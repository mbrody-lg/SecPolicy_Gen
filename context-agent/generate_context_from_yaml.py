import os
import sys
import yaml
from pathlib import Path
from datetime import datetime, timezone

from app import create_app, mongo
from app.services.logic import generate_context_prompt, run_with_agent, load_questions

# Inicialitza Flask app
app = create_app()
app.app_context().push()

def parse_yaml_answers(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = yaml.safe_load(f)
        answers = content.get('answers', [])
        return {item['id']: item['answer'].strip() for item in answers if 'id' in item and 'answer' in item}

def recreate_context_from_answers(data):
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

    full_prompt = run_with_agent(initial_prompt, str(context_id))
    mongo.db.interactions.insert_one({
        "context_id": context_id,
        "question_id": "response_initial",
        "question_text": "Resposta de l'agent",
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
    yaml_files = Path(directory_path).glob("*.yaml")
    for file_path in yaml_files:
        print(f"Processing {file_path.name}...")
        try:
            data = parse_yaml_answers(file_path)
            recreate_context_from_answers(data)
        except Exception as e:
            print(f"Error with {file_path.name}: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python generate_context_from_yaml.py /ruta/a/answers")
        directory = Path(os.getenv('CONTEXT_IMPORT_PATH', '/context-agent/app/config/examples/answers'))
    else: 
        directory = Path(sys.argv[1])

    if not directory.is_dir():
        print(f"The path {directory} is invalid..")
        sys.exit(1)

    # Esborrem tota la base de dades
    mongo.db.interactions.delete_many({})
    mongo.db.contexts.delete_many({})
    print("Database cleaned.")

    process_directory(directory)