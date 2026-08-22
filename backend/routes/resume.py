"""
routes/resume.py — Resume CRUD Blueprint
==========================================
All resume-document operations with Bearer token authentication
and horizontal ownership checks (IDOR protection):

  POST /generate                          → create or update resume (from wizard)
  GET  /resume/<id>                       → view resume data JSON
  GET  /resume/<id>/download-doc          → download as text
  GET  /resume/<id>/download              → download as JSON
  POST /resume/<id>/delete                → soft delete
  POST /resume/<id>/duplicate             → clone with a different template
  POST /resume/process-json               → parse uploaded file → JSON schema
  GET  /resume/<id>/versions              → version history list
"""

import json
import os
import uuid

from flask import (Blueprint, abort, current_app, flash, g, jsonify,
                   redirect, request, url_for)
from werkzeug.utils import secure_filename

from backend.extensions import db, limiter
from backend.models import (Education, Experience, ExportHistory, Resume,
                             ResumeVersion)
from backend.services.auth_token_service import token_required

resume_bp = Blueprint("resume", __name__)

# Valid template slugs (must match frontend values)
VALID_TEMPLATES = {f"template{i}" for i in range(1, 9)}


# ────────────────────────────────────────────────────────────────────────────
# Create / Update Resume  (called by wizard-vue.js → POST /generate)
# ────────────────────────────────────────────────────────────────────────────
@resume_bp.route("/generate", methods=["POST"])
@token_required
@limiter.limit("30 per hour")
def generate():
    """
    Accept the Vue wizard payload and persist it to the database.
    Owned by the authenticated user in g.current_user.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "No JSON payload received."}), 400

    # ── Validate required fields ──────────────────────────────────────────────
    errors = _validate_resume_payload(data)
    if errors:
        return jsonify({"success": False, "error": "; ".join(errors)}), 422

    resume_id = data.get("resume_id")
    is_update = bool(resume_id)

    try:
        if is_update:
            resume = Resume.query.filter_by(
                id=resume_id, user_id=g.current_user.id, is_deleted=False
            ).first()
            if not resume:
                return jsonify({"success": False, "error": "Resume not found."}), 404

            # Snapshot current state for version history before overwriting
            _snapshot_resume(resume)

            # Bump version counter
            resume.version += 1
            # Remove old experience / education rows (will be re-inserted)
            Experience.query.filter_by(resume_id=resume.id).delete()
            Education.query.filter_by(resume_id=resume.id).delete()
        else:
            resume = Resume(user_id=g.current_user.id)
            db.session.add(resume)

        # ── Populate fields ───────────────────────────────────────────────────
        resume.template = data.get("template", "template1")[:50]
        resume.name     = data.get("name", "")[:120].strip()
        resume.title    = data.get("title", "")[:120].strip()
        resume.email    = data.get("email", "")[:254].strip()
        resume.phone    = data.get("phone", "")[:30].strip()
        resume.address  = data.get("address", "")[:255].strip()
        resume.summary  = data.get("summary", "").strip()
        resume.photo_url = data.get("photo", "")[:512]

        # Skills: wizard sends either a list or a comma-separated string
        raw_skills = data.get("skills", "")
        if isinstance(raw_skills, list):
            resume.skills = ", ".join(s.strip() for s in raw_skills if s.strip())
        else:
            resume.skills = str(raw_skills).strip()

        # Languages: wizard sends a list of strings
        raw_langs = data.get("languages", [])
        resume.languages = json.dumps(raw_langs if isinstance(raw_langs, list) else [])

        db.session.flush()  # get resume.id before inserting children

        # ── Experience entries ────────────────────────────────────────────────
        for pos, exp_data in enumerate(data.get("experience", [])):
            title = (exp_data.get("title") or "").strip()
            if not title:
                continue  # skip empty rows
            exp = Experience(
                resume_id   = resume.id,
                position    = pos,
                title       = title[:150],
                company     = (exp_data.get("company") or "")[:150].strip(),
                duration    = (exp_data.get("duration") or "")[:100].strip(),
                description = (exp_data.get("description") or "").strip(),
            )
            db.session.add(exp)

        # ── Education entries ─────────────────────────────────────────────────
        for pos, edu_data in enumerate(data.get("education", [])):
            degree = (edu_data.get("degree") or "").strip()
            if not degree:
                continue  # skip empty rows
            edu = Education(
                resume_id  = resume.id,
                position   = pos,
                degree     = degree[:200],
                university = (edu_data.get("university") or "")[:200].strip(),
                year       = (edu_data.get("year") or "")[:50].strip(),
            )
            db.session.add(edu)

        db.session.commit()
        return jsonify({
            "success":   True,
            "message":   "Resume saved successfully! ✅",
            "redirect":  url_for("resume.view_resume", resume_id=resume.id),
            "resume_id": resume.id,
        })

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error saving resume")
        return jsonify({"success": False, "error": "Failed to save resume. Please try again."}), 500


# ────────────────────────────────────────────────────────────────────────────
# View Resume (rendered template data)
# ────────────────────────────────────────────────────────────────────────────
@resume_bp.route("/resume/<int:resume_id>")
@token_required
def view_resume(resume_id: int):
    """
    Return resume data as JSON.
    The frontend renders resumes client-side via resume.html.
    """
    resume = Resume.query.filter_by(
        id=resume_id, user_id=g.current_user.id, is_deleted=False
    ).first_or_404()

    data = resume.to_dict()
    photo_url = resume.photo_url or ""
    photo_exists = bool(photo_url and photo_url.strip())

    name_parts = (resume.name or "").split()
    if len(name_parts) >= 2:
        initials = (name_parts[0][0] + name_parts[-1][0]).upper()
    elif name_parts:
        initials = name_parts[0][0].upper()
    else:
        initials = "?"

    data["photo_exists"] = photo_exists
    data["initials"] = initials
    data["template_id"] = resume.template.replace("template", "")

    return jsonify({"success": True, "resume": data})


@resume_bp.route("/resume/<int:resume_id>/switch-template", methods=["POST"])
@token_required
def switch_template(resume_id: int):
    """Quick template switch without duplicating — updates in place."""
    resume = Resume.query.filter_by(
        id=resume_id, user_id=g.current_user.id, is_deleted=False
    ).first_or_404()

    # Extract template from JSON payload or form data
    if request.is_json:
        body = request.get_json(silent=True) or {}
        new_template = body.get("template", resume.template)
    else:
        new_template = request.form.get("template", resume.template)

    if new_template in VALID_TEMPLATES:
        _snapshot_resume(resume)
        resume.template  = new_template
        resume.version  += 1
        db.session.commit()

    if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
        return jsonify({"success": True, "message": "Template updated successfully."})

    return redirect(url_for("resume.view_resume", resume_id=resume.id))


# ────────────────────────────────────────────────────────────────────────────
# Download DOC (plain-text)
# ────────────────────────────────────────────────────────────────────────────
@resume_bp.route("/resume/<int:resume_id>/download-doc")
@token_required
def download_doc(resume_id: int):
    """Download resume as plain text (DOCX generation is a future enhancement)."""
    from flask import Response
    resume = Resume.query.filter_by(
        id=resume_id, user_id=g.current_user.id, is_deleted=False
    ).first_or_404()

    # Log the export
    export = ExportHistory(
        resume_id=resume.id,
        user_id=g.current_user.id,
        format="doc",
    )
    db.session.add(export)
    db.session.commit()

    lines = [
        resume.name, resume.title, resume.email, resume.phone or "",
        resume.address or "", "",
        "SUMMARY", resume.summary or "", "",
        "SKILLS", resume.skills or "", "",
    ]
    for exp in resume.experience:
        lines += [f"{exp.title} — {exp.company} ({exp.duration})", exp.description or "", ""]
    for edu in resume.education:
        lines += [f"{edu.degree} — {edu.university} ({edu.year})", ""]

    text = "\n".join(lines)
    filename = f"resume_{resume.name.replace(' ', '_')}.txt"
    response = Response(text, mimetype="text/plain")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ────────────────────────────────────────────────────────────────────────────
# Download JSON
# ────────────────────────────────────────────────────────────────────────────
@resume_bp.route("/resume/<int:resume_id>/download")
@token_required
def download_resume(resume_id: int):
    """
    Return the resume as a downloadable JSON file.
    Also records an ExportHistory entry.
    """
    resume = Resume.query.filter_by(
        id=resume_id, user_id=g.current_user.id, is_deleted=False
    ).first_or_404()

    # Log the export
    export = ExportHistory(
        resume_id=resume.id,
        user_id=g.current_user.id,
        format="json",
    )
    db.session.add(export)
    db.session.commit()

    filename = f"resume_{resume.name.replace(' ', '_')}.json"
    response = current_app.response_class(
        response=json.dumps(resume.to_dict(), indent=2),
        status=200,
        mimetype="application/json",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ────────────────────────────────────────────────────────────────────────────
# Delete Resume
# ────────────────────────────────────────────────────────────────────────────
@resume_bp.route("/resume/<int:resume_id>/delete", methods=["POST"])
@token_required
def delete_resume(resume_id: int):
    """Soft-delete the resume so it disappears from the profile page."""
    resume = Resume.query.filter_by(
        id=resume_id, user_id=g.current_user.id, is_deleted=False
    ).first_or_404()

    resume.is_deleted = True
    db.session.commit()

    if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
        return jsonify({"success": True, "message": "Resume deleted."})

    flash("Resume deleted.", "info")
    return redirect(url_for("main.profile"))


# ────────────────────────────────────────────────────────────────────────────
# Duplicate / Clone Resume with a Different Template
# ────────────────────────────────────────────────────────────────────────────
@resume_bp.route("/resume/<int:resume_id>/duplicate", methods=["POST"])
@token_required
def duplicate_resume(resume_id: int):
    """
    Clone a resume with a new template (the "Switch Template / Clone" UI).
    Creates a brand-new Resume row with the same data but a different template.
    """
    source = Resume.query.filter_by(
        id=resume_id, user_id=g.current_user.id, is_deleted=False
    ).first_or_404()

    if request.is_json:
        body = request.get_json(silent=True) or {}
        new_template = body.get("duplicate_template", "template1")
    else:
        new_template = request.form.get("duplicate_template", "template1")

    if new_template not in VALID_TEMPLATES:
        if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
            return jsonify({"success": False, "error": "Invalid template selected."}), 422
        flash("Invalid template selected.", "error")
        return redirect(url_for("main.profile"))

    try:
        clone = Resume(
            user_id   = g.current_user.id,
            template  = new_template,
            name      = source.name,
            title     = source.title,
            email     = source.email,
            phone     = source.phone,
            address   = source.address,
            photo_url = source.photo_url,
            summary   = source.summary,
            skills    = source.skills,
            languages = source.languages,
        )
        db.session.add(clone)
        db.session.flush()

        # Clone all experience entries
        for exp in source.experience:
            db.session.add(Experience(
                resume_id   = clone.id,
                position    = exp.position,
                title       = exp.title,
                company     = exp.company,
                duration    = exp.duration,
                description = exp.description,
            ))

        # Clone all education entries
        for edu in source.education:
            db.session.add(Education(
                resume_id  = clone.id,
                position   = edu.position,
                degree     = edu.degree,
                university = edu.university,
                year       = edu.year,
            ))

        db.session.commit()

        if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
            return jsonify({
                "success":   True,
                "message":   f"Resume cloned with {new_template.title()} template! ✅",
                "redirect":  f"/resume?id={clone.id}",
                "resume_id": clone.id,
            })

        flash(f"Resume cloned with {new_template.title()} template! ✅", "success")
        return redirect(url_for("resume.view_resume", resume_id=clone.id))

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error duplicating resume")
        if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
            return jsonify({"success": False, "error": "Could not duplicate resume. Please try again."}), 500
        flash("Could not duplicate resume. Please try again.", "error")
        return redirect(url_for("main.profile"))


# ────────────────────────────────────────────────────────────────────────────
# JSON Resume Parser  (upload → extract → display)
# ────────────────────────────────────────────────────────────────────────────
@resume_bp.route("/resume/process-json", methods=["POST"])
@token_required
@limiter.limit("10 per hour")
def process_json():
    """
    Accept a PDF / DOCX / JSON file upload, extract structured data
    using the AI service, and redirect to the wizard pre-filled with
    that data.
    """
    from backend.services.ai_service import AIService

    uploaded_file = request.files.get("json_file")
    if not uploaded_file or not uploaded_file.filename:
        if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
            return jsonify({"success": False, "error": "No file selected."}), 400
        flash("No file selected.", "error")
        return redirect(url_for("main.json_features"))

    filename = secure_filename(uploaded_file.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    allowed = current_app.config.get("ALLOWED_RESUME_EXTENSIONS", {"json", "pdf", "docx"})
    if ext not in allowed:
        msg = f"Unsupported file type: .{ext}. Please upload JSON, PDF, or DOCX."
        if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
            return jsonify({"success": False, "error": msg}), 415
        flash(msg, "error")
        return redirect(url_for("main.json_features"))

    try:
        if ext == "json":
            # Parse JSON directly — no AI needed
            raw = uploaded_file.read().decode("utf-8")
            parsed_data = json.loads(raw)
        else:
            # For PDF/DOCX — save temporarily and use AI to extract text
            save_path = os.path.join(
                current_app.config["UPLOAD_FOLDER"],
                f"tmp_{uuid.uuid4().hex}.{ext}"
            )
            uploaded_file.save(save_path)
            try:
                parsed_data = AIService.extract_resume_from_file(save_path, ext)
            finally:
                if os.path.exists(save_path):
                    os.remove(save_path)

        if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
            return jsonify({"success": True, "data": parsed_data})

        from flask import session
        session["import_data"] = parsed_data
        flash("Resume parsed successfully! Fill in any missing details below.", "success")
        return redirect(url_for("main.dashboard"))

    except json.JSONDecodeError:
        msg = "The JSON file is malformed. Please check and try again."
        if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
            return jsonify({"success": False, "error": msg}), 422
        flash(msg, "error")
    except Exception:
        current_app.logger.exception("File processing error")
        msg = "Could not process the file. Please try again."
        if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("Origin"):
            return jsonify({"success": False, "error": msg}), 500
        flash(msg, "error")

    return redirect(url_for("main.json_features"))


# ────────────────────────────────────────────────────────────────────────────
# Version History
# ────────────────────────────────────────────────────────────────────────────
@resume_bp.route("/resume/<int:resume_id>/versions")
@token_required
def version_history(resume_id: int):
    """Return JSON list of version snapshots for a resume."""
    resume = Resume.query.filter_by(
        id=resume_id, user_id=g.current_user.id, is_deleted=False
    ).first_or_404()

    versions = (
        ResumeVersion.query
        .filter_by(resume_id=resume.id)
        .order_by(ResumeVersion.version_num.desc())
        .limit(20)
        .all()
    )

    return jsonify({
        "success": True,
        "data": [
            {
                "version_num": v.version_num,
                "created_at":  v.created_at.isoformat(),
            }
            for v in versions
        ],
    })


# ────────────────────────────────────────────────────────────────────────────
# Private helpers
# ────────────────────────────────────────────────────────────────────────────
def _validate_resume_payload(data: dict) -> list:
    """Return a list of validation error strings, or [] if valid."""
    errors = []
    if not data.get("name", "").strip():
        errors.append("Name is required.")
    if not data.get("title", "").strip():
        errors.append("Job title is required.")

    email = data.get("email", "").strip()
    if not email or "@" not in email:
        errors.append("A valid email address is required.")

    template = data.get("template", "")
    if template not in VALID_TEMPLATES:
        errors.append(f"Invalid template: {template!r}.")

    return errors


def _snapshot_resume(resume: Resume):
    """Save an immutable JSON snapshot of the resume before an update."""
    snap = ResumeVersion(
        resume_id   = resume.id,
        version_num = resume.version,
        snapshot    = json.dumps(resume.to_dict()),
    )
    db.session.add(snap)
