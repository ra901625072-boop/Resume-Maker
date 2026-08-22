"""
routes/ai.py — AI Generation Blueprint (v2)
=============================================
Protected AI endpoints requiring Bearer token authentication:

  POST /api/generate-summary     → professional summary paragraph
  POST /api/generate-experience  → CAR-framework bullet points
  POST /api/suggest-skills       → skill recommendations
  POST /api/improve-grammar      → polish any text
  POST /api/ats-score            → 0-100 ATS score + tips
  POST /api/cover-letter         → full cover letter
  POST /api/extract-json         → extract structured resume JSON from
                                   image / PDF / DOCX upload (multimodal)
"""

import os
import uuid

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.utils import secure_filename

from backend.extensions import limiter
from backend.services.ai_service import AIService
from backend.services.auth_token_service import token_required

ai_bp = Blueprint("ai", __name__, url_prefix="/api")


# ────────────────────────────────────────────────────────────────────────────
# Generate Professional Summary
# ────────────────────────────────────────────────────────────────────────────
@ai_bp.route("/generate-summary", methods=["POST"])
@token_required
@limiter.limit("20 per hour")
def generate_summary():
    """Body: { name, title, skills }"""
    body   = request.get_json(silent=True) or {}
    name   = body.get("name", "").strip()
    title  = body.get("title", "").strip()
    skills = body.get("skills", "")
    exp_titles = body.get("experience_titles", [])

    if not title:
        return jsonify({"success": False, "error": "Job title is required."}), 422

    result = AIService.generate_summary(name=name, title=title,
                                        skills=skills, experience_titles=exp_titles)
    return jsonify(result), (200 if result["success"] else 502)


# ────────────────────────────────────────────────────────────────────────────
# Generate Experience Description
# ────────────────────────────────────────────────────────────────────────────
@ai_bp.route("/generate-experience", methods=["POST"])
@token_required
@limiter.limit("20 per hour")
def generate_experience():
    """Body: { title, company, duration, skills }"""
    body     = request.get_json(silent=True) or {}
    title    = body.get("title", "").strip()
    company  = body.get("company", "")
    duration = body.get("duration", "")
    skills   = body.get("skills", "")

    if not title:
        return jsonify({"success": False, "error": "Job title is required."}), 422

    result = AIService.generate_experience(
        title=title, company=company, duration=duration, skills=skills
    )
    return jsonify(result), (200 if result["success"] else 502)


# ────────────────────────────────────────────────────────────────────────────
# Suggest Skills
# ────────────────────────────────────────────────────────────────────────────
@ai_bp.route("/suggest-skills", methods=["POST"])
@token_required
@limiter.limit("15 per hour")
def suggest_skills():
    """Body: { job_title, existing_skills }"""
    body            = request.get_json(silent=True) or {}
    job_title       = body.get("job_title", "").strip()
    existing_skills = body.get("existing_skills", "")

    if not job_title:
        return jsonify({"success": False, "error": "Job title is required."}), 422

    result = AIService.suggest_skills(job_title=job_title, existing_skills=existing_skills)
    return jsonify(result), (200 if result["success"] else 502)


# ────────────────────────────────────────────────────────────────────────────
# Improve Grammar / Tone
# ────────────────────────────────────────────────────────────────────────────
@ai_bp.route("/improve-grammar", methods=["POST"])
@token_required
@limiter.limit("15 per hour")
def improve_grammar():
    """Body: { text }"""
    body = request.get_json(silent=True) or {}
    text = body.get("text", "").strip()

    if not text:
        return jsonify({"success": False, "error": "Text is required."}), 422

    result = AIService.improve_grammar(text=text)
    return jsonify(result), (200 if result["success"] else 502)


