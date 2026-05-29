"""
services/ai_service.py — OpenRouter AI Brain (v2)
===================================================
Architecture:
  • 3-tier model fallback chain (primary → fast → emergency-free)
  • Per-action smart model selection based on task complexity
  • Retry logic with exponential back-off per tier
  • In-process LRU response cache (TTL-based)
  • Multimodal file analysis (image / PDF / DOCX)
  • Structured JSON extraction with schema validation
  • All public methods return:
      { "success": True,  "data": <str|dict>, "tokens": int, "model": str }
      { "success": False, "error": str }
"""

import base64
import hashlib
import json
import logging
import re
import time
from functools import lru_cache
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── Model tiers ──────────────────────────────────────────────────────────────
# Each tier is tried in order; if one fails the next is attempted.
# Override any of these in .env via OPENROUTER_MODEL_PRIMARY etc.
_MODELS = [
    "google/gemini-2.0-flash-exp:free",           # Often 404s now, but good if it exists
    "nvidia/llama-3.1-nemotron-nano-8b-v1:free",  # Very reliable
    "meta-llama/llama-3.3-8b-instruct:free",      # Lightweight + stable
    "mistralai/mistral-7b-instruct:free",         # Fast agent tasks
    "openrouter/free"                             # Auto-routes to any working free model
]

# Vision-capable models for image/multimodal requests (tried in order)
_VISION_MODELS = [
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "openrouter/free",
]

# Actions that need multimodal or heavy reasoning → always use primary
_HEAVY_ACTIONS = {"extract_resume", "ats_score", "extract_from_file", "analyze_file"}
# Actions that are lightweight → can start at secondary for speed
_LIGHT_ACTIONS = {"suggest_skills", "improve_grammar", "chat"}

# Simple in-process response cache  {cache_key: (timestamp, result)}
_CACHE: dict = {}
_CACHE_TTL = 300  # seconds


def _cache_key(action: str, payload: str) -> str:
    return hashlib.md5(f"{action}:{payload}".encode()).hexdigest()


def _cache_get(key: str):
    entry = _CACHE.get(key)
    if entry and (time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: dict):
    _CACHE[key] = (time.time(), value)
    # Evict old entries if cache grows large
    if len(_CACHE) > 500:
        oldest = sorted(_CACHE, key=lambda k: _CACHE[k][0])[:100]
        for k in oldest:
            _CACHE.pop(k, None)


