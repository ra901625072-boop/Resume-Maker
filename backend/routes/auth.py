"""
routes/auth.py — Authentication Blueprint
==========================================
Stateless Bearer token authentication endpoints:
  POST /api/auth/signup  → register new user account
  POST /api/auth/login   → authenticate credentials & issue token
  POST /api/auth/logout  → client-side token discard acknowledgement
  GET  /api/auth/me      → get current authenticated user profile
"""

import re
from datetime import datetime, timezone
from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.security import check_password_hash

from backend.extensions import db, limiter
from backend.models.user import User, UserSettings
from backend.services.auth_token_service import generate_auth_token, token_required

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DUMMY_PASSWORD_HASH = (
    "pbkdf2:sha256:260000$dummy$4b0870932bb82f7188719f9bb699a224f8d672df6c5fe56b8209ebfae7136005"
)


# ────────────────────────────────────────────────────────────────────────────
# User Registration
# ────────────────────────────────────────────────────────────────────────────
@auth_bp.route("/signup", methods=["POST"])
@limiter.limit("5 per minute")
def signup():
    """
    Register a new user, create their default settings, and return an auth token.
    Body: { name, email, password, confirm_password }
    """
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    confirm_password = body.get("confirm_password") or ""

    # Validation
    if not name or len(name) < 2:
        return jsonify({"success": False, "error": "Name must be at least 2 characters long."}), 422

    if not email or not EMAIL_REGEX.match(email):
        return jsonify({"success": False, "error": "A valid email address is required."}), 422

    if not password or len(password) < 8:
        return jsonify({"success": False, "error": "Password must be at least 8 characters long."}), 422

    if password != confirm_password:
        return jsonify({"success": False, "error": "Passwords do not match."}), 422

    # Check for existing account
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({"success": False, "error": "An account with this email already exists."}), 409

    try:
        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        # Create default preferences
        settings = UserSettings(user_id=user.id)
        db.session.add(settings)
        db.session.commit()

        token = generate_auth_token(user_id=user.id, email=user.email, name=user.name)
        return jsonify({
            "success": True,
            "message": "Account created successfully.",
            "token": token,
            "user": user.to_dict(),
        }), 201

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Signup error")
        return jsonify({"success": False, "error": "Could not complete registration. Please try again."}), 500


