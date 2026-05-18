import generate_context_from_yaml as importer


def test_recreate_context_from_answers_creates_reviewable_plan(monkeypatch):
    monkeypatch.setattr(
        importer,
        "run_with_agent",
        lambda prompt, context_id, model_version=None: "Review this context plan.",
    )

    importer.mongo.db.contexts.delete_many({})
    importer.mongo.db.interactions.delete_many({})

    importer.recreate_context_from_answers({
        "country": "Spain",
        "sector": "Healthcare",
        "company_activity": "Private clinic",
        "critical_assets": "Patient records",
        "data_categories": "health_data",
        "need": "Build a security plan",
    })

    context = importer.mongo.db.contexts.find_one({"country": "Spain"})
    assert context["status"] == "awaiting_task_validation"
    assert context["security_context"]["profile"]["sector"] == "Healthcare"
    assert context["context_intelligence_plan"]["status"] == "draft"
    assert context["context_intelligence_plan"]["tasks"][0]["id"] == "company_profile"
    assert "refined_prompt" not in context

    response = importer.mongo.db.interactions.find_one({
        "context_id": context["_id"],
        "question_id": "response_initial",
    })
    assert response["answer"] == "Review this context plan."


def test_recreate_context_from_answers_can_auto_approve_plan(monkeypatch):
    monkeypatch.setattr(
        importer,
        "run_with_agent",
        lambda prompt, context_id, model_version=None: "Review this context plan.",
    )

    importer.mongo.db.contexts.delete_many({})
    importer.mongo.db.interactions.delete_many({})

    importer.recreate_context_from_answers(
        {
            "country": "France",
            "sector": "E-commerce",
            "critical_assets": "Payment flow",
            "need": "Build a security plan",
        },
        auto_approve_plan=True,
    )

    context = importer.mongo.db.contexts.find_one({"country": "France"})
    plan = context["context_intelligence_plan"]
    assert context["status"] == "context_plan_approved"
    assert plan["status"] == "approved"
    assert plan["review"]["required"] is False
    assert plan["review"]["user_feedback"] == (
        "Automatically approved during fixture import."
    )
    assert {task["status"] for task in plan["tasks"]} == {"approved"}


def test_parse_args_supports_auto_approve_env(monkeypatch):
    monkeypatch.setenv("CONTEXT_IMPORT_AUTO_APPROVE_PLAN", "true")

    args = importer.parse_args(["/tmp/fixtures"])

    assert args.directory == "/tmp/fixtures"
    assert args.auto_approve_plan is True