# ────────────────────────────────────────────────────────────────────────────
# ATS Resume Score
# ────────────────────────────────────────────────────────────────────────────
@ai_bp.route("/ats-score", methods=["POST"])
@token_required
@limiter.limit("10 per hour")
def ats_score():
    """Body: { resume_id }  OR  full resume dict"""
    from backend.models import Resume

    body      = request.get_json(silent=True) or {}
    resume_id = body.get("resume_id")

    if resume_id:
        resume = Resume.query.filter_by(
            id=resume_id, user_id=g.current_user.id, is_deleted=False
        ).first()
        if not resume:
            return jsonify({"success": False, "error": "Resume not found."}), 404
        resume_dict = resume.to_dict()
    else:
        resume_dict = body

    result = AIService.ats_score(resume_dict=resume_dict)
    return jsonify(result), (200 if result["success"] else 502)


# ────────────────────────────────────────────────────────────────────────────
# Cover Letter Generator
# ────────────────────────────────────────────────────────────────────────────
@ai_bp.route("/cover-letter", methods=["POST"])
@token_required
@limiter.limit("10 per hour")
def cover_letter():
    """Body: { name, title, company, job_description, skills }"""
    body            = request.get_json(silent=True) or {}
    name            = body.get("name", "").strip()
    title           = body.get("title", "").strip()
    company         = body.get("company", "").strip()
    job_description = body.get("job_description", "")
    skills          = body.get("skills", "")

    missing = [f for f, v in [("name", name), ("title", title), ("company", company)] if not v]
    if missing:
        return jsonify({
            "success": False,
            "error":   f"Required fields missing: {', '.join(missing)}"
        }), 422

    result = AIService.generate_cover_letter(
        name=name, title=title, company=company,
        job_description=job_description, skills=skills,
    )
    return jsonify(result), (200 if result["success"] else 502)


# ────────────────────────────────────────────────────────────────────────────
# AI File Extraction
# POST /api/extract-json
# Accepts: multipart/form-data  file=<binary>
# Returns: { success, data: { name, title, email, ... } }
# ────────────────────────────────────────────────────────────────────────────
@ai_bp.route("/extract-json", methods=["POST"])
@token_required
@limiter.limit("10 per hour")
def extract_json():
    """
    Upload an image, PDF, or DOCX and extract full structured resume data.
    The AI uses multimodal vision for images/scanned PDFs and text extraction
    for digital PDFs and DOCX files, then returns a validated JSON schema.
    """
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"success": False, "error": "No file received."}), 400

    filename = secure_filename(uploaded.filename)
    if "." not in filename:
        return jsonify({"success": False, "error": "File has no extension."}), 400

    ext     = filename.rsplit(".", 1)[-1].lower()
    allowed = current_app.config.get(
        "ALLOWED_ANALYZE_EXTENSIONS", {"jpg", "jpeg", "png", "webp", "pdf", "docx", "doc"}
    )
    if ext not in allowed:
        return jsonify({
            "success": False,
            "error":   f"Unsupported file type .{ext}. Allowed: {', '.join(sorted(allowed))}"
        }), 415

    # Validate size
    uploaded.seek(0, 2)
    size = uploaded.tell()
    uploaded.seek(0)
    max_size = current_app.config.get("MAX_CONTENT_LENGTH", 10 * 1024 * 1024)
    if size > max_size:
        return jsonify({
            "success": False,
            "error":   f"File too large. Maximum is {max_size // (1024*1024)} MB."
        }), 413

    # Save temporarily
    save_dir  = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(save_dir, exist_ok=True)
    tmp_name  = f"analyze_{uuid.uuid4().hex}.{ext}"
    tmp_path  = os.path.join(save_dir, tmp_name)

    try:
        uploaded.save(tmp_path)
        result = AIService.analyze_file(file_path=tmp_path, ext=ext)
    except Exception as e:
        current_app.logger.exception("extract-json endpoint error")
        result = {"success": False, "error": f"File processing error: {str(e)}"}
    finally:
        # Always clean up the temp file
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

    return jsonify(result), (200 if result["success"] else 502)
