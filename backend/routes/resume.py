"""
routes/resume.py — Resume CRUD Blueprint
==========================================
All resume-document operations:

  POST /generate                          → create or update resume (from wizard)
  GET  /resume/<id>                       → view rendered resume (template page)
  GET  /resume/<id>/download              → download as JSON
  POST /resume/<id>/delete                → hard delete
  POST /resume/<id>/duplicate             → clone with a different template
  POST /resume/process-json               → parse uploaded file → JSON schema

The wizard sends one unified JSON payload to POST /generate regardless
of whether this is a create or an update (resume_id present = update).
"""

import json
import os
import uuid

from flask import (Blueprint, abort, current_app, flash, jsonify,
                   redirect, request, url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from backend.extensions import db, limiter
from backend.models import (Education, Experience, ExportHistory, Resume,
                             ResumeVersion)

resume_bp = Blueprint("resume", __name__)

# Valid template slugs (must match frontend values)
VALID_TEMPLATES = {f"template{i}" for i in range(1, 9)}


# ────────────────────────────────────────────────────────────────────────────
# Create / Update Resume  (called by wizard-vue.js → POST /generate)
# ────────────────────────────────────────────────────────────────────────────
@resume_bp.route("/generate", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def generate():
    """
    Accept the Vue wizard payload and persist it to the database.

    Expected JSON body (mirrors formData from wizard-vue.js):
    {
        "resume_id": null | int,    ← null = create, int = update
        "template":  "template1",
        "name":      "John Doe",
        "title":     "Senior Engineer",
        "email":     "john@example.com",
        "phone":     "1234567890",
        "address":   "New York, NY",
        "photo":     "/static/uploads/abc.jpg",   ← optional
        "summary":   "...",
        "skills":    ["Python", "Flask"],          ← array from wizard
        "languages": ["English (Native)"],
        "experience": [{ title, company, duration, description }],
        "education":  [{ degree, university, year }]
    }

    Returns JSON: { "success": true, "redirect": "/resume/<id>" }
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
                id=resume_id, user_id=current_user.id, is_deleted=False
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
            resume = Resume(user_id=current_user.id)
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
        flash("Resume saved successfully! ✅", "success")
        return jsonify({
            "success":  True,
            "redirect": url_for("resume.view_resume", resume_id=resume.id),
            "resume_id": resume.id,
        })

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Error saving resume")
        return jsonify({"success": False, "error": "Failed to save resume. Please try again."}), 500


# ────────────────────────────────────────────────────────────────────────────
# View Resume (rendered template page)
# ────────────────────────────────────────────────────────────────────────────
@resume_bp.route("/resume/<int:resume_id>")
@login_required
def view_resume(resume_id: int):
    """
    Return resume data as JSON.
    The frontend renders resumes client-side via resume.html.
    """
    resume = Resume.query.filter_by(
        id=resume_id, user_id=current_user.id, is_deleted=False
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
@login_required
def switch_template(resume_id: int):
    """Quick template switch without duplicating — updates in place."""
    resume = Resume.query.filter_by(
        id=resume_id, user_id=current_user.id, is_deleted=False
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
# Download DOC (plain-text placeholder; real DOCX needs python-docx)
# ────────────────────────────────────────────────────────────────────────────
@resume_bp.route("/resume/<int:resume_id>/download-doc")
@login_required
def download_doc(resume_id: int):
    """Download resume as plain text (DOCX generation is a future enhancement)."""
    from flask import current_app, Response
    resume = Resume.query.filter_by(
        id=resume_id, user_id=current_user.id, is_deleted=False
    ).first_or_404()

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
@login_required
def download_resume(resume_id: int):
    """
    Return the resume as a downloadable JSON file.
    Also records an ExportHistory entry.
    """
    resume = Resume.query.filter_by(
        id=resume_id, user_id=current_user.id, is_deleted=False
    ).first_or_404()

    # Log the export
    export = ExportHistory(
        resume_id=resume.id,
        user_id=current_user.id,
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
@login_required
def delete_resume(resume_id: int):
    """Soft-delete the resume so it disappears from the profile page."""
    resume = Resume.query.filter_by(
        id=resume_id, user_id=current_user.id, is_deleted=False
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
@login_required
def duplicate_resume(resume_id: int):
    """
    Clone a resume with a new template (the "Switch Template / Clone" UI).
    Creates a brand-new Resume row with the same data but a different template.
    """
    source = Resume.query.filter_by(
        id=resume_id, user_id=current_user.id, is_deleted=False
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
            user_id   = current_user.id,
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
                "success": True,
                "message": f"Resume cloned with {new_template.title()} template! ✅",
                "redirect": f"/resume?id={clone.id}"
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
@login_required
@limiter.limit("10 per hour")
def process_json():
    """
    Accept a PDF / DOCX / JSON file upload, extract structured data
    using the AI service, and redirect to the wizard pre-filled with
    that data.

    For JSON files: parse directly.
    For PDF/DOCX: use the AI service to extract structured data.
    """
    from backend.services.ai_service import AIService

    uploaded_file = request.files.get("json_file")
    if not uploaded_file or not uploaded_file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("main.json_features"))

    filename = secure_filename(uploaded_file.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    allowed = current_app.config.get("ALLOWED_RESUME_EXTENSIONS", {"json", "pdf", "docx"})
    if ext not in allowed:
        flash(f"Unsupported file type: .{ext}. Please upload JSON, PDF, or DOCX.", "error")
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

        # Re-direct to wizard with parsed data serialized in session
        from flask import session
        session["import_data"] = parsed_data
        flash("Resume parsed successfully! Fill in any missing details below.", "success")
        return redirect(url_for("main.dashboard"))

    except json.JSONDecodeError:
        flash("The JSON file is malformed. Please check and try again.", "error")
    except Exception as exc:
        current_app.logger.exception("File processing error")
        flash("Could not process the file. Please try again.", "error")

    return redirect(url_for("main.json_features"))


# ────────────────────────────────────────────────────────────────────────────
# Version History
# ────────────────────────────────────────────────────────────────────────────
@resume_bp.route("/resume/<int:resume_id>/versions")
@login_required
def version_history(resume_id: int):
    """Return JSON list of version snapshots for a resume."""
    resume = Resume.query.filter_by(
        id=resume_id, user_id=current_user.id, is_deleted=False
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
