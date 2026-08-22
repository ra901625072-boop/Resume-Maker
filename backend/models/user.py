from datetime import datetime, timezone
from backend.extensions import db

from werkzeug.security import generate_password_hash, check_password_hash

def _utcnow():
    return datetime.now(timezone.utc)

class User(db.Model):
    """
    User model representing registered user accounts.
    """
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), nullable=False, default="Guest User")
    email         = db.Column(db.String(254), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active     = db.Column(db.Boolean, default=True, nullable=False)
    is_admin      = db.Column(db.Boolean, default=False, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at    = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at    = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # ── Password management ───────────────────────────────────────────────────
    def set_password(self, raw_password: str) -> None:
        """Hash raw password with PBKDF2-SHA256 (260k iterations)."""
        self.password_hash = generate_password_hash(
            raw_password,
            method="pbkdf2:sha256:260000"
        )

    def check_password(self, raw_password: str) -> bool:
        """Check raw password against stored hash."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw_password)

    # ── Serialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "name":          self.name,
            "email":         self.email,
            "is_active":     self.is_active,
            "is_admin":      self.is_admin,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "created_at":    self.created_at.isoformat() if self.created_at else None,
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
