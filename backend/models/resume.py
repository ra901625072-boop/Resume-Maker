import json
from datetime import datetime, timezone
from backend.extensions import db

def _utcnow():
    return datetime.now(timezone.utc)

class Resume(db.Model):
    """
    Core resume document. One user may have many resumes.
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
    skills      = db.Column(db.Text)
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
        Produce a dict that exactly mirrors the Vue wizard's formData shape.
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


class Experience(db.Model):
    """
    A single work-experience entry.
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


class Education(db.Model):
    """
    A single education entry.
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


class ResumeVersion(db.Model):
    """
    Immutable JSON snapshot of a resume at a point in time.
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
