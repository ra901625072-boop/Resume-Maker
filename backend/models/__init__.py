"""
models/__init__.py — SQLAlchemy Database Models
================================================
Normalized SQLite schema designed to exactly match the WISAXIS
Resume Maker frontend data-flow:

  Users ──< Resumes ──< Experience
                   ──< Education
                   ──< Skills (stored as CSV on the Resume row)
                   ──< Languages (stored as JSON list on the Resume row)
                   ──< ExportHistory
  Users ──< AIHistory
  Templates (static seed data)
  UserSettings (1-to-1 with User)

Design decisions:
  • Skills and Languages are stored as lightweight denormalized columns
    (comma-separated / JSON array) because the wizard form treats them
    as a single textarea/list — normalizing would add complexity with
    no query benefit at this scale.
  • Experience and Education are proper related tables so they can be
    CRUD'd independently (e.g. the "Remove Experience" button in the
    wizard).
  • All timestamps are UTC-aware via server_default=func.now().
  • Soft-delete is NOT used — hard deletes keep the schema simple.
"""

import json
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from backend.extensions import db


# ────────────────────────────────────────────────────────────────────────────
# Helper: current UTC time
# ────────────────────────────────────────────────────────────────────────────
def _utcnow():
    return datetime.now(timezone.utc)


