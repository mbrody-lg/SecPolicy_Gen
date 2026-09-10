"""Provider-neutral OpenID Connect boundary for human users."""

from __future__ import annotations

from urllib.parse import urlparse

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.flask_client import OAuth
from flask import Blueprint, current_app, g, jsonify, redirect, request, session, url_for
from pymongo.errors import PyMongoError


identity = Blueprint("identity", __name__, url_prefix="/auth")
oauth = OAuth()

PUBLIC_ENDPOINTS = frozenset(
    {
        "identity.login",
        "identity.callback",
        "main.health",
        "main.ready",
        "main.metrics",
        "static",
    }
)


def init_identity(app) -> None:
    """Register the configured OIDC provider without provider-specific code."""
    oauth.init_app(app)
    oauth.register(
        name="oidc",
        client_id=app.config["OIDC_CLIENT_ID"],
        client_secret=app.config["OIDC_CLIENT_SECRET"],
        server_metadata_url=(
            f"{app.config['OIDC_ISSUER_URL'].rstrip('/')}/.well-known/openid-configuration"
        ),
        client_kwargs={
            "scope": app.config["OIDC_SCOPES"],
            "code_challenge_method": "S256",
        },
    )


def _safe_local_path(value: str | None) -> str:
    """Return a local redirect path and reject external or scheme-relative URLs."""
    candidate = (value or "").strip()
    parsed = urlparse(candidate)
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/"
    if parsed.scheme or parsed.netloc:
        return "/"
    return candidate


def _bounded_claim(value, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:limit]


def current_principal() -> dict | None:
    """Return the verified minimal principal stored in the signed session."""
    principal = session.get("principal")
    if not isinstance(principal, dict):
        return None
    issuer = principal.get("issuer")
    subject = principal.get("subject")
    if not isinstance(issuer, str) or not issuer:
        return None
    if not isinstance(subject, str) or not subject:
        return None
    return principal


def require_authenticated_principal():
    """Protect every route except the explicit runtime and login allowlist."""
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None

    principal = current_principal()
    if principal is not None:
        g.principal = principal
        return None

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": False, "error_code": "authentication_required"}), 401

    return redirect(url_for("identity.login", next=_safe_local_path(request.full_path)))


@identity.get("/login")
def login():
    """Start an OIDC Authorization Code flow with PKCE."""
    session["post_auth_redirect"] = _safe_local_path(request.args.get("next"))
    return oauth.oidc.authorize_redirect(current_app.config["OIDC_REDIRECT_URI"])


@identity.get("/callback")
def callback():
    """Validate the OIDC response and establish a minimal application session."""
    try:
        token = oauth.oidc.authorize_access_token()
    except OAuthError:
        current_app.logger.warning("OIDC callback validation failed")
        session.clear()
        return jsonify({"success": False, "error_code": "authentication_failed"}), 401
    userinfo = token.get("userinfo") if isinstance(token, dict) else None
    if not isinstance(userinfo, dict) or not _bounded_claim(userinfo.get("sub"), limit=255):
        return jsonify({"success": False, "error_code": "invalid_identity"}), 401

    redirect_path = _safe_local_path(session.get("post_auth_redirect"))
    principal = {
        "issuer": _bounded_claim(userinfo.get("iss"), limit=2048),
        "subject": _bounded_claim(userinfo.get("sub"), limit=255),
    }
    if principal["issuer"] != current_app.config["OIDC_ISSUER_URL"]:
        session.clear()
        return jsonify({"success": False, "error_code": "invalid_identity"}), 401
    from app.access_control import sync_principal

    try:
        sync_principal(**principal)
    except PermissionError:
        session.clear()
        return jsonify({"success": False, "error_code": "principal_disabled"}), 403
    except PyMongoError:
        current_app.logger.exception("OIDC principal synchronization failed")
        session.clear()
        return jsonify({"success": False, "error_code": "identity_store_unavailable"}), 503
    session.clear()
    session["principal"] = principal
    session.permanent = True
    return redirect(redirect_path)


@identity.post("/logout")
def logout():
    """Clear the local session without exposing provider tokens to the browser."""
    session.clear()
    return redirect("/")
