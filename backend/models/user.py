from datetime import datetime, timezone
from backend.extensions import db

def _utcnow():
    return datetime.now(timezone.utc)

class User(db.Model):
    """
    User model (optional profile reference).
    """
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), nullable=False, default="Guest User")
    email         = db.Column(db.String(254), nullable=True)
    is_admin      = db.Column(db.Boolean, default=False, nullable=False)
    created_at    = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at    = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

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


class UserSettings(db.Model):
    """
    Per-user preferences such as default template and notification flags.
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
