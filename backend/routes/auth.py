"""
routes/auth.py — Authentication Blueprint
==========================================
Handles:
  GET  /login       → render login page
  POST /login       → validate credentials, create session
  GET  /signup      → render signup page
  POST /signup      → create account
  GET  /logout      → clear session, redirect to home

Security:
  • Passwords hashed with Werkzeug (bcrypt-backed PBKDF2)
  • CSRF token on every form (Flask-WTF)
  • Login required enforced via Flask-Login on protected routes
  • Failed logins do NOT reveal whether the email exists (prevents user enumeration)
"""

from flask import (Blueprint, flash, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user, login_required, login_user, logout_user

from backend.extensions import db, limiter, csrf
from backend.models import User, UserSettings

auth_bp = Blueprint("auth", __name__)


# ────────────────────────────────────────────────────────────────────────────
# Login
# ────────────────────────────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")   # brute-force protection
def login():
    """Render login form (GET) or authenticate user (POST)."""
    # Already authenticated → skip to dashboard
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        # Basic server-side validation
        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("login.html"), 400

        user = User.query.filter_by(email=email).first()

        # Intentionally vague error — prevents user enumeration
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "error")
            return render_template("login.html"), 401

        if not user.is_active:
            flash("Your account has been deactivated. Contact support.", "error")
            return render_template("login.html"), 403

        # Update last_login timestamp
        from datetime import datetime, timezone
        user.last_login_at = datetime.now(timezone.utc)
        db.session.commit()

        login_user(user, remember=True)
        flash(f"Welcome back, {user.name}! 👋", "success")

        # Honour the ?next= redirect parameter (must be relative path)
        next_page = request.args.get("next")
        if next_page and next_page.startswith("/"):
            return redirect(next_page)
        return redirect(url_for("main.dashboard"))

    return render_template("login.html")


# ────────────────────────────────────────────────────────────────────────────
# Sign Up
# ────────────────────────────────────────────────────────────────────────────
@auth_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def signup():
    """Render signup form (GET) or create a new account (POST)."""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        name             = request.form.get("name", "").strip()
        email            = request.form.get("email", "").strip().lower()
        password         = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # ── Server-side validation ────────────────────────────────────────────
        errors = []
        if not name or len(name) < 2:
            errors.append("Full name must be at least 2 characters.")
        if not email or "@" not in email:
            errors.append("A valid email address is required.")
        if not password or len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm_password:
            errors.append("Passwords do not match.")

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template("signup.html"), 400

        # ── Duplicate email check ─────────────────────────────────────────────
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists. Try logging in.", "error")
            return render_template("signup.html"), 409

        # ── Create user + default settings ───────────────────────────────────
        new_user = User(name=name, email=email)
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.flush()  # get the new_user.id before commit

        # Every user gets a default settings row
        default_settings = UserSettings(user_id=new_user.id)
        db.session.add(default_settings)
        db.session.commit()

        login_user(new_user, remember=True)
        flash(f"Welcome to WISAXIS, {new_user.name}! 🎉 Let's build your first resume.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("signup.html")


# ────────────────────────────────────────────────────────────────────────────
# Logout
# ────────────────────────────────────────────────────────────────────────────
@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
@csrf.exempt
def logout():
    """Clear the session and redirect to landing page."""
    user_name = current_user.name
    logout_user()
    session.clear()
    
    if request.method == "POST" and request.headers.get("Content-Type") == "application/json":
        return {"success": True, "message": "Logged out successfully"}
        
    flash(f"You've been signed out. See you soon, {user_name}!", "info")
    
    response = redirect(url_for("main.home"))
    # Explicitly clear cookies to prevent browser caching from keeping the user logged in
    response.set_cookie('session', '', expires=0)
    response.set_cookie('remember_token', '', expires=0)
    
    return response
