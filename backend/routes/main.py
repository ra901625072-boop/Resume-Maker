"""
routes/main.py — Main Page Blueprint (API Redirects)
===================================================
Since the frontend is now decoupled for static Vercel hosting,
direct visits to backend page views will return JSON API notices
or redirect to the configured frontend.
"""

import os
from flask import Blueprint, jsonify, redirect, request, current_app, send_from_directory, url_for
from flask_login import current_user, login_required

main_bp = Blueprint("main", __name__)


def _serve_frontend_file(filename):
    """Helper to serve static HTML files from the frontend directory."""
    frontend_dir = os.path.abspath(os.path.join(current_app.root_path, "..", "frontend"))
    return send_from_directory(frontend_dir, filename)


@main_bp.route("/")
def home():
    """Serve the landing page HTML."""
    return _serve_frontend_file("index.html")


@main_bp.route("/dashboard")
@login_required
def dashboard():
    """Serve the dashboard HTML page directly."""
    return _serve_frontend_file("dashboard.html")


@main_bp.route("/edit/<int:resume_id>")
@login_required
def edit_resume(resume_id: int):
    """Redirect edit browser visits to dashboard with ID query param."""
    return redirect(url_for("main.dashboard", id=resume_id))


@main_bp.route("/profile")
@login_required
def profile():
    """Serve the profile HTML page directly."""
    return _serve_frontend_file("profile.html")


@main_bp.route("/chat")
@login_required
def chat():
    """Serve the chat assistant HTML page directly."""
    return _serve_frontend_file("chat.html")


@main_bp.route("/json")
@login_required
def json_features():
    """Serve the json features HTML page directly."""
    return _serve_frontend_file("json.html")


@main_bp.route("/upload")
@login_required
def upload_resume():
    """Redirect upload visits to the json features page."""
    return redirect(url_for("main.json_features"))