# ────────────────────────────────────────────────────────────────────────────
# User Login
# ────────────────────────────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    """
    Verify credentials and return a Bearer auth token.
    Body: { email, password }
    """
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return jsonify({"success": False, "error": "Invalid email or password."}), 401

    user = User.query.filter_by(email=email).first()

    # Mitigate user enumeration and timing attacks:
    # Always run check_password_hash even when user is None
    if not user or not user.is_active:
        check_password_hash(DUMMY_PASSWORD_HASH, password)
        return jsonify({"success": False, "error": "Invalid email or password."}), 401

    if not user.check_password(password):
        return jsonify({"success": False, "error": "Invalid email or password."}), 401

    try:
        user.last_login_at = datetime.now(timezone.utc)
        db.session.commit()

        token = generate_auth_token(user_id=user.id, email=user.email, name=user.name)
        return jsonify({
            "success": True,
            "message": "Logged in successfully.",
            "token": token,
            "user": user.to_dict(),
        }), 200

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Login error")
        return jsonify({"success": False, "error": "Login failed. Please try again."}), 500


# ────────────────────────────────────────────────────────────────────────────
# Logout
# ────────────────────────────────────────────────────────────────────────────
@auth_bp.route("/logout", methods=["POST"])
def logout():
    """
    Stateless logout confirmation.
    The client discards the Bearer token from localStorage.
    """
    return jsonify({"success": True, "message": "Logged out successfully."}), 200


# ────────────────────────────────────────────────────────────────────────────
# Current User Profile
# ────────────────────────────────────────────────────────────────────────────
@auth_bp.route("/me", methods=["GET"])
@token_required
def get_current_user():
    """Return profile data for the authenticated user."""
    return jsonify({"success": True, "data": g.current_user.to_dict()}), 200


# ────────────────────────────────────────────────────────────────────────────
# Update User Profile & Settings
# ────────────────────────────────────────────────────────────────────────────
@auth_bp.route("/profile", methods=["PUT"])
@token_required
@limiter.limit("15 per minute")
def update_profile():
    """
    Update the authenticated user's name, email, or settings preferences.
    Body: { name, email, default_template, theme_preference, email_notifications }
    """
    body = request.get_json(silent=True) or {}
    user = g.current_user

    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()

    if name:
        if len(name) < 2:
            return jsonify({"success": False, "error": "Name must be at least 2 characters long."}), 422
        user.name = name

    if email and email != user.email:
        if not EMAIL_REGEX.match(email):
            return jsonify({"success": False, "error": "A valid email address is required."}), 422

        existing = User.query.filter_by(email=email).first()
        if existing and existing.id != user.id:
            return jsonify({"success": False, "error": "An account with this email already exists."}), 409
        user.email = email

    # Update or create UserSettings
    settings = user.settings
    if not settings:
        settings = UserSettings(user_id=user.id)
        db.session.add(settings)

    if "default_template" in body:
        tpl = str(body["default_template"]).strip()
        if tpl:
            settings.default_template = tpl[:50]

    if "theme_preference" in body:
        theme = str(body["theme_preference"]).strip()
        if theme in {"light", "dark"}:
            settings.theme_preference = theme

    if "email_notifications" in body:
        settings.email_notifications = bool(body["email_notifications"])

    try:
        db.session.commit()
        # Generate fresh token in case name/email changed
        new_token = generate_auth_token(user_id=user.id, email=user.email, name=user.name)
        return jsonify({
            "success": True,
            "message": "Profile updated successfully.",
            "token": new_token,
            "user": user.to_dict(),
        }), 200
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Profile update error")
        return jsonify({"success": False, "error": "Could not update profile. Please try again."}), 500


# ────────────────────────────────────────────────────────────────────────────
# Change Password
# ────────────────────────────────────────────────────────────────────────────
@auth_bp.route("/change-password", methods=["POST"])
@token_required
@limiter.limit("5 per minute")
def change_password():
    """
    Update authenticated user password after verifying current credentials.
    Body: { current_password, new_password, confirm_password }
    """
    body = request.get_json(silent=True) or {}
    user = g.current_user

    current_password = body.get("current_password") or ""
    new_password = body.get("new_password") or ""
    confirm_password = body.get("confirm_password") or ""

    if not current_password:
        return jsonify({"success": False, "error": "Current password is required."}), 422

    if not user.check_password(current_password):
        return jsonify({"success": False, "error": "Current password is incorrect."}), 401

    if not new_password or len(new_password) < 8:
        return jsonify({"success": False, "error": "New password must be at least 8 characters long."}), 422

    if new_password != confirm_password:
        return jsonify({"success": False, "error": "New passwords do not match."}), 422

    if current_password == new_password:
        return jsonify({"success": False, "error": "New password must be different from current password."}), 422

    try:
        user.set_password(new_password)
        db.session.commit()

        new_token = generate_auth_token(user_id=user.id, email=user.email, name=user.name)
        return jsonify({
            "success": True,
            "message": "Password changed successfully.",
            "token": new_token,
        }), 200
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Change password error")
        return jsonify({"success": False, "error": "Could not change password. Please try again."}), 500


# ────────────────────────────────────────────────────────────────────────────
# User Account Statistics
# ────────────────────────────────────────────────────────────────────────────
@auth_bp.route("/stats", methods=["GET"])
@token_required
def user_stats():
    """Return summary activity metrics for the authenticated user."""
    from backend.models.resume import Resume
    from backend.models.export_history import ExportHistory
    from backend.models.ai_history import AIHistory

    user_id = g.current_user.id
    total_resumes = Resume.query.filter_by(user_id=user_id, is_deleted=False).count()
    total_exports = ExportHistory.query.filter_by(user_id=user_id).count()
    total_ai_requests = AIHistory.query.filter_by(user_id=user_id).count()

    return jsonify({
        "success": True,
        "data": {
            "total_resumes": total_resumes,
            "total_exports": total_exports,
            "total_ai_requests": total_ai_requests,
            "member_since": g.current_user.created_at.isoformat() if g.current_user.created_at else None,
            "last_login": g.current_user.last_login_at.isoformat() if g.current_user.last_login_at else None,
        }
    }), 200

