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
import sys
from logging.handlers import RotatingFileHandler

from flask import Flask

from backend.config import get_config
from backend.extensions import cors, csrf, db, limiter


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

    # ── Early Logging setup ───────────────────────────────────────────────────
    _configure_logging(app)

    # ── Ensure instance folder exists (SQLite db + uploads live here) ────────
    os.makedirs(app.config.get("UPLOAD_FOLDER", "instance/uploads"), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "instance"), exist_ok=True)

    # ── Initialise extensions ─────────────────────────────────────────────────
    db.init_app(app)
    csrf.init_app(app)
    
    # Enable credentials support on CORS
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

    # ── Register Blueprints ───────────────────────────────────────────────────
    from backend.routes.main import main_bp
    from backend.routes.resume import resume_bp
    from backend.routes.ai import ai_bp
    from backend.routes.api import api_bp
    from backend.routes.auth import auth_bp

    app.register_blueprint(main_bp)            # /  /dashboard  /profile  /chat  /json-features
    app.register_blueprint(resume_bp)          # /generate  /resume/<id>  /resume/<id>/edit  …
    app.register_blueprint(ai_bp)              # /api/generate-summary  /api/generate-experience  …
    app.register_blueprint(api_bp)             # /api/chat  /upload-photo  /api/resumes  …
    app.register_blueprint(auth_bp)            # /api/auth/signup  /api/auth/login  …

    # Exempt CORS API blueprints from CSRF checks
    csrf.exempt(resume_bp)
    csrf.exempt(ai_bp)
    csrf.exempt(api_bp)
    csrf.exempt(auth_bp)

    # ── Global error handlers ─────────────────────────────────────────────────
    _register_error_handlers(app)

    # ── Database setup ────────────────────────────────────────────────────────
    with app.app_context():
        try:
            db.create_all()
            # Seed static template catalogue on first run
            from backend.models import seed_templates
            seed_templates()
            app.logger.info("Database tables initialized successfully.")
        except Exception as db_err:
            app.logger.warning(f"Database initialization deferred/warning: {db_err}")

    @app.after_request
    def add_cache_control(response):
        from flask import request
        # Do not aggressively cache dynamic routes to prevent back-button showing authenticated content after logout
        if request.endpoint != "static" and not request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "-1"
        return response

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

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] in %(module)s: %(message)s"
    )

    app.logger.setLevel(level)

    # 1. Console / Stdout handler (critical for Render Live Tail & containers)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    app.logger.addHandler(stream_handler)

    # 2. File handler (optional disk persistence)
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = RotatingFileHandler(log_file, maxBytes=10_000_000, backupCount=5)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        if not app.debug and not app.testing:
            app.logger.addHandler(file_handler)
        else:
            file_handler.close()
    except Exception:
        pass  # ignore file logging errors on read-only/restricted environments
