"""
config.py — Application Configuration
======================================
Centralised configuration for all environments.
Loads secrets from environment variables so no credentials
live inside the source code.
"""

import os
from datetime import timedelta


# ---------------------------------------------------------------------------
# Base configuration shared by all environments
# ---------------------------------------------------------------------------
class Config:
    # ── Security ─────────────────────────────────────────────────────────────
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production-!@#$%^")
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour token lifetime



    # ── Session ───────────────────────────────────────────────────────────────
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    REMEMBER_COOKIE_SAMESITE = os.environ.get("REMEMBER_COOKIE_SAMESITE", "Lax")
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # ── Database ──────────────────────────────────────────────────────────────
    # Uses SQLite by default (file-based, zero infrastructure)
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    _db_url = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'wisaxis.db')}"
    )
    # Render provides postgres:// but SQLAlchemy requires postgresql://
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,        # detect stale connections
        "pool_recycle": 300,          # recycle connections every 5 min
    }

    # ── File Uploads ──────────────────────────────────────────────────────────
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "instance", "uploads")
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB cap (images + PDFs)
    ALLOWED_PHOTO_EXTENSIONS  = {"jpg", "jpeg", "png", "webp"}
    ALLOWED_RESUME_EXTENSIONS = {"json", "pdf", "docx", "doc"}
    # All file types accepted by the AI file-analysis endpoint
    ALLOWED_ANALYZE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf", "docx", "doc"}

    # ── AI / OpenRouter ───────────────────────────────────────────────────────
    OPENROUTER_API_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    # 3-Tier fallback model chain
    # Primary  → high-quality reasoning (multimodal-capable)
    AI_MODEL_PRIMARY   = os.environ.get(
        "AI_MODEL_PRIMARY", "google/gemini-2.0-flash-exp:free"
    )
    # Secondary → fast, lightweight free model
    AI_MODEL_SECONDARY = os.environ.get(
        "AI_MODEL_SECONDARY", "meta-llama/llama-3.1-8b-instruct:free"
    )
    # Emergency → ultra-fast free fallback for zero-downtime
    AI_MODEL_EMERGENCY = os.environ.get(
        "AI_MODEL_EMERGENCY", "mistralai/mistral-7b-instruct:free"
    )
    # Legacy single-model key (kept for backward compat)
    OPENROUTER_MODEL   = os.environ.get(
        "OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free"
    )
    # Request timeout in seconds
    AI_REQUEST_TIMEOUT = int(os.environ.get("AI_REQUEST_TIMEOUT", "30"))
    # Maximum tokens for AI responses
    AI_MAX_TOKENS      = int(os.environ.get("AI_MAX_TOKENS", "1024"))

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATELIMIT_STORAGE_URL = os.environ.get("REDIS_URL", "memory://")
    RATELIMIT_DEFAULT = "200 per hour"

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    LOG_FILE = os.path.join(BASE_DIR, "instance", "app.log")

    # ── CORS ──────────────────────────────────────────────────────────────────
    _origins = [
        "https://resume-maker-five-bice.vercel.app",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:5000",
        "http://localhost:5000",
        "http://127.0.0.1:5500",
        "http://localhost:5500"
    ]
    _env_origins = os.environ.get("CORS_ORIGINS", "")
    if _env_origins:
        _origins.extend([o.strip() for o in _env_origins.split(",") if o.strip()])
    CORS_ORIGINS = _origins

    # ── Pagination ────────────────────────────────────────────────────────────
    RESUMES_PER_PAGE = 12

    # ── App meta ─────────────────────────────────────────────────────────────
    APP_NAME = "WISAXIS Resume Maker"
    APP_VERSION = "2.0.0"


# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------
class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False
    SESSION_COOKIE_SECURE = False  # HTTP is fine locally
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SAMESITE = "Lax"
    SQLALCHEMY_ECHO = False         # Set True to log raw SQL queries


# ---------------------------------------------------------------------------
# Testing (in-memory SQLite, no CSRF, no rate limits)
# ---------------------------------------------------------------------------
class TestingConfig(Config):
    DEBUG = True
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    SESSION_COOKIE_SECURE = False


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------
class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True   # Requires HTTPS
    SESSION_COOKIE_SAMESITE = "None"  # Requires cross-site cookies for Vercel -> Backend API
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_SAMESITE = "None"
    WTF_CSRF_SSL_STRICT = True


# ---------------------------------------------------------------------------
# Config registry — resolved by FLASK_ENV environment variable
# ---------------------------------------------------------------------------
config_map = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config() -> Config:
    """Return the config class that matches FLASK_ENV or RENDER environment."""
    if os.environ.get("RENDER", "").lower() == "true":
        return ProductionConfig
    env = os.environ.get("FLASK_ENV", "development").lower()
    return config_map.get(env, DevelopmentConfig)
