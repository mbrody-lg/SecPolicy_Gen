from app.routes.route_security import (
    MUTATION_BOUNDARY_DECISION,
    OPERATOR_UI_MUTATION,
    ROUTE_SECURITY_CLASSIFICATIONS,
    SERVICE_CALLBACK,
    route_security_inventory,
)


ALLOWED_CATEGORIES = {
    "authenticated_read",
    "public_read",
    "operator_ui_mutation",
    "service_to_service_callback",
    "runtime_endpoint",
}


def _application_routes(app):
    return {
        (method, rule.rule)
        for rule in app.url_map.iter_rules()
        if rule.endpoint != "static"
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"})
    }


def test_all_context_agent_routes_have_security_classification(app):
    inventory = route_security_inventory()

    assert set(inventory) == _application_routes(app)


def test_all_mutating_routes_have_next_boundary_decision(app):
    inventory = route_security_inventory()
    post_routes = {
        key: classification
        for key, classification in inventory.items()
        if key[0] == "POST"
    }

    assert post_routes
    assert all(classification.next_control != "none" for classification in post_routes.values())


def test_route_security_categories_are_allowlisted():
    assert {item.category for item in ROUTE_SECURITY_CLASSIFICATIONS} <= ALLOWED_CATEGORIES


def test_policy_callback_is_not_classified_as_operator_ui_mutation():
    inventory = route_security_inventory()

    policy_callback = inventory[("POST", "/context/<context_id>/policy")]

    assert policy_callback.category == SERVICE_CALLBACK
    assert policy_callback.category != OPERATOR_UI_MUTATION
    assert policy_callback.next_control == "service_to_service_auth"


def test_mutation_boundary_decision_tracks_the_next_security_boundary():
    assert MUTATION_BOUNDARY_DECISION["decision"] == "identity_first_then_resource_authorization"
    assert "resource authorization" in MUTATION_BOUNDARY_DECISION["reason"]
