"""
backend/services/auth_token_service.py — Bearer Token Service & Decorator
=========================================================================
Handles cryptographic token generation and verification for stateless
cross-origin authentication between frontend (Vercel) and backend (Render).
"""

from functools import wraps
from flask import current_app, g, jsonify, request
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

from backend.extensions import db
from backend.models.user import User

TOKEN_SALT = "wisaxis-auth-token"
DEFAULT_TOKEN_EXPIRY = 30 * 24 * 3600  # 30 days in seconds


def _get_serializer() -> URLSafeTimedSerializer:
    """Return a timed serializer configured with the app SECRET_KEY."""
    secret = current_app.config.get("SECRET_KEY", "fallback-secret-key")
    return URLSafeTimedSerializer(secret_key=secret, salt=TOKEN_SALT)


def generate_auth_token(user_id: int, email: str, name: str, expires_in_seconds: int = DEFAULT_TOKEN_EXPIRY) -> str:
    """
    Generate a signed URL-safe token carrying user payload.
    """
    serializer = _get_serializer()
    payload = {
        "user_id": user_id,
        "email": email,
        "name": name,
    }
    return serializer.dumps(payload)


def verify_auth_token(auth_header_or_token: str, max_age: int = DEFAULT_TOKEN_EXPIRY):
    """
    Verify a signed auth token or an Authorization header value (Bearer <token>).
    Returns user_id if valid, or None if invalid or expired.
    """
    if not auth_header_or_token:
        return None

    token = str(auth_header_or_token).strip()
    if token.startswith("Bearer ") or token.startswith("bearer "):
        token = token.split(" ", 1)[1].strip()

    if not token:
        return None

    serializer = _get_serializer()
    try:
        data = serializer.loads(token, max_age=max_age)
        return data.get("user_id")
    except (SignatureExpired, BadSignature, Exception):
        return None


def token_required(fn):
    """
    Decorator for endpoints requiring Bearer token authentication.
    Extracts Bearer token from the Authorization header, validates it,
    loads the User object into flask.g.current_user, and returns 401 JSON
    if unauthenticated.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        user_id = verify_auth_token(auth_header)
        if not user_id:
            return jsonify({"success": False, "error": "Authentication required."}), 401

        user = db.session.get(User, user_id)
        if not user or not user.is_active:
            return jsonify({"success": False, "error": "Authentication required."}), 401

        g.current_user = user
        return fn(*args, **kwargs)

    return wrapper
