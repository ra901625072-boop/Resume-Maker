"""
routes/auth.py — Authentication Blueprint
==========================================
Handles:
  GET  /login       → render login page / check status
  POST /login       → validate credentials, generate token & session
  GET  /signup      → render signup page / check status
  POST /signup      → create account, generate token & session
  GET/POST /logout  → clear session, token logout confirmation

Security:
  • Passwords hashed with Werkzeug (PBKDF2/SHA-256)
  • Dual-Auth: Cryptographic Bearer Tokens for cross-origin APIs + Flask-Login sessions
  • Rate limiting via Flask-Limiter to prevent brute-force attacks
  • Vague error messages on login failures to prevent user enumeration
"""

from datetime import datetime, timezone
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_user, logout_user

from backend.extensions import csrf, db, limiter
from backend.models import User, UserSettings
from backend.services.auth_token_service import generate_auth_token

auth_bp = Blueprint("auth", __name__)


def _get_frontend_redirect(fallback="/"):
    """Get the frontend origin for redirects if configured."""
    origins = current_app.config.get("CORS_ORIGINS", "*")
    if origins and origins != "*":
        if isinstance(origins, list) and len(origins) > 0:
            return origins[0]
        return origins
    return fallback


# ────────────────────────────────────────────────────────────────────────────
# Login
# ────────────────────────────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("15 per minute")
def login():
    """Render login form (GET) or authenticate user (POST)."""
    # If already authenticated (via session or Bearer token in request header)
    if current_user.is_authenticated:
        if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
            token = generate_auth_token(current_user.id, email=current_user.email, name=current_user.name)
            return jsonify({
                "success": True,
                "message": f"Welcome back, {current_user.name}! 👋",
                "token": token,
                "user": current_user.to_dict()
            })
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        # Extract credentials from JSON or Form data
        if request.is_json:
            body = request.get_json(silent=True) or {}
            email = body.get("email", "").strip().lower()
            password = body.get("password", "")
        else:
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

        # Server-side validation
        if not email or not password:
            return jsonify({
                "success": False,
                "error": "Email and password are required."
            }), 400

        user = User.query.filter_by(email=email).first()

        # Intentionally vague error message to prevent user enumeration
        if not user or not user.check_password(password):
            return jsonify({
                "success": False,
                "error": "Invalid email or password."
            }), 401

        if not user.is_active:
            return jsonify({
                "success": False,
                "error": "Your account has been deactivated. Contact support."
            }), 403

        # Update last_login timestamp
        try:
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Establish Flask-Login session
        login_user(user, remember=True)

        # Generate stateless cryptographic Bearer token
        token = generate_auth_token(
            user_id=user.id,
            email=user.email,
            name=user.name
        )

        if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
            return jsonify({
                "success": True,
                "message": f"Welcome back, {user.name}! 👋",
                "token": token,
                "user": user.to_dict()
            })

        flash(f"Welcome back, {user.name}! 👋", "success")
        next_page = request.args.get("next")
        if next_page and next_page.startswith("/"):
            return redirect(next_page)
        return redirect(url_for("main.dashboard"))

    return redirect(_get_frontend_redirect() + "/login")


# ────────────────────────────────────────────────────────────────────────────
# Sign Up
# ────────────────────────────────────────────────────────────────────────────
@auth_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def signup():
    """Render signup form (GET) or create a new account (POST)."""
    if current_user.is_authenticated:
        if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
            token = generate_auth_token(current_user.id, email=current_user.email, name=current_user.name)
            return jsonify({
                "success": True,
                "token": token,
                "user": current_user.to_dict()
            })
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        if request.is_json:
            body = request.get_json(silent=True) or {}
            name = body.get("name", "").strip()
            email = body.get("email", "").strip().lower()
            password = body.get("password", "")
            confirm_password = body.get("confirm_password", "")
        else:
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

        # ── Comprehensive server-side validation ──────────────────────────────
        if not name or len(name) < 2:
            return jsonify({"success": False, "error": "Full name must be at least 2 characters."}), 400
        if not email or "@" not in email or "." not in email:
            return jsonify({"success": False, "error": "A valid email address is required."}), 400
        if not password or len(password) < 8:
            return jsonify({"success": False, "error": "Password must be at least 8 characters long."}), 400
        if password != confirm_password:
            return jsonify({"success": False, "error": "Passwords do not match."}), 400

        # ── Duplicate email check ─────────────────────────────────────────────
        if User.query.filter_by(email=email).first():
            return jsonify({
                "success": False,
                "error": "An account with that email already exists. Please log in instead."
            }), 409

        # ── Create user + default settings in transaction ─────────────────────
        try:
            new_user = User(name=name, email=email)
            new_user.set_password(password)

            db.session.add(new_user)
            db.session.flush()  # obtain new_user.id before committing

            # Every user gets a default settings row
            default_settings = UserSettings(user_id=new_user.id)
            db.session.add(default_settings)
            db.session.commit()

            # Establish Flask-Login session
            login_user(new_user, remember=True)

            # Generate Bearer token
            token = generate_auth_token(
                user_id=new_user.id,
                email=new_user.email,
                name=new_user.name
            )

            if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
                return jsonify({
                    "success": True,
                    "message": f"Welcome to WISAXIS, {new_user.name}! 🎉",
                    "token": token,
                    "user": new_user.to_dict()
                }), 201

            flash(f"Welcome to WISAXIS, {new_user.name}! 🎉 Let's build your first resume.", "success")
            return redirect(url_for("main.dashboard"))
        except Exception:
            db.session.rollback()
            return jsonify({
                "success": False,
                "error": "An error occurred while creating your account. Please try again."
            }), 500

    return redirect(_get_frontend_redirect() + "/signup")


# ────────────────────────────────────────────────────────────────────────────
# Logout
# ────────────────────────────────────────────────────────────────────────────
@auth_bp.route("/logout", methods=["GET", "POST"])
@csrf.exempt
def logout():
    """Clear session and confirm logout."""
    if current_user.is_authenticated:
        user_name = current_user.name
        logout_user()
    else:
        user_name = "User"

    session.clear()

    if (
        request.is_json or
        request.headers.get("Accept") == "application/json" or
        request.headers.get("Origin") or
        request.headers.get("Authorization") or
        request.method == "POST"
    ):
        response = jsonify({
            "success": True,
            "message": "Logged out successfully"
        })
        response.set_cookie("session", "", expires=0)
        response.set_cookie("remember_token", "", expires=0)
        return response

    flash(f"You've been signed out. See you soon, {user_name}!", "info")
    response = redirect(url_for("main.home"))
    response.set_cookie("session", "", expires=0)
    response.set_cookie("remember_token", "", expires=0)
    return response