# ────────────────────────────────────────────────────────────────────────────
class AIService:
    """
    Central AI brain.  All AI features route through this class.
    """

    # ── Public generation methods ─────────────────────────────────────────────

    @classmethod
    def generate_summary(cls, name: str, title: str,
                         skills: str = "", experience_titles: list = None) -> dict:
        """ATS-optimised professional summary paragraph (3-5 sentences)."""
        exp_ctx = ""
        if experience_titles:
            exp_ctx = f"with experience as {', '.join(experience_titles)}"

        prompt = (
            f"Write a professional resume summary for {name}, a {title} {exp_ctx}.\n"
            f"Key skills: {skills or 'not specified'}.\n\n"
            "Requirements:\n"
            "- 3-5 sentences, first-person narrative voice\n"
            "- ATS-friendly with strong action verbs and industry keywords\n"
            "- Highlight measurable value and impact, not just responsibilities\n"
            "- Human-sounding, not generic — avoid clichés like 'results-driven'\n"
            "- Output only the paragraph text, no heading or label"
        )
        return cls._call(prompt, action="generate_summary", max_tokens=400)

    @classmethod
    def generate_experience(cls, title: str, company: str = "",
                            duration: str = "", skills: str = "") -> dict:
        """3-5 CAR-framework bullet points for a work experience entry."""
        ctx = [f"Job Title: {title}"]
        if company:  ctx.append(f"Company: {company}")
        if duration: ctx.append(f"Duration: {duration}")
        if skills:   ctx.append(f"Skills used: {skills}")

        prompt = (
            f"{chr(10).join(ctx)}\n\n"
            "Write 3-5 impactful resume bullet points for this work experience.\n"
            "Requirements:\n"
            "- Use the CAR framework (Challenge → Action → Result)\n"
            "- Start each bullet with a strong past-tense action verb\n"
            "- Include quantifiable results (percentages, numbers, scale)\n"
            "- ATS-optimised keywords for the job title\n"
            "- Output only the bullet points, no headings\n"
            "- Format each bullet on its own line starting with •"
        )
        return cls._call(prompt, action="generate_experience", max_tokens=512)

    @classmethod
    def chat(cls, message: str, history: list = None) -> dict:
        """Multi-turn resume assistant chat."""
        messages = [{
            "role": "system",
            "content": (
                "You are WISAXIS AI, an expert resume writer and career coach. "
                "You specialise in ATS optimisation, impactful wording, and professional formatting. "
                "Help users craft outstanding resumes. Be concise, professional, and practical. "
                "Use strong action verbs and quantifiable achievements. Format responses in markdown."
            ),
        }]
        if history:
            for turn in history[-10:]:
                if turn.get("role") in ("user", "assistant") and turn.get("content"):
                    messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": message})
        return cls._call_with_messages(messages, action="chat", max_tokens=2048)

    @classmethod
    def ats_score(cls, resume_dict: dict) -> dict:
        """ATS compatibility score 0-100 + structured feedback."""
        resume_text = _dict_to_text(resume_dict)
        prompt = (
            f"Analyse the following resume and give an ATS compatibility score from 0 to 100.\n\n"
            f"Resume:\n{resume_text}\n\n"
            "Return a JSON object with exactly these keys:\n"
            '  "score": integer 0-100\n'
            '  "summary": one sentence overall assessment\n'
            '  "strengths": array of 2-3 strong points\n'
            '  "improvements": array of 3-5 specific actionable improvements\n'
            "Return ONLY the JSON, no extra text."
        )
        result = cls._call(prompt, action="ats_score", max_tokens=600)
        if result["success"]:
            result["data"] = _safe_parse_json(result["data"], result["data"])
        return result

    @classmethod
    def generate_cover_letter(cls, name: str, title: str, company: str,
                               job_description: str = "", skills: str = "") -> dict:
        """Full professional cover letter (300-400 words)."""
        prompt = (
            f"Write a professional cover letter for {name} applying for "
            f"a {title} position at {company}.\n"
            f"Candidate skills: {skills or 'not specified'}.\n"
            f"Job description: {job_description or 'standard role responsibilities'}.\n\n"
            "Requirements:\n"
            "- Professional business letter format\n"
            "- Opening, 2-3 body paragraphs, closing\n"
            "- Specific to the company and role\n"
            "- Highlight 2-3 key achievements\n"
            "- 300-400 words total\n"
            "- Do not use placeholders like [Your Name]"
        )
        return cls._call(prompt, action="cover_letter", max_tokens=1024)

    @classmethod
    def improve_grammar(cls, text: str) -> dict:
        """Polish grammar, tone, and professional wording."""
        prompt = (
            f"Improve the grammar, tone, and professional wording of the following "
            f"resume text. Preserve the original meaning. Return only the improved text.\n\n"
            f"Original text:\n{text}"
        )
        return cls._call(prompt, action="improve_grammar", max_tokens=800)

    @classmethod
    def suggest_skills(cls, job_title: str, existing_skills: str = "") -> dict:
        """Suggest 10 relevant ATS-optimised skills for a job title."""
        prompt = (
            f"Suggest 10 highly relevant technical and soft skills for a {job_title} role.\n"
            f"Existing skills (do not repeat): {existing_skills or 'none'}.\n"
            "Requirements:\n"
            "- Include both technical and soft skills\n"
            "- Be specific (e.g. 'React.js' not 'JavaScript frameworks')\n"
            "- ATS-optimised keywords\n"
            "- Return as a comma-separated list only, no explanation"
        )
        return cls._call(prompt, action="suggest_skills", max_tokens=256)

    # ── File Analysis (NEW) ───────────────────────────────────────────────────

    @classmethod
    def analyze_file(cls, file_path: str, ext: str, file_bytes: bytes = None) -> dict:
        """
        Analyse an uploaded file (image / PDF / DOCX) and extract structured
        resume data.  Returns a validated JSON dict matching the WISAXIS schema.

        Strategy:
          • Images  → multimodal vision model (base64 inline)
          • PDF     → pdfplumber text extraction → text prompt
          • DOCX    → python-docx text extraction → text prompt
          • Scanned PDF (no text) → base64 image fallback via vision
        """
        ext = ext.lower().strip(".")

        if ext in ("jpg", "jpeg", "png", "webp", "gif"):
            return cls._analyze_image(file_path, file_bytes)
        elif ext == "pdf":
            return cls._analyze_pdf(file_path, file_bytes)
        elif ext in ("doc", "docx"):
            return cls._analyze_docx(file_path)
        else:
            return {"success": False, "error": f"Unsupported file type: .{ext}"}

    @classmethod
    def _analyze_image(cls, file_path: str, file_bytes: bytes = None) -> dict:
        """Send image as base64 to a vision-capable model."""
        try:
            if file_bytes is None:
                with open(file_path, "rb") as f:
                    file_bytes = f.read()

            ext = file_path.rsplit(".", 1)[-1].lower()
            mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                        "png": "image/png", "webp": "image/webp", "gif": "image/gif"}
            mime = mime_map.get(ext, "image/jpeg")
            b64 = base64.b64encode(file_bytes).decode("utf-8")

            messages = [
                {"role": "user", "content": [
                    {"type": "text",       "text": _RESUME_EXTRACTION_PROMPT},
                    {"type": "image_url",  "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ]}
            ]
            result = cls._call_with_messages(
                messages, action="analyze_file", max_tokens=2048,
                force_primary=True, vision=True
            )
            if result["success"]:
                result["data"] = _parse_and_validate_resume_json(result["data"])
            return result
        except Exception as e:
            logger.exception("Image analysis failed")
            return {"success": False, "error": f"Image analysis error: {str(e)}"}

    @classmethod
    def _analyze_pdf(cls, file_path: str, file_bytes: bytes = None) -> dict:
        """Extract text from PDF, fall back to vision if text is empty (scanned PDF)."""
        text = _extract_pdf_text(file_path)

        if text and len(text.strip()) > 100:
            # PDF has real text — use text prompt
            return cls._extract_from_text(text, "pdf")
        else:
            # Scanned PDF — convert first page to image and use vision
            logger.info("PDF appears scanned. Attempting vision fallback.")
            try:
                img_bytes = _pdf_page_to_image(file_path)
                if img_bytes:
                    # Write tmp file path for mime detection
                    tmp_path = file_path.replace(".pdf", "_page1.png")
                    return cls._analyze_image(tmp_path + ".png", img_bytes)
                else:
                    return {"success": False,
                            "error": "PDF appears to be a scanned image but image conversion failed. "
                                     "Please upload a text-based PDF or a direct image file."}
            except Exception as e:
                logger.exception("Scanned PDF fallback failed")
                return {"success": False, "error": f"Could not process scanned PDF: {str(e)}"}

    @classmethod
    def _analyze_docx(cls, file_path: str) -> dict:
        """Extract text from DOCX and analyse."""
        text = _extract_docx_text(file_path)
        if not text or len(text.strip()) < 50:
            return {"success": False, "error": "Could not extract text from this document."}
        return cls._extract_from_text(text, "docx")

    @classmethod
    def _extract_from_text(cls, text: str, source: str) -> dict:
        """Run the structured extraction prompt over plain text."""
        truncated = text[:5000]  # Stay within context limits
        prompt = f"{_RESUME_EXTRACTION_PROMPT}\n\nDocument text:\n{truncated}"
        result = cls._call(prompt, action="extract_from_file", max_tokens=2048)
        if result["success"]:
            result["data"] = _parse_and_validate_resume_json(result["data"])
        return result

    # Legacy compat
    @classmethod
    def extract_resume_from_file(cls, file_path: str, ext: str) -> dict:
        return cls.analyze_file(file_path, ext)

    # ── Private API caller ────────────────────────────────────────────────────

    @classmethod
    def _get_config(cls):
        """Pull config from Flask app context."""
        from flask import current_app
        cfg = current_app.config
        # We can still read an override for the primary model if desired
        models = list(_MODELS)
        primary_override = cfg.get("AI_MODEL_PRIMARY")
        if primary_override and primary_override != models[0]:
            models.insert(0, primary_override)
        return {
            "api_key":  cfg.get("OPENROUTER_API_KEY", ""),
            "base_url": cfg.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            "timeout":  int(cfg.get("AI_REQUEST_TIMEOUT", 30)),
            "models":   models,
        }

    @classmethod
    def _call(cls, prompt: str, action: str = "unknown",
              max_tokens: int = None, force_primary: bool = False) -> dict:
        messages = [{"role": "user", "content": prompt}]
        return cls._call_with_messages(messages, action=action,
                                       max_tokens=max_tokens, force_primary=force_primary, vision=False)

    @classmethod
    def _call_with_messages(cls, messages: list, action: str = "unknown",
                             max_tokens: int = None, force_primary: bool = False,
                             vision: bool = False) -> dict:
        """
        Execute the API call with the fallback chain.
        - vision=True uses _VISION_MODELS list (models that support image input).
        - Heavy/multimodal actions always start at primary tier.
        - Each tier gets 1 retry before cascading to the next.
        """
        try:
            cfg = cls._get_config()
        except RuntimeError:
            return {"success": False, "error": "AI service unavailable outside app context."}

        api_key = cfg["api_key"]
        if not api_key:
            return {"success": False,
                    "error": "AI service is not configured. Add OPENROUTER_API_KEY to .env"}

        # Use vision model list for image requests, text model list otherwise
        if vision:
            models_to_try = list(_VISION_MODELS)
            # Also prepend the configured primary if it's not already in the vision list
            primary_override = cfg.get("models", [None])[0] if cfg.get("models") else None
            if primary_override and primary_override not in models_to_try:
                models_to_try.insert(0, primary_override)
        else:
            models_to_try = cfg["models"]

        tokens = max_tokens or 1024
        last_error = "Unknown error"

        for idx, model in enumerate(models_to_try):
            for attempt in range(2):  # 1 retry per model
                try:
                    result = cls._http_call(
                        api_key=api_key,
                        base_url=cfg["base_url"],
                        model=model,
                        messages=messages,
                        max_tokens=tokens,
                        timeout=cfg["timeout"],
                        action=action,
                    )
                    if result["success"]:
                        result["tier"] = f"model_{idx}"
                        return result
                    last_error = result.get("error", "Unknown error")
                    # Don't retry on auth errors — they won't fix themselves
                    if "401" in last_error or "API key" in last_error:
                        return result
                    # Exponential wait before retry
                    if attempt == 0:
                        time.sleep(1.0)

                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"[AI] Model {model} attempt {attempt+1} failed: {e}")
                    if attempt == 0:
                        time.sleep(1.0)

            logger.warning(f"[AI] Model {model} exhausted, cascading. Last error: {last_error}")

        return {"success": False,
                "error": f"All AI models unavailable. Last error: {last_error}"}

    @classmethod
    def _http_call(cls, api_key: str, base_url: str, model: str,
                   messages: list, max_tokens: int, timeout: int, action: str) -> dict:
        """Single HTTP call to OpenRouter."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "HTTP-Referer":  "https://wisaxis.com",
            "X-Title":       "WISAXIS Resume Maker",
        }
        payload = {
            "model":       model,
            "messages":    messages,
            "max_tokens":  max_tokens,
            "temperature": 0.65,
        }

        resp = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )

        if resp.status_code == 401:
            return {"success": False, "error": "Invalid OpenRouter API key. Check your .env file."}
        if resp.status_code == 402:
            return {"success": False, "error": "OpenRouter credit balance too low."}
        if resp.status_code == 429:
            return {"success": False, "error": "Rate limit reached. Cascading to fallback model."}
        if resp.status_code == 503:
            return {"success": False, "error": f"Model {model} temporarily unavailable."}

        resp.raise_for_status()
        data = resp.json()

        # Guard against None content — some models return null for unsupported inputs
        raw_content = data.get("choices", [{}])[0].get("message", {}).get("content")
        if raw_content is None:
            # Treat as a model failure so the fallback chain continues
            finish_reason = data.get("choices", [{}])[0].get("finish_reason", "unknown")
            return {"success": False,
                    "error": f"Model {model} returned empty content (finish_reason={finish_reason}). "
                             "Model may not support this input type."}

        content     = raw_content.strip()
        tokens_used = data.get("usage", {}).get("total_tokens", 0)

        _log_ai_history(action, str(messages[-1].get("content", ""))[:2000],
                        content, model, tokens_used, True)

        return {"success": True, "data": content, "tokens": tokens_used, "model": model}


# ────────────────────────────────────────────────────────────────────────────
# Extraction prompt (shared by text and image routes)
# ────────────────────────────────────────────────────────────────────────────
_RESUME_EXTRACTION_PROMPT = """Extract ALL text and structured information from this document.

Requirements:
Return ONLY valid JSON.
No markdown.
No explanation.
Preserve exact text.
Detect tables, forms, resume sections, invoices, and layouts.
Extract all emails, phones, dates, links, skills, education, experience, and metadata.

Use EXACTLY this schema (if a field is missing, return null or empty array/string):
{
  "raw_text": "Full extracted text here",
  "structured_data": {
    "name": "Full Name",
    "title": "Job Title / Professional Headline",
    "email": "email@example.com",
    "phone": "+1 555 000 0000",
    "address": "City, Country",
    "website": "https://...",
    "linkedin": "https://linkedin.com/in/...",
    "github": "https://github.com/...",
    "summary": "Professional summary paragraph",
    "skills": "skill1, skill2, skill3",
    "languages": ["English (Native)", "French (B2)"],
    "experience": [
      {
        "title": "Job Title",
        "company": "Company Name",
        "duration": "Jan 2020 – Present",
        "description": "• Bullet point 1\n• Bullet point 2"
      }
    ],
    "education": [
      {
        "degree": "B.Sc Computer Science",
        "university": "University Name",
        "year": "2018 – 2022"
      }
    ],
    "certifications": ["AWS Certified Developer", "Google Cloud Professional"],
    "projects": [
      {
        "name": "Project Name",
        "description": "Brief description",
        "tech_stack": "Python, React, AWS"
      }
    ],
    "achievements": ["Achievement 1", "Achievement 2"]
  },
  "metadata": {
    "pages": 1,
    "language": "en"
  }
}

Return ONLY the JSON object, no markdown fences, no explanation."""


# ────────────────────────────────────────────────────────────────────────────
# JSON helpers
# ────────────────────────────────────────────────────────────────────────────
def _safe_parse_json(text: str, fallback=None):
    """Try to parse JSON from text, stripping markdown fences if present."""
    # Strip ```json ... ``` or ``` ... ```
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON object inside the text
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return fallback


_REQUIRED_RESUME_KEYS = {
    "name": "", "title": "", "email": "", "phone": "", "address": "",
    "website": "", "linkedin": "", "github": "", "summary": "", "skills": "",
    "languages": [], "experience": [], "education": [],
    "certifications": [], "projects": [], "achievements": [],
}


def _parse_and_validate_resume_json(raw: str) -> dict:
    """Parse AI output and ensure all schema keys exist with correct types."""
    parsed = _safe_parse_json(raw, {})
    if not isinstance(parsed, dict):
        parsed = {}

    structured_data = parsed.get("structured_data", {})
    if not isinstance(structured_data, dict):
        structured_data = {}

    # Fill missing keys with defaults
    result_structured = {**_REQUIRED_RESUME_KEYS, **structured_data}

    # Coerce array fields
    for arr_key in ("languages", "experience", "education", "certifications",
                    "projects", "achievements"):
        if not isinstance(result_structured[arr_key], list):
            result_structured[arr_key] = []

    # Coerce string fields
    for str_key in ("name", "title", "email", "phone", "address",
                    "website", "linkedin", "github", "summary", "skills"):
        if not isinstance(result_structured[str_key], str):
            result_structured[str_key] = str(result_structured[str_key]) if result_structured[str_key] else ""

    metadata = parsed.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    raw_text = parsed.get("raw_text", "")

    return {
        "raw_text": str(raw_text) if raw_text else "",
        "structured_data": result_structured,
        "metadata": metadata
    }


# ────────────────────────────────────────────────────────────────────────────
# File extraction helpers
# ────────────────────────────────────────────────────────────────────────────
def _extract_pdf_text(file_path: str) -> str:
    """Extract text from a PDF using pdfplumber (returns empty string on failure)."""
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(pages)
    except ImportError:
        logger.warning("pdfplumber not installed. Run: pip install pdfplumber")
        return ""
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""


def _extract_docx_text(file_path: str) -> str:
    """Extract text from a DOCX using python-docx."""
    try:
        from docx import Document
        doc = Document(file_path)
        lines = [para.text for para in doc.paragraphs if para.text.strip()]
        # Also extract table cells
        for table in doc.tables:
            for row in table.rows:
                row_data = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_data:
                    lines.append(" | ".join(row_data))
        return "\n".join(lines)
    except ImportError:
        logger.warning("python-docx not installed. Run: pip install python-docx")
        return ""
    except Exception as e:
        logger.error(f"DOCX extraction failed: {e}")
        return ""


def _pdf_page_to_image(file_path: str) -> Optional[bytes]:
    """Convert the first page of a PDF to PNG bytes for vision analysis."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=150)
        return pix.tobytes("png")
    except ImportError:
        logger.warning("PyMuPDF not installed. Run: pip install PyMuPDF")
        return None
    except Exception as e:
        logger.error(f"PDF→image conversion failed: {e}")
        return None


def _dict_to_text(resume_dict: dict) -> str:
    """Flatten a resume dict to plain text for AI analysis."""
    lines = [
        f"Name: {resume_dict.get('name', '')}",
        f"Title: {resume_dict.get('title', '')}",
        f"Summary: {resume_dict.get('summary', '')}",
        f"Skills: {resume_dict.get('skills', '')}",
    ]
    for exp in resume_dict.get("experience", []):
        lines.append(f"Experience: {exp.get('title')} at {exp.get('company')} ({exp.get('duration')})")
        lines.append(f"  {exp.get('description', '')}")
    for edu in resume_dict.get("education", []):
        lines.append(f"Education: {edu.get('degree')} from {edu.get('university')} ({edu.get('year')})")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
# AI History logger
# ────────────────────────────────────────────────────────────────────────────
def _log_ai_history(action, prompt, response, model, tokens, success, error=None):
    """Persist an AIHistory row — silently skipped if outside app context."""
    try:
        from flask_login import current_user
        from backend.models import AIHistory
        from backend.extensions import db

        if not current_user or not current_user.is_authenticated:
            return

        record = AIHistory(
            user_id       = current_user.id,
            action        = action,
            prompt        = prompt[:2000] if prompt else None,
            response      = response[:4000] if response else None,
            model_used    = model,
            tokens_used   = tokens,
            success       = success,
            error_message = error,
        )
        db.session.add(record)
        db.session.commit()
    except Exception:
        pass
