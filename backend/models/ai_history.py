from datetime import datetime, timezone
from backend.extensions import db

def _utcnow():
    return datetime.now(timezone.utc)

class AIHistory(db.Model):
    """
    Audit log of every AI request made by a user.
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