# ────────────────────────────────────────────────────────────────────────────
# User
# ────────────────────────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    """
    Registered user account.

    Flask-Login requires UserMixin which provides:
      is_authenticated, is_active, is_anonymous, get_id()
    """
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), nullable=False)
    email         = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin      = db.Column(db.Boolean, default=False, nullable=False)
    is_active     = db.Column(db.Boolean, default=True, nullable=False)
    created_at    = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at    = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    resumes      = db.relationship("Resume", backref="owner", lazy="dynamic",
                                   cascade="all, delete-orphan")
    ai_history   = db.relationship("AIHistory", backref="user", lazy="dynamic",
                                   cascade="all, delete-orphan")
    settings     = db.relationship("UserSettings", backref="user", uselist=False,
                                   cascade="all, delete-orphan")

    # ── Password helpers ──────────────────────────────────────────────────────
    def set_password(self, raw_password: str):
        """Hash and store a password. Never store plaintext."""
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        """Return True if the raw password matches the stored hash."""
        return check_password_hash(self.password_hash, raw_password)

    # ── Serialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "name":       self.name,
            "email":      self.email,
            "is_admin":   self.is_admin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<User id={self.id} email={self.email!r}>"


# ────────────────────────────────────────────────────────────────────────────
# UserSettings  (1-to-1 with User)
# ────────────────────────────────────────────────────────────────────────────
class UserSettings(db.Model):
    """
    Per-user preferences such as default template and notification flags.
    Created automatically when a user registers.
    """
    __tablename__ = "user_settings"

    id                  = db.Column(db.Integer, primary_key=True)
    user_id             = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                                    unique=True, nullable=False)
    default_template    = db.Column(db.String(50), default="template1")
    email_notifications = db.Column(db.Boolean, default=True)
    theme_preference    = db.Column(db.String(20), default="dark")
    updated_at          = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def __repr__(self):
        return f"<UserSettings user_id={self.user_id}>"


# ────────────────────────────────────────────────────────────────────────────
# Resume  (top-level document)
# ────────────────────────────────────────────────────────────────────────────
class Resume(db.Model):
    """
    Core resume document.  One user may have many resumes.

    Fields map 1-to-1 with the Vue wizard formData object so the
    frontend payload can be saved directly with minimal transformation.
    """
    __tablename__ = "resumes"

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    template    = db.Column(db.String(50), nullable=False, default="template1")

    # Personal info (Step 1 of wizard)
    name        = db.Column(db.String(120), nullable=False)
    title       = db.Column(db.String(120), nullable=False)
    email       = db.Column(db.String(254), nullable=False)
    phone       = db.Column(db.String(30))
    address     = db.Column(db.String(255))
    photo_url   = db.Column(db.String(512))          # path to uploaded photo

    # Step 3: summary + skills + languages
    summary     = db.Column(db.Text)
    # Comma-separated: "Python, Flask, SQL"  (matches wizard input exactly)
    skills      = db.Column(db.Text)
    # JSON array: ["English (Native)", "French (B2)"]
    languages   = db.Column(db.Text, default="[]")

    # Metadata
    version     = db.Column(db.Integer, default=1, nullable=False)  # for version history
    is_deleted  = db.Column(db.Boolean, default=False, nullable=False)  # soft delete
    created_at  = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at  = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # ── Relationships ─────────────────────────────────────────────────────────
    experience    = db.relationship("Experience", backref="resume",
                                    lazy="selectin", order_by="Experience.position",
                                    cascade="all, delete-orphan")
    education     = db.relationship("Education", backref="resume",
                                    lazy="selectin", order_by="Education.position",
                                    cascade="all, delete-orphan")
    export_history = db.relationship("ExportHistory", backref="resume",
                                     lazy="dynamic", cascade="all, delete-orphan")
    versions       = db.relationship("ResumeVersion", backref="resume",
                                     lazy="dynamic", cascade="all, delete-orphan")

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def skills_list(self) -> list:
        """Return skills as a Python list."""
        if not self.skills:
            return []
        return [s.strip() for s in self.skills.split(",") if s.strip()]

    @property
    def languages_list(self) -> list:
        """Return languages as a Python list."""
        try:
            return json.loads(self.languages or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def to_dict(self) -> dict:
        """
        Produce a dict that exactly mirrors the Vue wizard's formData shape
        so the frontend can re-hydrate the form when editing.
        """
        return {
            "id":         self.id,
            "template":   self.template,
            "name":       self.name,
            "title":      self.title,
            "email":      self.email,
            "phone":      self.phone or "",
            "address":    self.address or "",
            "photo":      self.photo_url or "",
            "summary":    self.summary or "",
            "skills":     self.skills or "",
            "languages":  self.languages_list,
            "experience": [e.to_dict() for e in self.experience],
            "education":  [e.to_dict() for e in self.education],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<Resume id={self.id} name={self.name!r}>"


# ────────────────────────────────────────────────────────────────────────────
# Experience  (child of Resume)
# ────────────────────────────────────────────────────────────────────────────
class Experience(db.Model):
    """
    A single work-experience entry.
    Matches the exp object inside wizard formData.experience[].
    """
    __tablename__ = "experiences"

    id          = db.Column(db.Integer, primary_key=True)
    resume_id   = db.Column(db.Integer, db.ForeignKey("resumes.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    position    = db.Column(db.Integer, default=0)   # display order
    title       = db.Column(db.String(150), nullable=False)
    company     = db.Column(db.String(150))
    duration    = db.Column(db.String(100))           # "Jan 2020 – Present"
    description = db.Column(db.Text)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "title":       self.title,
            "company":     self.company or "",
            "duration":    self.duration or "",
            "description": self.description or "",
        }

    def __repr__(self):
        return f"<Experience id={self.id} title={self.title!r}>"


# ────────────────────────────────────────────────────────────────────────────
# Education  (child of Resume)
# ────────────────────────────────────────────────────────────────────────────
class Education(db.Model):
    """
    A single education entry.
    Matches the edu object inside wizard formData.education[].
    """
    __tablename__ = "educations"

    id          = db.Column(db.Integer, primary_key=True)
    resume_id   = db.Column(db.Integer, db.ForeignKey("resumes.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    position    = db.Column(db.Integer, default=0)
    degree      = db.Column(db.String(200))            # "B.Sc Computer Science"
    university  = db.Column(db.String(200))
    year        = db.Column(db.String(50))             # "2021" or "2018-2022"

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "degree":     self.degree or "",
            "university": self.university or "",
            "year":       self.year or "",
        }

    def __repr__(self):
        return f"<Education id={self.id} degree={self.degree!r}>"


# ────────────────────────────────────────────────────────────────────────────
# ResumeVersion  (snapshot for version history)
# ────────────────────────────────────────────────────────────────────────────
class ResumeVersion(db.Model):
    """
    Immutable JSON snapshot of a resume at a point in time.
    Created automatically before every update so users can roll back.
    """
    __tablename__ = "resume_versions"

    id          = db.Column(db.Integer, primary_key=True)
    resume_id   = db.Column(db.Integer, db.ForeignKey("resumes.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    version_num = db.Column(db.Integer, nullable=False)
    snapshot    = db.Column(db.Text, nullable=False)   # JSON blob of Resume.to_dict()
    created_at  = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    def get_snapshot(self) -> dict:
        return json.loads(self.snapshot)

    def __repr__(self):
        return f"<ResumeVersion resume_id={self.resume_id} v={self.version_num}>"


# ────────────────────────────────────────────────────────────────────────────
# ExportHistory
# ────────────────────────────────────────────────────────────────────────────
class ExportHistory(db.Model):
    """
    Records every time a user exports / downloads a resume.
    Useful for analytics and re-download links.
    """
    __tablename__ = "export_history"

    id          = db.Column(db.Integer, primary_key=True)
    resume_id   = db.Column(db.Integer, db.ForeignKey("resumes.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                             nullable=False)
    format      = db.Column(db.String(10), default="pdf")   # "pdf" | "json"
    exported_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self):
        return f"<ExportHistory resume_id={self.resume_id} format={self.format}>"


# ────────────────────────────────────────────────────────────────────────────
# AIHistory  (stores every AI generation for analytics / replay)
# ────────────────────────────────────────────────────────────────────────────
class AIHistory(db.Model):
    """
    Audit log of every AI request made by a user.
    Enables replay, analytics, token-budget tracking, and debugging.
    """
    __tablename__ = "ai_history"

    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                               nullable=False, index=True)
    resume_id     = db.Column(db.Integer, db.ForeignKey("resumes.id", ondelete="SET NULL"),
                               nullable=True)
    action        = db.Column(db.String(60), nullable=False)
    # e.g. "generate_summary" | "generate_experience" | "chat" | "ats_score"
    prompt        = db.Column(db.Text)
    response      = db.Column(db.Text)
    model_used    = db.Column(db.String(100))
    tokens_used   = db.Column(db.Integer, default=0)
    success       = db.Column(db.Boolean, default=True)
    error_message = db.Column(db.Text)
    created_at    = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self):
        return f"<AIHistory id={self.id} action={self.action!r}>"


# ────────────────────────────────────────────────────────────────────────────
# Template  (seed data — the 8 visual templates)
# ────────────────────────────────────────────────────────────────────────────
class Template(db.Model):
    """
    Static catalogue of available resume templates.
    Seeded once at startup; referenced by Resume.template.
    """
    __tablename__ = "templates"

    id          = db.Column(db.Integer, primary_key=True)
    slug        = db.Column(db.String(50), unique=True, nullable=False)  # "template1"
    name        = db.Column(db.String(80), nullable=False)               # "Executive"
    tag         = db.Column(db.String(50))                               # "Professional"
    preview_img = db.Column(db.String(120))                              # "templateA.webp"
    is_active   = db.Column(db.Boolean, default=True)
    sort_order  = db.Column(db.Integer, default=0)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "slug":        self.slug,
            "name":        self.name,
            "tag":         self.tag,
            "preview_img": self.preview_img,
        }

    def __repr__(self):
        return f"<Template slug={self.slug!r}>"


# ────────────────────────────────────────────────────────────────────────────
# Seed helpers
# ────────────────────────────────────────────────────────────────────────────
TEMPLATE_SEED = [
    {"slug": "template1", "name": "Executive",    "tag": "Professional", "preview_img": "templateA.webp", "sort_order": 1},
    {"slug": "template2", "name": "Modern",       "tag": "Trendy",       "preview_img": "templateB.webp", "sort_order": 2},
    {"slug": "template3", "name": "Creative",     "tag": "Expressive",   "preview_img": "templateC.webp", "sort_order": 3},
    {"slug": "template4", "name": "Minimalist",   "tag": "Clean",        "preview_img": "templateD.webp", "sort_order": 4},
    {"slug": "template5", "name": "Academic",     "tag": "Scholarly",    "preview_img": "templateE.webp", "sort_order": 5},
    {"slug": "template6", "name": "Professional", "tag": "Robust",       "preview_img": "templateF.webp", "sort_order": 6},
    {"slug": "template7", "name": "Classic",      "tag": "Elegant",      "preview_img": "templateG.webp", "sort_order": 7},
    {"slug": "template8", "name": "Compact",      "tag": "Sleek",        "preview_img": "templateH.webp", "sort_order": 8},
]


def seed_templates():
    """Insert template rows if they don't already exist."""
    for tdata in TEMPLATE_SEED:
        exists = Template.query.filter_by(slug=tdata["slug"]).first()
        if not exists:
            db.session.add(Template(**tdata))
    db.session.commit()
