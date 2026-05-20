"""Utility to rebuild context records from YAML answer files or JSON fixtures."""

import argparse
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
import json

import yaml

from app import create_app, mongo
from app.services.logic import (
    SECURITY_CONTEXT_VERSION,
    approve_context_intelligence_plan,
    build_context_building_state,
    build_context_security_context,
    build_context_intelligence_plan,
    context_answer_fields,
    generate_context_plan_prompt,
    run_with_agent,
    load_questions,
)

_APP_CONTEXT = None


def initialize_app_context():
    """Initialize Flask context when running this module as a CLI script."""
    global _APP_CONTEXT
    if _APP_CONTEXT is None:
        app = create_app()
        _APP_CONTEXT = app.app_context()
        _APP_CONTEXT.push()

def parse_yaml_answers(file_path):
    """Parse answers from a YAML file into an id->answer dictionary."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = yaml.safe_load(f)
        answers = content.get("answers", [])
        return {item['id']: item['answer'].strip() for item in answers if 'id' in item and 'answer' in item}


def parse_json_answers(file_path):
    """Parse answers from a migration JSON fixture into an id->answer dictionary."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = json.load(f)
    if "context" in content and isinstance(content["context"], dict):
        return {key: str(value).strip() for key, value in content["context"].items()}
    if "answers" in content and isinstance(content["answers"], list):
        return {
            item["id"]: str(item.get("answer", "")).strip()
            for item in content["answers"]
            if isinstance(item, dict) and "id" in item
        }
    if isinstance(content, dict):
        allowed_fields = context_answer_fields()
        return {key: str(value).strip() for key, value in content.items() if key in allowed_fields}
    return {}


def parse_fixture(file_path):
    """Parse either YAML or JSON fixtures into context answer payload."""
    if file_path.suffix == ".json":
        return parse_json_answers(file_path)
    return parse_yaml_answers(file_path)

def recreate_context_from_answers(data, *, auto_approve_plan=False):
    """Create context records and the first reviewable context-intelligence plan."""
    created_at = datetime.now(timezone.utc)
    initial_prompt = generate_context_plan_prompt(data)
    security_context = build_context_security_context(data)
    context_building = build_context_building_state(
        data,
        security_context=security_context,
        bypassed=auto_approve_plan,
    )
    context_plan = build_context_intelligence_plan(data)

    context_result = mongo.db.contexts.insert_one({
        **data,
        "version": 1,
        "security_context_version": SECURITY_CONTEXT_VERSION,
        "security_context": security_context,
        "context_building": context_building,
        "context_intelligence_plan": context_plan,
        "status": (
            "context_building_needs_input"
            if context_building["status"] == "needs_information"
            else "planning"
        ),
        "created_at": created_at
    })
    context_id = context_result.inserted_id

    questions = load_questions()
    for q in questions:
        mongo.db.interactions.insert_one({
            "context_id": context_id,
            "question_id": f"q_{q['id']}",
            "question_text": q["question"],
            "answer": "",
            "timestamp": created_at,
            "origin": "agent"
        })
        mongo.db.interactions.insert_one({
            "context_id": context_id,
            "question_id": q["id"],
            "question_text": q["question"],
            "answer": data.get(q["id"], "").strip(),
            "timestamp": created_at,
            "origin": "user"
        })

    full_prompt = run_with_agent(initial_prompt, str(context_id), model_version="0.1.0")
    mongo.db.interactions.insert_one({
        "context_id": context_id,
        "question_id": "response_initial",
        "question_text": "Agent response",
        "answer": full_prompt.strip(),
        "timestamp": datetime.now(timezone.utc),
        "origin": "agent"
    })

    status = (
        "context_building_needs_input"
        if context_building["status"] == "needs_information"
        else "awaiting_task_validation"
    )
    update_payload = {"status": status}
    if auto_approve_plan:
        context_record = {
            **data,
            "_id": context_id,
            "security_context": security_context,
            "context_intelligence_plan": context_plan,
        }
        update_payload = {
            "status": "context_plan_approved",
            "context_building": build_context_building_state(
                data,
                security_context=security_context,
                existing=context_building,
                bypassed=True,
            ),
            "context_intelligence_plan": approve_context_intelligence_plan(
                context_record,
                "Automatically approved during fixture import.",
                approved_by="fixture-import",
                approval_source="generate_context_from_yaml",
            ),
        }
        status = "context_plan_approved"

    mongo.db.contexts.update_one(
        {"_id": context_id},
        {"$set": update_payload}
    )

    print(
        f"Context created by: {data.get('country', 'unknown')} - "
        f"{data.get('sector', 'unknown')} [{status}]"
    )

def process_directory(directory_path, *, auto_approve_plan=False):
    """Process every fixture file in a directory and recreate its context."""
    fixtures = sorted(
        list(Path(directory_path).glob("*.yaml"))
        + list(Path(directory_path).glob("*.yml"))
        + list(Path(directory_path).glob("*.json"))
    )
    for file_path in fixtures:
        if file_path.name == "schema.json":
            continue
        print(f"Processing {file_path.name}...")
        try:
            data = parse_fixture(file_path)
            recreate_context_from_answers(data, auto_approve_plan=auto_approve_plan)
        except Exception as e:
            print(f"Error with {file_path.name}: {e}")

def _env_flag(name):
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def parse_args(argv):
    """Parse CLI arguments for context fixture import."""
    parser = argparse.ArgumentParser(
        description="Rebuild context records from YAML answer files or JSON fixtures.",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=os.getenv(
            "CONTEXT_IMPORT_PATH",
            "/context-agent/app/config/examples/answers",
        ),
        help="Directory containing YAML or JSON context fixtures.",
    )
    parser.add_argument(
        "--auto-approve-plan",
        action="store_true",
        default=_env_flag("CONTEXT_IMPORT_AUTO_APPROVE_PLAN"),
        help="Mark generated context-intelligence plans as approved after import.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    initialize_app_context()
    args = parse_args(sys.argv[1:])
    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"The path {directory} is invalid..")
        sys.exit(1)

    # Clean the full database
    mongo.db.interactions.delete_many({})
    mongo.db.contexts.delete_many({})
    print("Database cleaned.")

    process_directory(directory, auto_approve_plan=args.auto_approve_plan)
