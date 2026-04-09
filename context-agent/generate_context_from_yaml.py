"""Utility to rebuild context records from YAML answer files or JSON fixtures."""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone
import json

import yaml

from app import create_app, mongo
from app.services.logic import generate_context_prompt, run_with_agent, load_questions

# Initialize Flask app
app = create_app()
app.app_context().push()

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
        return {key: str(value).strip() for key, value in content.items() if key in (
            "country", "region", "sector", "important_assets", "critical_assets",
            "current_security_operations", "methodology", "generic", "need",
        )}
    return {}


def parse_fixture(file_path):
    """Parse either YAML or JSON fixtures into context answer payload."""
    if file_path.suffix == ".json":
        return parse_json_answers(file_path)
    return parse_yaml_answers(file_path)

def recreate_context_from_answers(data):
    """Create context and interaction records, then run initial agent generation."""
    created_at = datetime.now(timezone.utc)
    initial_prompt = generate_context_prompt(data)

    context_result = mongo.db.contexts.insert_one({
        **data,
        "version": 1,
        "status": "pending",
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

    mongo.db.contexts.update_one(
        {"_id": context_id},
        {"$set": {"status": "completed"}}
    )

    print(f"Context created by: {data.get('country', 'unknown')} - {data.get('sector', 'unknown')}")

def process_directory(directory_path):
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
            recreate_context_from_answers(data)
        except Exception as e:
            print(f"Error with {file_path.name}: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python generate_context_from_yaml.py /path/to/answers")
        directory = Path(os.getenv('CONTEXT_IMPORT_PATH', '/context-agent/app/config/examples/answers'))
    else: 
        directory = Path(sys.argv[1])

    if not directory.is_dir():
        print(f"The path {directory} is invalid..")
        sys.exit(1)

    # Clean the full database
    mongo.db.interactions.delete_many({})
    mongo.db.contexts.delete_many({})
    print("Database cleaned.")

    process_directory(directory)
