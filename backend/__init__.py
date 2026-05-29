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
        # Point Flask at the frontend folder so Jinja2 finds templates
        # and url_for('static', ...) resolves CSS / images / JS.
        template_folder=os.path.join(os.path.dirname(__file__), "..", "frontend", "templates"),
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
    cors.init_app(app, resources={r"/api/*": {"origins": app.config.get("CORS_ORIGINS", "*")}})
    limiter.init_app(app)

    # ── User loader for Flask-Login ───────────────────────────────────────────
    from backend.models import User

    @login_manager.user_loader
    def load_user(user_id: str):
        return User.query.get(int(user_id))

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

    # ── Static JS shortcut (/js/<file> → frontend/js/<file>) ─────────────────
    from flask import send_from_directory

    js_folder = os.path.join(os.path.dirname(__file__), "..", "frontend", "js")

    @app.route("/js/<path:filename>")
    @limiter.exempt
    def serve_js(filename):
        return send_from_directory(js_folder, filename)

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

    # ── Jinja Template Globals and Filters ────────────────────────────────────
    from markupsafe import escape, Markup
    
    def nl2br_filter(value):
        if not value: return ""
        return Markup(str(escape(value)).replace('\n', '<br>\n'))
        
    def render_inline(value):
        return escape(value) if value else ""
        
    def render_html(value):
        return Markup(value) if value else ""
        
    app.jinja_env.globals.update(
        e=escape,
        render_inline=render_inline,
        render_html=render_html,
    )
    app.jinja_env.filters['nl2br'] = nl2br_filter

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
    from flask import jsonify, render_template

    @app.errorhandler(400)
    def bad_request(e):
        if _is_api_request():
            return jsonify({"success": False, "error": str(e)}), 400
        return render_template("404.html"), 400

    @app.errorhandler(401)
    def unauthorized(e):
        if _is_api_request():
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        from flask import redirect, url_for
        return redirect(url_for("auth.login"))

    @app.errorhandler(403)
    def forbidden(e):
        if _is_api_request():
            return jsonify({"success": False, "error": "Forbidden"}), 403
        return render_template("404.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        if _is_api_request():
            return jsonify({"success": False, "error": "Not found"}), 404
        return render_template("404.html"), 404

    @app.errorhandler(429)
    def too_many_requests(e):
        if _is_api_request():
            return jsonify({"success": False, "error": "Rate limit exceeded. Please wait."}), 429
        return render_template("404.html"), 429

    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()  # prevent broken transactions
        app.logger.exception("500 Internal Server Error")
        if _is_api_request():
            return jsonify({"success": False, "error": "Internal server error"}), 500
        return render_template("404.html"), 500

    def _is_api_request() -> bool:
        from flask import request
        return request.path.startswith("/api/") or request.is_json


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
