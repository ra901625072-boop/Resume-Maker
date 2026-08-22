"""
backend/services/auth_token_service.py — Auth Token Service
============================================================
Provides stateless, cryptographically signed authentication tokens using
itsdangerous (built into Flask / Werkzeug).

Supports:
  - Token generation with custom expiration (default 30 days)
  - Token verification and payload extraction
  - Seamless integration with Flask-Login request_loader
"""

import time
from typing import Optional, Dict, Any
from flask import current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired


AUTH_SALT = "wisaxis-auth-token-salt-v1"
DEFAULT_TOKEN_EXPIRY = 30 * 24 * 3600  # 30 days in seconds


def _get_serializer() -> URLSafeTimedSerializer:
    """Return a serializer initialized with the current Flask secret key."""
    secret_key = current_app.config.get("SECRET_KEY", "wisaxis-secret-key-fallback")
    return URLSafeTimedSerializer(secret_key, salt=AUTH_SALT)


def generate_auth_token(
    user_id: int,
    email: str = "",
    name: str = "",
    expires_in_seconds: int = DEFAULT_TOKEN_EXPIRY
) -> str:
    """
    Generate a secure, signed auth token containing user identification and expiration.
    """
    serializer = _get_serializer()
    payload = {
        "user_id": user_id,
        "email": email,
        "name": name,
        "created_at": int(time.time()),
        "exp": int(time.time()) + expires_in_seconds
    }
    return serializer.dumps(payload)


def verify_auth_token(token: str, max_age: int = DEFAULT_TOKEN_EXPIRY) -> Optional[int]:
    """
    Verify the token signature and expiration.
    Returns the user_id (int) if valid, or None if invalid/expired.
    """
    if not token or not isinstance(token, str):
        return None

    # Handle 'Bearer <token>' format if passed directly
    if token.startswith("Bearer ") or token.startswith("bearer "):
        token = token.split(" ", 1)[1].strip()

    serializer = _get_serializer()
    try:
        payload = serializer.loads(token, max_age=max_age)
        if isinstance(payload, dict) and "user_id" in payload:
            return int(payload["user_id"])
        elif isinstance(payload, int):
            return payload
    except (SignatureExpired, BadSignature, Exception):
        return None

    return None


def decode_token_payload(token: str, max_age: int = DEFAULT_TOKEN_EXPIRY) -> Optional[Dict[str, Any]]:
    """
    Decode and return the full token payload dictionary if valid, else None.
    """
    if not token or not isinstance(token, str):
        return None

    if token.startswith("Bearer ") or token.startswith("bearer "):
        token = token.split(" ", 1)[1].strip()

    serializer = _get_serializer()
    try:
        payload = serializer.loads(token, max_age=max_age)
        if isinstance(payload, dict):
            return payload
    except (SignatureExpired, BadSignature, Exception):
        return None

    return None
