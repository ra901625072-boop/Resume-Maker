from datetime import datetime, timezone
from backend.extensions import db

def _utcnow():
    return datetime.now(timezone.utc)

class ExportHistory(db.Model):
    """
    Records every time a user exports / downloads a resume.
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
