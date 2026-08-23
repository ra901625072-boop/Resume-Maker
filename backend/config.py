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
    _raw_db_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not _raw_db_url:
        _raw_db_url = f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'wisaxis.db')}"
    elif _raw_db_url.startswith("postgres://"):
        _raw_db_url = _raw_db_url.replace("postgres://", "postgresql://", 1)
    
    # Ensure SSL mode if connecting to external PostgreSQL
    if "render.com" in _raw_db_url and "sslmode=" not in _raw_db_url:
        _joiner = "&" if "?" in _raw_db_url else "?"
        _raw_db_url = f"{_raw_db_url}{_joiner}sslmode=require"

    SQLALCHEMY_DATABASE_URI = _raw_db_url
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
    # All file types accepted by the AI file-analysis & JSON extraction endpoint
    ALLOWED_ANALYZE_EXTENSIONS = {
        "jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif",
        "pdf", "docx", "doc", "txt", "rtf", "odt", "md", "csv", "json"
    }

    # ── AI / OpenRouter ───────────────────────────────────────────────────────
    OPENROUTER_API_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    # Multi-Tier Intelligent Model Fallback Chains
    # Primary  → High-performance auto-routing model
    AI_MODEL_PRIMARY   = os.environ.get(
        "AI_MODEL_PRIMARY", "openrouter/free"
    )
    # Vision models for images & scanned documents (tried in order)
    AI_MODEL_VISION    = os.environ.get(
        "AI_MODEL_VISION",
        "openrouter/free,google/gemma-4-26b-a4b-it:free,nvidia/nemotron-nano-12b-v2-vl:free,dots-studio/dots-3-note-preview:free"
    )
    # Secondary → High-context reasoning model (Gemma 4 / Nemotron)
    AI_MODEL_SECONDARY = os.environ.get(
        "AI_MODEL_SECONDARY", "google/gemma-4-26b-a4b-it:free"
    )
    # Emergency → ultra-fast free fallback for zero-downtime
    AI_MODEL_EMERGENCY = os.environ.get(
        "AI_MODEL_EMERGENCY", "nvidia/nemotron-3.5-lightning:free"
    )
    # Legacy single-model key (kept for backward compat)
    OPENROUTER_MODEL   = os.environ.get(
        "OPENROUTER_MODEL", "openrouter/free"
    )
    # Per-model request timeout in seconds (ensures fast responses under WSGI limits)
    AI_REQUEST_TIMEOUT = int(os.environ.get("AI_REQUEST_TIMEOUT", "18"))
    # Maximum tokens for AI responses (high limit for full document JSON extraction)
    AI_MAX_TOKENS      = int(os.environ.get("AI_MAX_TOKENS", "4096"))

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
