"""
models/__init__.py — SQLAlchemy Database Models
================================================
Exposes all modular model classes for import compatibility.
"""

from backend.models.user import User, UserSettings
from backend.models.resume import Resume, Experience, Education, ResumeVersion
from backend.models.export_history import ExportHistory
from backend.models.ai_history import AIHistory
from backend.models.template import Template, seed_templates

__all__ = [
    "User",
    "UserSettings",
    "Resume",
    "Experience",
    "Education",
    "ResumeVersion",
    "ExportHistory",
    "AIHistory",
    "Template",
    "seed_templates",
]
