"""
routes/api.py — General API Blueprint
=======================================
Miscellaneous JSON API endpoints used by the frontend:

  POST /api/chat           → AI chat assistant (from chat.html)
  POST /upload-photo       → Profile photo upload (from wizard)
  GET  /api/resumes        → List current user's resumes (JSON)
  GET  /api/resumes/<id>   → Single resume JSON
  GET  /api/templates      → Available templates list
  GET  /api/health         → Health check (no auth required)
  GET  /api/me             → Current user info (JSON)
"""

import os
import uuid

from flask import (Blueprint, current_app, jsonify, request, url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from backend.extensions import limiter
from backend.models import Resume, Template
from backend.services.ai_service import AIService

api_bp = Blueprint("api", __name__)


# ────────────────────────────────────────────────────────────────────────────
# Health Check  (used by Render / Docker / uptime monitors)
# ────────────────────────────────────────────────────────────────────────────
@api_bp.route("/api/health")
def health_check():
    """Returns 200 OK — no authentication required."""
    from backend.extensions import db
    try:
        db.session.execute(db.text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    return jsonify({
        "status":   "ok",
        "db":       db_status,
        "app":      current_app.config.get("APP_NAME", "WISAXIS"),
        "version":  current_app.config.get("APP_VERSION", "2.0.0"),
    })


# ────────────────────────────────────────────────────────────────────────────
# AI Chat  (called by chat.html via fetch('/api/chat'))
# ────────────────────────────────────────────────────────────────────────────
@api_bp.route("/api/chat", methods=["POST"])
@login_required
@limiter.limit("60 per hour")
def chat():
    """
    Multi-turn AI chat for the resume assistant page.

    Body: { message: str, history: [{ role, content }] }
    Returns: { success, data }   data = assistant response
    """
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    history = body.get("history", [])

    if not message:
        return jsonify({"success": False, "error": "Message cannot be empty."}), 422

    result = AIService.chat(message=message, history=history)
    return jsonify(result), (200 if result["success"] else 502)


# ────────────────────────────────────────────────────────────────────────────
# Photo Upload  (called by wizard-vue.js → fetch('/upload-photo'))
# ────────────────────────────────────────────────────────────────────────────
@api_bp.route("/upload-photo", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def upload_photo():
    """
    Accept a profile photo, validate it, save it, and return its URL.

    Returns: { success, url }
    """
    photo = request.files.get("photo")
    if not photo or not photo.filename:
        return jsonify({"success": False, "error": "No file received."}), 400

    # Validate extension
    filename   = secure_filename(photo.filename)
    ext        = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed    = current_app.config.get("ALLOWED_PHOTO_EXTENSIONS", {"jpg", "jpeg", "png"})

    if ext not in allowed:
        return jsonify({
            "success": False,
            "error":   f"File type not allowed. Use: {', '.join(sorted(allowed))}"
        }), 415

    # Validate file size (already capped by MAX_CONTENT_LENGTH in Flask,
    # but double-check for explicit error message)
    photo.seek(0, 2)  # seek to end
    size = photo.tell()
    photo.seek(0)     # reset
    max_size = current_app.config.get("MAX_CONTENT_LENGTH", 5 * 1024 * 1024)
    if size > max_size:
        return jsonify({
            "success": False,
            "error":   f"File too large. Maximum size is {max_size // (1024*1024)} MB."
        }), 413

    # Save with a UUID filename to avoid collisions and path traversal
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    save_dir    = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(save_dir, exist_ok=True)
    save_path   = os.path.join(save_dir, unique_name)
    photo.save(save_path)

    # Build a URL the browser can fetch  (/static/uploads/abc.jpg)
    # We serve uploads via a dedicated route below
    photo_url = url_for("api.serve_upload", filename=unique_name, _external=False)

    return jsonify({"success": True, "url": photo_url})


@api_bp.route("/uploads/<path:filename>")
def serve_upload(filename: str):
    """Serve user-uploaded files (photos)."""
    from flask import send_from_directory
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    return send_from_directory(upload_dir, filename)


# ────────────────────────────────────────────────────────────────────────────
# Resumes — JSON REST API
# ────────────────────────────────────────────────────────────────────────────
@api_bp.route("/api/resumes")
@login_required
def list_resumes():
    """Return a paginated list of the current user's resumes."""
    page     = request.args.get("page", 1, type=int)
    per_page = current_app.config.get("RESUMES_PER_PAGE", 12)

    pagination = (
        Resume.query
        .filter_by(user_id=current_user.id, is_deleted=False)
        .order_by(Resume.updated_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    return jsonify({
        "success": True,
        "data": [r.to_dict() for r in pagination.items],
        "meta": {
            "page":       pagination.page,
            "per_page":   per_page,
            "total":      pagination.total,
            "pages":      pagination.pages,
            "has_next":   pagination.has_next,
            "has_prev":   pagination.has_prev,
        },
    })


@api_bp.route("/api/resumes/<int:resume_id>")
@login_required
def get_resume(resume_id: int):
    """Return a single resume as JSON."""
    resume = Resume.query.filter_by(
        id=resume_id, user_id=current_user.id, is_deleted=False
    ).first_or_404()
    return jsonify({"success": True, "data": resume.to_dict()})


# ────────────────────────────────────────────────────────────────────────────
# Templates catalogue
# ────────────────────────────────────────────────────────────────────────────
@api_bp.route("/api/templates")
def list_templates():
    """Return the available templates (no auth required for public landing page)."""
    templates = Template.query.filter_by(is_active=True).order_by(Template.sort_order).all()
    return jsonify({"success": True, "data": [t.to_dict() for t in templates]})


# ────────────────────────────────────────────────────────────────────────────
# Current User Info
# ────────────────────────────────────────────────────────────────────────────
@api_bp.route("/api/me")
@login_required
def me():
    """Return current user profile data as JSON."""
    return jsonify({"success": True, "data": current_user.to_dict()})
