"""
routes/main.py — Main Page Blueprint
=====================================
Public-facing and authenticated page routes:

  GET /          → home (landing page — unauthenticated)
  GET /dashboard → resume form wizard (authenticated)
  GET /profile   → user profile + resume history
  GET /chat      → AI chat assistant page
  GET /json      → JSON parser / schema page
  GET /edit/<id> → re-open wizard pre-filled with existing resume data
"""

from flask import (Blueprint, flash, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user, login_required

from backend.models import Resume

main_bp = Blueprint("main", __name__)


# ────────────────────────────────────────────────────────────────────────────
# Home / Landing
# ────────────────────────────────────────────────────────────────────────────
@main_bp.route("/")
def home():
    """
    Public landing page.
    """
    return render_template("home.html")


# ────────────────────────────────────────────────────────────────────────────
# Dashboard — Resume Wizard (Create)
# ────────────────────────────────────────────────────────────────────────────
@main_bp.route("/dashboard")
@login_required
def dashboard():
    """
    The 4-step Vue wizard for creating a new resume.

    Also checks the Flask session for `import_data` — set by
    /resume/process-json when a user uploads a PDF/DOCX file from the
    JSON Features page.  If present the data is popped and passed to
    the template so Vue's mounted() hook pre-fills the form.
    """
    # Pop import data from session (set by /resume/process-json)
    import_data = session.pop("import_data", None)

    return render_template(
        "dashboard.html",
        user=current_user.name,
        editing=False,
        resume_data=import_data,  # None on normal visits; dict when arriving from file import
    )


# ────────────────────────────────────────────────────────────────────────────
# Dashboard — Resume Wizard (Edit)
# ────────────────────────────────────────────────────────────────────────────
@main_bp.route("/edit/<int:resume_id>")
@login_required
def edit_resume(resume_id: int):
    """
    Re-open the wizard pre-populated with an existing resume.

    The resume data is injected as `window.INITIAL_RESUME_DATA` via
    Jinja so the Vue app's mounted() hook can call populateData().
    """
    resume = Resume.query.filter_by(
        id=resume_id, user_id=current_user.id, is_deleted=False
    ).first_or_404()

    return render_template(
        "dashboard.html",
        user=current_user.name,
        editing=True,
        resume_data=resume.to_dict(),
    )


# ────────────────────────────────────────────────────────────────────────────
# Profile — Resume History
# ────────────────────────────────────────────────────────────────────────────
@main_bp.route("/profile")
@login_required
def profile():
    """
    User profile page showing:
      - Account details (name, email)
      - All resumes with View / Edit / Download / Delete / Clone actions
    """
    resumes_raw = (
        Resume.query
        .filter_by(user_id=current_user.id, is_deleted=False)
        .order_by(Resume.updated_at.desc())
        .all()
    )

    # Build lightweight display-safe dicts for the template
    resumes = [
        {
            "id":       r.id,
            "title":    r.title,
            "template": r.template,
            # Human-readable date e.g. "25 May 2026"
            "date":     r.updated_at.strftime("%d %b %Y") if r.updated_at else "—",
        }
        for r in resumes_raw
    ]

    return render_template(
        "profile.html",
        user=current_user,
        resumes=resumes,
        total_prints=len(resumes),
    )


# ────────────────────────────────────────────────────────────────────────────
# AI Chat Assistant Page
# ────────────────────────────────────────────────────────────────────────────
@main_bp.route("/chat")
@login_required
def chat():
    """
    Renders the full-page AI chat interface.
    Actual messages are sent to /api/chat (POST) via fetch() in the template.
    """
    return render_template("chat.html", user=current_user.name)


# ────────────────────────────────────────────────────────────────────────────
# JSON Resume Parser Page
# ────────────────────────────────────────────────────────────────────────────
@main_bp.route("/json")
@login_required
def json_features():
    """
    Page with drag-drop upload zone and JSON schema viewer.
    File processing is handled by resume_bp at /resume/process-json.
    """
    return render_template("json_features.html", user=current_user.name)


# ────────────────────────────────────────────────────────────────────────────
# AI File Upload Analyzer Page
# ────────────────────────────────────────────────────────────────────────────
@main_bp.route("/upload")
@login_required
def upload_resume():
    """
    AI-powered resume upload page.
    Accepts image / PDF / DOCX and extracts structured resume data via
    POST /api/extract-json (multimodal vision + text extraction).
    """
    return render_template("upload_resume.html", user=current_user.name)
