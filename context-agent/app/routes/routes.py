from flask import Blueprint, render_template, request, redirect, url_for, abort, flash, jsonify
from app.services.logic import generate_context_prompt, run_with_agent, load_questions, generate_full_policy_pipeline, render_markdown
from app import mongo
from datetime import datetime, timezone
from bson import ObjectId

main = Blueprint("main", __name__)

@main.route("/")
def index():
    per_page = 10
    page = max(int(request.args.get("page", 1)), 1)
    status_filter = request.args.get("status", "")
    sort_order = request.args.get("sort", "desc")

    query = {}
    if status_filter:
        query["status"] = status_filter

    sort_dir = -1 if sort_order == "desc" else 1
    sort_param = [("created_at", sort_dir)]

    fields = {
        "created_at": 1,
        "version": 1,
        "status": 1,
        "country": 1,
        "region": 1,
        "sector": 1,
        "generic": 1,
        "need": 1
    }

    collection = mongo.db.contexts
    total_count = collection.count_documents(query)
    contexts = (
        collection.find(query, fields)
        .sort(sort_param)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )

    return render_template(
        "dashboard.html",
        contexts=contexts,
        page=page,
        per_page=per_page,
        total_count=total_count,
        status_filter=status_filter,
        sort_order=sort_order
    )

@main.route("/create", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        allowed_fields = {"country", "region", "sector", "important_assets", "critical_assets", "current_security_operations", "methodology", "generic", "need"}
        data = {k: v.strip() for k, v in request.form.items() if k in allowed_fields}

        initial_prompt = generate_context_prompt(data)

        created_at = datetime.now(timezone.utc)

        inserted = mongo.db.contexts.insert_one({
            **data,
            "version": 1,
            "status": "pending",
            "created_at": created_at
        })

        context_id = inserted.inserted_id

        # Desa preguntes i respostes per separat com a interacció d'agent (pregunta) i usuari (resposta)
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
                "answer": data.get(q["id"]).strip() if data.get(q["id"]) else "",
                "timestamp": created_at,
                "origin": "user"
            })

        # Enviem el prompt a l'agent per generar el context refinat
        full_prompt = run_with_agent(initial_prompt, str(context_id))

        if not full_prompt or not full_prompt.strip():
            flash("An initial response could not be generated. Please try again.", "warning")
            return redirect(url_for("main.context_detail", context_id=context_id))

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

        return redirect(url_for("main.context_detail", context_id=context_id))

    questions = load_questions()
    return render_template(
        "create_context.html",
        questions=questions
    )

@main.route("/context/<context_id>")
def context_detail(context_id):
    from bson.errors import InvalidId
    try:
        context_id = ObjectId(context_id)
        context = mongo.db.contexts.find_one({"_id": context_id})
        if not context:
            return abort(404, "Context not found.")

        interactions = list(
            mongo.db.interactions.find({"context_id": context_id}).sort("timestamp", 1)
        )
        # Processem només les respostes dels agents per afegir-hi format HTML des del Markdown
        for item in interactions:
            if item.get("origin") == "agent" and item.get("answer"):
                item["rendered_answer"] = render_markdown(item["answer"])
            else:
                item["rendered_answer"] = item.get("answer", "")

    except (InvalidId, TypeError, Exception):
        return abort(400, "Invalid identifier.")

    return render_template(
        "context_detail.html",
        context=context,
        interactions=interactions
    )

@main.route("/context/<context_id>/continue", methods=["POST"])
def continue_context(context_id):
    context = mongo.db.contexts.find_one({"_id": ObjectId(context_id)})
    if not context:
        return abort(404, "Context not found.")

    new_prompt = request.form.get("prompt", "").strip()
    if not new_prompt:
        return redirect(url_for("main.context_detail", context_id=context_id))

    count = mongo.db.interactions.count_documents({
        "context_id": ObjectId(context_id),
        "question_id": {"$regex": "^need"}
    })
    new_question_id = f"need_{count + 1}"

    # 1. Desa la interacció de l'usuari
    mongo.db.interactions.insert_one({
        "context_id": ObjectId(context_id),
        "question_id": new_question_id,
        "question_text": "Add more information or questions...",
        "answer": new_prompt,
        "timestamp": datetime.now(timezone.utc),
        "origin": "user"
    })

    # 2. Executa l'agent
    response = run_with_agent(new_prompt, context_id)

    # 3. Si no hi ha resposta vàlida → no es desa resposta i el context queda pendent
    if not response or not response.strip():
        mongo.db.contexts.update_one(
            {"_id": ObjectId(context_id)},
            {"$set": {"status": "pending"}}
        )
        flash("A response could not be generated. Please try again.", "warning")
        return redirect(url_for("main.context_detail", context_id=context_id))

    # 4. Desa la resposta de l'agent
    mongo.db.interactions.insert_one({
        "context_id": ObjectId(context_id),
        "question_id": f"response_{count + 1}",
        "question_text": "Agent response",
        "answer": response.strip(),
        "timestamp": datetime.now(timezone.utc),
        "origin": "agent"
    })

    mongo.db.contexts.update_one(
        {"_id": ObjectId(context_id)},
        {"$set": {"status": "completed"}}
    )

    return redirect(url_for("main.context_detail", context_id=context_id))

@main.route("/context/<context_id>/delete", methods=["POST"])
def delete_context(context_id):
    try:
        result = mongo.db.contexts.delete_one({"_id": ObjectId(context_id)})
        mongo.db.interactions.delete_many({"context_id": ObjectId(context_id)})
        if result.deleted_count == 1:
            flash("Context successfully removed.", "success")
        else:
            flash("The context could not be deleted.", "warning")
    except Exception:
        flash("Error deleting context.", "danger")

    return redirect(url_for("main.index"))

@main.route("/context/<context_id>/policy", methods=["POST"])
def send_policy_to_context(context_id):
    try:
        data = request.get_json(force=True)

        required_fields = ["policy_text", "generated_at", "policy_agent_version", "language"]
        missing = [field for field in required_fields if field not in data]

        if missing:
            return jsonify({
                "error": f"Missing required fields: {', '.join(missing)}"
            }), 400

        try:
            context_obj_id = ObjectId(context_id)
        except Exception:
            return jsonify({"error": "Invalid context_id format."}), 400

        validated_at = datetime.now(timezone.utc)

        # Desa la política com una resposta de l'agent a interactions
        mongo.db.interactions.insert_one({
            "context_id": context_obj_id,
            "question_id": "validated_policy",
            "question_text": "Agent-generated policy",
            "answer": data["policy_text"],
            "timestamp": validated_at,
            "origin": "agent",
            "status": data.get("status", "review"),
            "recommendations": data.get("recommendations", [])
        })

        return redirect(url_for("main.context_detail", context_id=context_id))

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main.route("/context/<context_id>/generate_policy", methods=["POST"])
def trigger_policy_generation(context_id):
    result = generate_full_policy_pipeline(context_id)
    if result.get("success"):
        flash("Policy successfully generated and validated.", "success")
    else:
        flash(f"Error in generation or validation: {result.get('error')} - {result.get('details')}", "danger")
    return redirect(url_for("main.context_detail", context_id=context_id))
