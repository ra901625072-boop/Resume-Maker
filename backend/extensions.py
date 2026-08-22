"""
extensions.py — Flask Extension Instances
==========================================
All extensions are instantiated here (without an app) so they can be
imported across the project without circular imports.
The actual app binding happens inside create_app() via the standard
Flask application-factory pattern.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS

# ── Database ORM ──────────────────────────────────────────────────────────────
db = SQLAlchemy()

# ── CSRF Protection ───────────────────────────────────────────────────────────
csrf = CSRFProtect()

# ── Rate Limiting ─────────────────────────────────────────────────────────────
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour", "50 per minute"],
    storage_uri="memory://",   # overridden in create_app with REDIS if available
)

# ── CORS ─────────────────────────────────────────────────────────────────────
cors = CORS()
