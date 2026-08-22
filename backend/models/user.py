from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from backend.extensions import db

def _utcnow():
    return datetime.now(timezone.utc)

class User(UserMixin, db.Model):
    """
    Registered user account.
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
