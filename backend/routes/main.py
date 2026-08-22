"""
routes/main.py — Main Page Blueprint (API Redirects)
===================================================
Since the frontend is now decoupled for static Vercel hosting,
direct visits to backend page views will return JSON API notices
or redirect to the configured frontend.
"""

from flask import Blueprint, jsonify, redirect, request, current_app

main_bp = Blueprint("main", __name__)


def _get_frontend_redirect(fallback="/"):
    """Get the frontend origin for redirects if configured."""
    origins = current_app.config.get("CORS_ORIGINS", "*")
    if origins and origins != "*":
        if isinstance(origins, list) and len(origins) > 0:
            return origins[0]
        return origins
    return fallback


@main_bp.route("/")
def home():
    """Return API server health and status notice."""
    return jsonify({
        "status": "online",
        "service": "WISAXIS Resume Maker API Server",
        "message": "Please access the application via the decoupled frontend."
    })


@main_bp.route("/dashboard")
def dashboard():
    """Redirect backend browser visits to the frontend dashboard."""
    return redirect(_get_frontend_redirect() + "/dashboard")


@main_bp.route("/edit/<int:resume_id>")
def edit_resume(resume_id: int):
    """Redirect edit browser visits to the frontend edit wizard."""
    return redirect(f"{_get_frontend_redirect()}/dashboard?id={resume_id}")


@main_bp.route("/profile")
def profile():
    """Redirect profile browser visits to the frontend profile."""
    return redirect(_get_frontend_redirect() + "/profile")


@main_bp.route("/chat")
def chat():
    """Redirect chat visits to the frontend chat assistant."""
    return redirect(_get_frontend_redirect() + "/chat")


@main_bp.route("/json")
def json_features():
    """Redirect json visits to the frontend json features page."""
    return redirect(_get_frontend_redirect() + "/json")


@main_bp.route("/upload")
def upload_resume():
    """Redirect upload visits to the frontend json features page."""
    return redirect(_get_frontend_redirect() + "/json")
