"""
backend/__init__.py — Application Factory
==========================================
The create_app() function is the single entry point that constructs
and returns a fully configured Flask application.

Usage:
    # Development
    from backend import create_app
    app = create_app()
    app.run()

    # Production (Gunicorn)
    gunicorn "backend:create_app()"
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask

from backend.config import get_config
from backend.extensions import cors, csrf, db, limiter, login_manager


def create_app(config_override=None) -> Flask:
    """
    Application factory.

    Args:
        config_override: An optional Config class (used in tests to
                         inject TestingConfig without env variables).

    Returns:
        A fully initialised Flask application.
    """
    app = Flask(
        __name__,
        # Serve uploaded photos and static assets from the frontend folder
        static_folder=os.path.join(os.path.dirname(__file__), "..", "frontend", "static"),
        static_url_path="/static",
    )

    # ── Load configuration ────────────────────────────────────────────────────
    cfg = config_override or get_config()
    app.config.from_object(cfg)

    # ── Ensure instance folder exists (SQLite db + uploads live here) ────────
    os.makedirs(app.config.get("UPLOAD_FOLDER", "instance/uploads"), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "instance"), exist_ok=True)

    # ── Initialise extensions ─────────────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    
    # Enable credentials support on CORS for cross-origin authentication
    cors.init_app(
        app,
        resources={
            r"/*": {
                "origins": app.config.get("CORS_ORIGINS", "*"),
                "supports_credentials": True,
                "allow_headers": ["Content-Type", "Authorization", "X-Requested-With", "X-CSRFToken"],
                "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
            }
        }
    )
    limiter.init_app(app)

    # ── Custom unauthorized handler for Flask-Login (CORS APIs) ───────────────
    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import request, jsonify, redirect, url_for
        if (
            request.path.startswith("/api/") or
            request.is_json or
            request.headers.get("Accept") == "application/json" or
            request.path.startswith("/generate") or
            "/delete" in request.path or
            "/duplicate" in request.path or
            "/switch-template" in request.path
        ):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return redirect(url_for("auth.login"))

    # ── User loaders for Flask-Login (Dual Auth: Session + Bearer Token) ─────
    from backend.models import User
    from backend.services.auth_token_service import verify_auth_token

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return User.query.get(int(user_id))
        except (ValueError, TypeError):
            return None

    @login_manager.request_loader
    def load_user_from_request(req):
        # 1. Check Authorization header: 'Bearer <token>'
        auth_header = req.headers.get("Authorization")
        if auth_header:
            parts = auth_header.split(" ", 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                token = parts[1].strip()
                user_id = verify_auth_token(token)
                if user_id:
                    user = User.query.get(user_id)
                    if user and user.is_active:
                        return user

        # 2. Check query parameter: ?auth_token=<token>
        token_param = req.args.get("auth_token")
        if token_param:
            user_id = verify_auth_token(token_param)
            if user_id:
                user = User.query.get(user_id)
                if user and user.is_active:
                    return user

        return None

    # ── Register Blueprints ───────────────────────────────────────────────────
    from backend.routes.auth import auth_bp
    from backend.routes.main import main_bp
    from backend.routes.resume import resume_bp
    from backend.routes.ai import ai_bp
    from backend.routes.api import api_bp

    app.register_blueprint(auth_bp)            # /login  /signup  /logout
    app.register_blueprint(main_bp)            # /  /dashboard  /profile  /chat  /json-features
    app.register_blueprint(resume_bp)          # /generate  /resume/<id>  /resume/<id>/edit  …
    app.register_blueprint(ai_bp)              # /api/generate-summary  /api/generate-experience  …
    app.register_blueprint(api_bp)             # /api/chat  /upload-photo  /api/resumes  …

    # Exempt CORS API/auth blueprints from CSRF checks
    csrf.exempt(auth_bp)
    csrf.exempt(resume_bp)
    csrf.exempt(ai_bp)
    csrf.exempt(api_bp)



    # ── Global error handlers ─────────────────────────────────────────────────
    _register_error_handlers(app)

    # ── Database setup ────────────────────────────────────────────────────────
    with app.app_context():
        db.create_all()
        # Seed static template catalogue on first run
        from backend.models import seed_templates
        try:
            seed_templates()
        except Exception:
            pass  # idempotent — safe to call multiple times



    @app.after_request
    def add_cache_control(response):
        from flask import request
        # Do not aggressively cache dynamic routes to prevent back-button showing authenticated content after logout
        if request.endpoint != "static" and not request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "-1"
        return response

    # ── Logging ───────────────────────────────────────────────────────────────
    _configure_logging(app)

    return app


# ────────────────────────────────────────────────────────────────────────────
# Error handlers
# ────────────────────────────────────────────────────────────────────────────
def _register_error_handlers(app: Flask):
    from flask import jsonify

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"success": False, "error": str(e.description) if hasattr(e, 'description') else str(e)}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"success": False, "error": "Forbidden"}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"success": False, "error": "Not Found"}), 404

    @app.errorhandler(429)
    def too_many_requests(e):
        return jsonify({"success": False, "error": "Rate limit exceeded. Please wait."}), 429

    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()  # prevent broken transactions
        app.logger.exception("500 Internal Server Error")
        return jsonify({"success": False, "error": "Internal server error"}), 500


# ────────────────────────────────────────────────────────────────────────────
# Logging configuration
# ────────────────────────────────────────────────────────────────────────────
def _configure_logging(app: Flask):
    level = getattr(logging, app.config.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    log_file = app.config.get("LOG_FILE", "instance/app.log")

    # Ensure log directory exists
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    )

    # Rotating file handler (10 MB, keep 5 backups)
    file_handler = RotatingFileHandler(log_file, maxBytes=10_000_000, backupCount=5)
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    app.logger.setLevel(level)
    if not app.debug:
        app.logger.addHandler(file_handler)
