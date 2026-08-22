"""
services/ai_service.py — OpenRouter AI Brain (v3 - Optimized Multimodal & Universal Extractor)
===========================================================================================
Architecture:
  • Multi-tier model fallback chain with top multimodal & reasoning models
  • Vision & Document intelligence: Google Gemini 2.0 Flash / Qwen 2.5 VL 72B / Llama 3.2 Vision
  • Universal Ingestion: Digital PDFs, Scanned PDFs, DOCX, DOC, RTF, ODT, TXT, MD, CSV, Images (JPG, PNG, WebP, BMP, TIFF)
  • Image Optimizer: EXIF orientation correction, DPI scaling, and high-fidelity base64 encoding
  • In-process LRU response cache (TTL-based)
  • Robust JSON repair & schema validation
  • All public methods return:
      { "success": True,  "data": <str|dict>, "tokens": int, "model": str, ... }
      { "success": False, "error": str }
"""

import base64
import hashlib
import io
import json
import logging
import os
import re
import time
from functools import lru_cache
from typing import Optional, Union

import requests
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# ── Model tiers ──────────────────────────────────────────────────────────────
# Default text-centric reasoning models (tried in order)
_MODELS = [
    "openrouter/free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemini-2.0-flash-001",
]

# Multimodal & Vision models for image/scanned document analysis (tried in order)
_VISION_MODELS = [
    "openrouter/free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "dots-studio/dots-3-note-preview:free",
    "google/gemini-2.0-flash-001",
]

# Actions that need multimodal or heavy reasoning → always use primary
_HEAVY_ACTIONS = {"extract_resume", "ats_score", "extract_from_file", "analyze_file", "extract_json"}
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
    Central AI brain. All AI features route through this class.
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
        return cls._call(prompt, action="generate_summary", max_tokens=600)

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
        return cls._call(prompt, action="generate_experience", max_tokens=700)

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
        result = cls._call(prompt, action="ats_score", max_tokens=800)
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
        return cls._call(prompt, action="cover_letter", max_tokens=1200)

    @classmethod
    def improve_grammar(cls, text: str) -> dict:
        """Polish grammar, tone, and professional wording."""
        prompt = (
            f"Improve the grammar, tone, and professional wording of the following "
            f"resume text. Preserve the original meaning. Return only the improved text.\n\n"
            f"Original text:\n{text}"
        )
        return cls._call(prompt, action="improve_grammar", max_tokens=1000)

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
        return cls._call(prompt, action="suggest_skills", max_tokens=300)

    # ── Universal File Analysis & JSON Extractor ──────────────────────────────

    @classmethod
    def analyze_file(cls, file_path: str, ext: str, file_bytes: bytes = None, mode: str = "auto") -> dict:
        """
        Universal document & image analyzer:
        Accepts: PDF, Word (DOCX/DOC), Rich Text (RTF/ODT), Text (TXT/MD/CSV/JSON),
                 and Images (JPG, PNG, WebP, BMP, TIFF, SVG).
        Returns a complete, validated structured JSON dictionary.
        """
        ext = ext.lower().strip(".")

        image_extensions = {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "svg"}
        text_extensions = {"txt", "md", "markdown", "csv", "tsv", "json", "html", "htm"}
        doc_extensions = {"doc", "docx", "rtf", "odt"}

        try:
            if ext in image_extensions:
                return cls._analyze_image(file_path, file_bytes, mode=mode)
            elif ext == "pdf":
                return cls._analyze_pdf(file_path, file_bytes, mode=mode)
            elif ext in ("docx", "doc"):
                return cls._analyze_docx(file_path, mode=mode)
            elif ext in ("rtf", "odt"):
                return cls._analyze_rich_text(file_path, mode=mode)
            elif ext in text_extensions:
                return cls._analyze_text_file(file_path, mode=mode)
            else:
                return {"success": False, "error": f"Unsupported file extension: .{ext}"}
        except Exception as e:
            logger.exception(f"File analysis failed for {file_path} (.{ext})")
            return {"success": False, "error": f"File analysis error: {str(e)}"}

    @classmethod
    def _analyze_image(cls, file_path: str, file_bytes: bytes = None, mode: str = "auto") -> dict:
        """Send image with auto-orientation and DPI scaling to a vision AI model."""
        try:
            if file_bytes is None:
                with open(file_path, "rb") as f:
                    file_bytes = f.read()

            optimized_bytes, mime = _optimize_image_bytes(file_bytes, file_path)
            b64 = base64.b64encode(optimized_bytes).decode("utf-8")

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _get_extraction_prompt(mode)},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                }
            ]
            result = cls._call_with_messages(
                messages, action="analyze_file", max_tokens=4096,
                force_primary=True, vision=True
            )
            if result["success"]:
                result["data"] = _parse_and_validate_resume_json(result["data"])
            return result
        except Exception as e:
            logger.exception("Image analysis failed")
            return {"success": False, "error": f"Image analysis error: {str(e)}"}

    @classmethod
    def _analyze_pdf(cls, file_path: str, file_bytes: bytes = None, mode: str = "auto") -> dict:
        """
        Extract text from PDF using pdfplumber.
        If the PDF is a scanned image (or has <50 chars), render page 1 to an image and run vision OCR.
        """
        text = _extract_pdf_text(file_path)

        if text and len(text.strip()) >= 50:
            # Digital text PDF
            return cls._extract_from_text(text, source="pdf", mode=mode)
        else:
            # Scanned / Image-only PDF fallback to Vision
            logger.info("PDF appears scanned or empty. Attempting multimodal vision fallback.")
            img_bytes = _pdf_page_to_image(file_path)
            if img_bytes:
                return cls._analyze_image(file_path + ".png", img_bytes, mode=mode)
            else:
                return {
                    "success": False,
                    "error": "The uploaded PDF appears to be an empty or scanned document, and page rendering failed. Please upload a clear text PDF or an image (JPG/PNG)."
                }

    @classmethod
    def _analyze_docx(cls, file_path: str, mode: str = "auto") -> dict:
        """Extract paragraphs, headings, and table cells from DOCX/DOC."""
        text = _extract_docx_text(file_path)
        if not text or len(text.strip()) < 20:
            # Try plain binary text reader for legacy doc
            text = _extract_fallback_text(file_path)

        if not text or len(text.strip()) < 10:
            return {"success": False, "error": "Could not extract readable text from this Word document."}

        return cls._extract_from_text(text, source="docx", mode=mode)

    @classmethod
    def _analyze_rich_text(cls, file_path: str, mode: str = "auto") -> dict:
        """Extract text from RTF/ODT files."""
        text = _extract_fallback_text(file_path)
        if not text or len(text.strip()) < 10:
            return {"success": False, "error": "Could not extract readable text from this document."}
        return cls._extract_from_text(text, source="document", mode=mode)

    @classmethod
    def _analyze_text_file(cls, file_path: str, mode: str = "auto") -> dict:
        """Extract text from TXT, MD, CSV, or JSON."""
        text = _extract_plain_text(file_path)
        if not text or len(text.strip()) < 5:
            return {"success": False, "error": "File is empty or contains no readable text."}
        return cls._extract_from_text(text, source="text", mode=mode)

    @classmethod
    def _extract_from_text(cls, text: str, source: str, mode: str = "auto") -> dict:
        """Run the structured extraction prompt over plain extracted text."""
        truncated = text[:25000]  # Support large text within safe token window
        prompt = f"{_get_extraction_prompt(mode)}\n\n--- DOCUMENT CONTENT ---\n{truncated}"
        result = cls._call(prompt, action="extract_from_file", max_tokens=4096)
        if result["success"]:
            result["data"] = _parse_and_validate_resume_json(result["data"], raw_fallback=text)
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

        # Text models
        models = list(_MODELS)
        primary_override = cfg.get("AI_MODEL_PRIMARY")
        if primary_override and primary_override not in models:
            models.insert(0, primary_override)

        # Vision models
        vision_models = list(_VISION_MODELS)
        vision_env = cfg.get("AI_MODEL_VISION", "")
        if vision_env:
            custom_vision = [m.strip() for m in vision_env.split(",") if m.strip()]
            for cv in reversed(custom_vision):
                if cv not in vision_models:
                    vision_models.insert(0, cv)

        return {
            "api_key":       cfg.get("OPENROUTER_API_KEY", ""),
            "base_url":      cfg.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            "timeout":       int(cfg.get("AI_REQUEST_TIMEOUT", 45)),
            "models":        models,
            "vision_models": vision_models,
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
        Execute the API call with the resilient fallback chain.
        - vision=True uses vision_models list (Gemini 2.0 Flash / Qwen 2.5 VL / Llama 3.2 Vision / Pixtral).
        - Each model gets 1 retry before cascading to the next.
        """
        try:
            cfg = cls._get_config()
        except RuntimeError:
            return {"success": False, "error": "AI service unavailable outside app context."}

        api_key = cfg["api_key"]
        if not api_key:
            return {"success": False,
                    "error": "AI service is not configured. Please set OPENROUTER_API_KEY in your environment (.env)."}

        # Select model list based on vision requirement
        models_to_try = cfg["vision_models"] if vision else cfg["models"]
        tokens = max_tokens or 2048
        last_error = "Unknown error"

        for idx, model in enumerate(models_to_try):
            for attempt in range(2):  # Max 1 retry for transient issues
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

                    # Global auth / billing failures -> stop cascading immediately
                    if result.get("status") in (401, 402):
                        return result

                    # Non-retryable model error (404 Not Found, 400 Bad Request, etc.) -> cascade immediately without delay
                    if result.get("non_retryable"):
                        logger.warning(f"[AI] Model {model} returned non-retryable error ({result.get('status')}), skipping to next fallback.")
                        break

                    if attempt == 0:
                        time.sleep(0.5)

                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"[AI] Model {model} attempt {attempt+1} failed: {e}")
                    if "404" in str(e) or "400" in str(e) or "401" in str(e) or "403" in str(e):
                        break
                    if attempt == 0:
                        time.sleep(0.5)

            logger.warning(f"[AI] Model {model} exhausted, cascading to next model. Last error: {last_error}")

        return {"success": False,
                "error": f"All AI models unavailable. Last error: {last_error}"}

    @classmethod
    def _http_call(cls, api_key: str, base_url: str, model: str,
                   messages: list, max_tokens: int, timeout: int, action: str) -> dict:
        """Single HTTP call to OpenRouter with clean status code handling."""
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
            "temperature": 0.2,  # Lower temperature for accurate structured extraction
        }

        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.exceptions.Timeout:
            return {"success": False, "error": f"Model {model} timed out after {timeout}s", "status": 408, "non_retryable": False}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"Network error connecting to {model}: {e}", "status": 500, "non_retryable": False}

        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                return {"success": False, "error": "Invalid JSON response from AI provider", "non_retryable": True}

            raw_content = data.get("choices", [{}])[0].get("message", {}).get("content")
            if raw_content is None:
                finish_reason = data.get("choices", [{}])[0].get("finish_reason", "unknown")
                return {"success": False,
                        "error": f"Model {model} returned empty content (finish_reason={finish_reason})."}

            content     = raw_content.strip()
            tokens_used = data.get("usage", {}).get("total_tokens", 0)

            _log_ai_history(action, str(messages[-1].get("content", ""))[:2000],
                            content, model, tokens_used, True)

            return {"success": True, "data": content, "tokens": tokens_used, "model": model}

        # Specific OpenRouter error handling
        if resp.status_code == 401:
            return {"success": False, "error": "Invalid OpenRouter API key. Check your .env file.", "status": 401, "non_retryable": True}
        if resp.status_code == 402:
            return {"success": False, "error": "OpenRouter credit balance too low.", "status": 402, "non_retryable": True}
        if resp.status_code == 404:
            return {"success": False, "error": f"Model {model} not found on OpenRouter (404).", "status": 404, "non_retryable": True}
        if resp.status_code == 400:
            return {"success": False, "error": f"Model {model} bad request (400): {resp.text[:120]}", "status": 400, "non_retryable": True}
        if resp.status_code == 429:
            return {"success": False, "error": f"Rate limit reached for {model} (429).", "status": 429, "non_retryable": False}
        if resp.status_code == 503:
            return {"success": False, "error": f"Model {model} temporarily unavailable (503).", "status": 503, "non_retryable": False}

        return {"success": False, "error": f"Model {model} HTTP {resp.status_code}: {resp.text[:120]}", "status": resp.status_code, "non_retryable": resp.status_code < 500}


# ────────────────────────────────────────────────────────────────────────────
# Dynamic High-Fidelity Extraction Prompt (4-Tier Production Schema)
# ────────────────────────────────────────────────────────────────────────────
def _get_extraction_prompt(mode: str = "auto") -> str:
    return """You are an elite Multimodal Document Intelligence & ATS Resume AI.
Analyze the provided document with 100% precision and extract every detail into the comprehensive 4-tier structured JSON schema below.

CRITICAL EXTRACTION RULES:
1. Return ONLY pure, valid JSON. No markdown code blocks, no preamble, no trailing text.
2. Separate pure factual data (candidate) from AI evaluation (analysis) and document metadata (document).
3. If a field or section is not present in the document, use null or empty array [] / empty string "". Never fabricate or hallucinate details.
4. If work experience or projects contain bullet points, extract them into both 'description' (combined text) and 'responsibilities' / 'achievements' (array of strings).
5. Categorize skills into technical, soft, programming languages, frameworks, databases, tools, cloud/devops.
6. Calculate accurate analysis scores (0-100) for ats_score, overall_quality_score, and completeness_score based on standard resume best practices.

REQUIRED JSON SCHEMA:
{
  "document": {
    "type": "resume",
    "language": "en",
    "source": {
      "filename": "",
      "mime_type": "",
      "page_count": 1
    }
  },

  "candidate": {
    "personal_information": {
      "full_name": "",
      "job_title": "",
      "email": "",
      "phone": "",
      "location": {
        "city": "",
        "state": "",
        "country": "",
        "postal_code": ""
      },
      "website": "",
      "linkedin": "",
      "github": "",
      "portfolio": "",
      "other_links": []
    },

    "professional_summary": "",
    "career_objective": "",

    "work_experience": [
      {
        "job_title": "",
        "company_name": "",
        "employment_type": "",
        "location": "",
        "start_date": "",
        "end_date": "",
        "is_current": false,
        "description": "",
        "responsibilities": [],
        "achievements": [],
        "technologies": []
      }
    ],

    "education": [
      {
        "degree": "",
        "field_of_study": "",
        "institution": "",
        "location": "",
        "start_date": "",
        "end_date": "",
        "is_current": false,
        "grade": "",
        "gpa": "",
        "percentage": "",
        "description": []
      }
    ],

    "skills": {
      "technical_skills": [],
      "soft_skills": [],
      "programming_languages": [],
      "frameworks_and_libraries": [],
      "databases": [],
      "tools_and_technologies": [],
      "cloud_and_devops": [],
      "other_skills": []
    },

    "projects": [
      {
        "project_name": "",
        "description": "",
        "role": "",
        "start_date": "",
        "end_date": "",
        "project_url": "",
        "github_url": "",
        "technologies": [],
        "responsibilities": [],
        "achievements": []
      }
    ],

    "certifications": [
      {
        "name": "",
        "issuing_organization": "",
        "issue_date": "",
        "expiration_date": "",
        "credential_id": "",
        "credential_url": ""
      }
    ],

    "achievements": [
      {
        "title": "",
        "description": "",
        "date": "",
        "organization": ""
      }
    ],

    "awards": [
      {
        "name": "",
        "issuer": "",
        "date": "",
        "description": ""
      }
    ],

    "languages": [
      {
        "language": "",
        "proficiency": ""
      }
    ],

    "publications": [
      {
        "title": "",
        "publisher": "",
        "publication_date": "",
        "url": "",
        "description": ""
      }
    ],

    "volunteer_experience": [
      {
        "role": "",
        "organization": "",
        "location": "",
        "start_date": "",
        "end_date": "",
        "description": []
      }
    ],

    "internships": [
      {
        "job_title": "",
        "company_name": "",
        "location": "",
        "start_date": "",
        "end_date": "",
        "description": "",
        "responsibilities": [],
        "technologies": []
      }
    ],

    "interests": [],

    "references": [
      {
        "name": "",
        "job_title": "",
        "company": "",
        "email": "",
        "phone": "",
        "relationship": ""
      }
    ],

    "additional_information": {
      "availability": "",
      "work_authorization": "",
      "visa_status": "",
      "willing_to_relocate": false,
      "driving_license": "",
      "notice_period": ""
    }
  },

  "analysis": {
    "overall_quality_score": 88,
    "ats_score": 85,
    "completeness_score": 90,
    "skills_detected": [],
    "missing_sections": [],
    "missing_information": [],
    "potential_errors": [],
    "recommendations": []
  },

  "extraction": {
    "confidence": 0.98,
    "field_confidence": {},
    "uncertain_fields": [],
    "source_references": []
  }
}

Return ONLY this JSON structure now."""


# ────────────────────────────────────────────────────────────────────────────
# Image Pre-processor & Optimizer
# ────────────────────────────────────────────────────────────────────────────
def _optimize_image_bytes(file_bytes: bytes, filename: str) -> tuple[bytes, str]:
    """
    Auto-orient EXIF, resize massive images to max 2048px (ideal for high-accuracy OCR),
    and convert to optimized JPEG or PNG.
    """
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img = ImageOps.exif_transpose(img)

        # Cap max dimension to 2048px while preserving aspect ratio
        max_dim = 2048
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / float(max(w, h))
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        out_io = io.BytesIO()
        ext = filename.split(".")[-1].lower() if filename else "png"
        if ext in ("jpg", "jpeg"):
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(out_io, format="JPEG", quality=90, optimize=True)
            return out_io.getvalue(), "image/jpeg"
        else:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            img.save(out_io, format="PNG", optimize=True)
            return out_io.getvalue(), "image/png"
    except Exception as e:
        logger.warning(f"Pillow image optimization skipped ({e}), using raw bytes.")
        mime = "image/jpeg" if "jpg" in filename or "jpeg" in filename else "image/png"
        return file_bytes, mime


# ────────────────────────────────────────────────────────────────────────────
# JSON Parser & 4-Tier Schema Normalizer
# ────────────────────────────────────────────────────────────────────────────
def _safe_parse_json(text: str, fallback=None):
    """Robust JSON parser that cleans markdown fences and recovers JSON objects."""
    if not text:
        return fallback

    # Strip markdown ```json ... ``` or ``` ... ```
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Regex search for the outermost {...} block
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = cleaned[start:end+1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # Basic cleanup of trailing commas before closing braces/brackets
                candidate_fixed = re.sub(r",\s*([\]}])", r"\1", candidate)
                try:
                    return json.loads(candidate_fixed)
                except json.JSONDecodeError:
                    pass
    return fallback


def _parse_and_validate_resume_json(raw: str, raw_fallback: str = "") -> dict:
    """
    Validate, unwrap, and normalize extracted JSON into the 4-Tier Production Schema:
    - document: file & language metadata
    - candidate: complete personal info, experience, education, skills, projects, etc.
    - analysis: ats_score, quality_score, recommendations, missing sections
    - extraction: confidence and field metrics
    - structured_data: backward-compatible flat object
    - raw_text: verbatim text
    """
    parsed = _safe_parse_json(raw, {})
    if not isinstance(parsed, dict):
        parsed = {}

    # Unwrap root wrappers if present (e.g. { "resume": { ... } })
    if "resume" in parsed and isinstance(parsed["resume"], dict):
        unwrapped = parsed["resume"]
    else:
        unwrapped = parsed

    # ── 1. Document Metadata ──────────────────────────────────────────────────
    raw_doc = unwrapped.get("document", {}) if isinstance(unwrapped.get("document"), dict) else {}
    doc = {
        "type": str(raw_doc.get("type") or "resume"),
        "language": str(raw_doc.get("language") or "en"),
        "source": {
            "filename": str(raw_doc.get("source", {}).get("filename") if isinstance(raw_doc.get("source"), dict) else ""),
            "mime_type": str(raw_doc.get("source", {}).get("mime_type") if isinstance(raw_doc.get("source"), dict) else ""),
            "page_count": int(raw_doc.get("source", {}).get("page_count") if isinstance(raw_doc.get("source"), dict) and str(raw_doc.get("source", {}).get("page_count", "")).isdigit() else 1)
        }
    }

    # ── 2. Candidate Section ──────────────────────────────────────────────────
    # Could be inside unwrapped['candidate'] or top-level
    raw_cand = unwrapped.get("candidate", {}) if isinstance(unwrapped.get("candidate"), dict) else unwrapped
    if "structured_data" in unwrapped and isinstance(unwrapped["structured_data"], dict):
        raw_sd = unwrapped["structured_data"]
    else:
        raw_sd = raw_cand

    # Personal Information & Contact
    raw_pi = raw_cand.get("personal_information", {}) if isinstance(raw_cand.get("personal_information"), dict) else raw_sd.get("personal_info", {})
    if not isinstance(raw_pi, dict):
        raw_pi = {}

    raw_loc = raw_pi.get("location", {}) if isinstance(raw_pi.get("location"), dict) else {}
    address_fallback = str(raw_pi.get("address") or raw_sd.get("address") or "")

    personal_info = {
        "full_name": str(raw_pi.get("full_name") or raw_pi.get("name") or raw_sd.get("name") or ""),
        "job_title": str(raw_pi.get("job_title") or raw_pi.get("title") or raw_sd.get("title") or ""),
        "email": str(raw_pi.get("email") or raw_sd.get("email") or ""),
        "phone": str(raw_pi.get("phone") or raw_sd.get("phone") or ""),
        "location": {
            "city": str(raw_loc.get("city") or (address_fallback.split(",")[0].strip() if address_fallback else "")),
            "state": str(raw_loc.get("state") or ""),
            "country": str(raw_loc.get("country") or (address_fallback.split(",")[-1].strip() if "," in address_fallback else "")),
            "postal_code": str(raw_loc.get("postal_code") or "")
        },
        "website": str(raw_pi.get("website") or raw_sd.get("website") or ""),
        "linkedin": str(raw_pi.get("linkedin") or raw_sd.get("linkedin") or ""),
        "github": str(raw_pi.get("github") or raw_sd.get("github") or ""),
        "portfolio": str(raw_pi.get("portfolio") or raw_sd.get("portfolio") or ""),
        "other_links": raw_pi.get("other_links") if isinstance(raw_pi.get("other_links"), list) else []
    }

    # Summary & Objective
    summary = str(raw_cand.get("professional_summary") or raw_cand.get("summary") or raw_sd.get("summary") or "")
    objective = str(raw_cand.get("career_objective") or raw_sd.get("career_objective") or "")

    # Work Experience
    raw_exp = raw_cand.get("work_experience") or raw_cand.get("experience") or raw_sd.get("experience") or []
    if not isinstance(raw_exp, list):
        raw_exp = [raw_exp] if raw_exp else []

    norm_exp = []
    for item in raw_exp:
        if isinstance(item, dict):
            dur = str(item.get("duration") or "")
            if not dur and (item.get("start_date") or item.get("end_date")):
                dur = f"{item.get('start_date', '')} – {item.get('end_date', 'Present')}".strip(" –")

            desc = str(item.get("description") or "")
            resp_list = item.get("responsibilities") if isinstance(item.get("responsibilities"), list) else []
            if not desc and resp_list:
                desc = "\n".join(f"• {r}" for r in resp_list)

            norm_exp.append({
                "job_title": str(item.get("job_title") or item.get("title") or ""),
                "company_name": str(item.get("company_name") or item.get("company") or item.get("organization") or ""),
                "employment_type": str(item.get("employment_type") or ""),
                "location": str(item.get("location") or ""),
                "start_date": str(item.get("start_date") or (dur.split("–")[0].strip() if "–" in dur else "")),
                "end_date": str(item.get("end_date") or (dur.split("–")[1].strip() if "–" in dur else "")),
                "is_current": bool(item.get("is_current") or "present" in dur.lower() or "current" in dur.lower()),
                "description": desc,
                "responsibilities": resp_list,
                "achievements": item.get("achievements") if isinstance(item.get("achievements"), list) else [],
                "technologies": item.get("technologies") if isinstance(item.get("technologies"), list) else []
            })
        elif isinstance(item, str):
            norm_exp.append({
                "job_title": item, "company_name": "", "employment_type": "", "location": "",
                "start_date": "", "end_date": "", "is_current": False, "description": "",
                "responsibilities": [], "achievements": [], "technologies": []
            })

    # Education
    raw_edu = raw_cand.get("education") or raw_sd.get("education") or []
    if not isinstance(raw_edu, list):
        raw_edu = [raw_edu] if raw_edu else []

    norm_edu = []
    for item in raw_edu:
        if isinstance(item, dict):
            yr = str(item.get("year") or item.get("duration") or item.get("graduation_year") or "")
            norm_edu.append({
                "degree": str(item.get("degree") or item.get("qualification") or ""),
                "field_of_study": str(item.get("field_of_study") or item.get("major") or ""),
                "institution": str(item.get("institution") or item.get("university") or item.get("school") or ""),
                "location": str(item.get("location") or ""),
                "start_date": str(item.get("start_date") or (yr.split("–")[0].strip() if "–" in yr else "")),
                "end_date": str(item.get("end_date") or (yr.split("–")[1].strip() if "–" in yr else yr)),
                "is_current": bool(item.get("is_current", False)),
                "grade": str(item.get("grade") or item.get("honors") or ""),
                "gpa": str(item.get("gpa") or ""),
                "percentage": str(item.get("percentage") or ""),
                "description": item.get("description") if isinstance(item.get("description"), list) else []
            })
        elif isinstance(item, str):
            norm_edu.append({
                "degree": item, "field_of_study": "", "institution": "", "location": "",
                "start_date": "", "end_date": "", "is_current": False, "grade": "",
                "gpa": "", "percentage": "", "description": []
            })

    # Skills categorization
    raw_skills = raw_cand.get("skills") or raw_sd.get("skills") or {}
    if isinstance(raw_skills, dict):
        skills_obj = {
            "technical_skills": raw_skills.get("technical_skills") if isinstance(raw_skills.get("technical_skills"), list) else [],
            "soft_skills": raw_skills.get("soft_skills") if isinstance(raw_skills.get("soft_skills"), list) else [],
            "programming_languages": raw_skills.get("programming_languages") if isinstance(raw_skills.get("programming_languages"), list) else [],
            "frameworks_and_libraries": raw_skills.get("frameworks_and_libraries") if isinstance(raw_skills.get("frameworks_and_libraries"), list) else [],
            "databases": raw_skills.get("databases") if isinstance(raw_skills.get("databases"), list) else [],
            "tools_and_technologies": raw_skills.get("tools_and_technologies") if isinstance(raw_skills.get("tools_and_technologies"), list) else [],
            "cloud_and_devops": raw_skills.get("cloud_and_devops") if isinstance(raw_skills.get("cloud_and_devops"), list) else [],
            "other_skills": raw_skills.get("other_skills") if isinstance(raw_skills.get("other_skills"), list) else []
        }
    elif isinstance(raw_skills, list):
        skills_obj = {
            "technical_skills": [str(s) for s in raw_skills],
            "soft_skills": [],
            "programming_languages": [],
            "frameworks_and_libraries": [],
            "databases": [],
            "tools_and_technologies": [],
            "cloud_and_devops": [],
            "other_skills": []
        }
    elif isinstance(raw_skills, str):
        parsed_s = [s.strip() for s in raw_skills.split(",") if s.strip()]
        skills_obj = {
            "technical_skills": parsed_s,
            "soft_skills": [],
            "programming_languages": [],
            "frameworks_and_libraries": [],
            "databases": [],
            "tools_and_technologies": [],
            "cloud_and_devops": [],
            "other_skills": []
        }
    else:
        skills_obj = {
            "technical_skills": [], "soft_skills": [], "programming_languages": [],
            "frameworks_and_libraries": [], "databases": [], "tools_and_technologies": [],
            "cloud_and_devops": [], "other_skills": []
        }

    # Projects
    raw_proj = raw_cand.get("projects") or raw_sd.get("projects") or []
    norm_proj = []
    if isinstance(raw_proj, list):
        for p in raw_proj:
            if isinstance(p, dict):
                norm_proj.append({
                    "project_name": str(p.get("project_name") or p.get("name") or p.get("title") or ""),
                    "description": str(p.get("description") or ""),
                    "role": str(p.get("role") or ""),
                    "start_date": str(p.get("start_date") or ""),
                    "end_date": str(p.get("end_date") or ""),
                    "project_url": str(p.get("project_url") or p.get("link") or p.get("url") or ""),
                    "github_url": str(p.get("github_url") or ""),
                    "technologies": p.get("technologies") if isinstance(p.get("technologies"), list) else ([t.strip() for t in str(p.get("tech_stack", "")).split(",") if t.strip()] if p.get("tech_stack") else []),
                    "responsibilities": p.get("responsibilities") if isinstance(p.get("responsibilities"), list) else [],
                    "achievements": p.get("achievements") if isinstance(p.get("achievements"), list) else []
                })

    # Certifications
    raw_certs = raw_cand.get("certifications") or raw_sd.get("certifications") or []
    norm_certs = []
    if isinstance(raw_certs, list):
        for c in raw_certs:
            if isinstance(c, dict):
                norm_certs.append({
                    "name": str(c.get("name") or c.get("title") or ""),
                    "issuing_organization": str(c.get("issuing_organization") or c.get("issuer") or c.get("organization") or ""),
                    "issue_date": str(c.get("issue_date") or c.get("date") or c.get("year") or ""),
                    "expiration_date": str(c.get("expiration_date") or ""),
                    "credential_id": str(c.get("credential_id") or ""),
                    "credential_url": str(c.get("credential_url") or "")
                })
            elif isinstance(c, str):
                norm_certs.append({
                    "name": c, "issuing_organization": "", "issue_date": "",
                    "expiration_date": "", "credential_id": "", "credential_url": ""
                })

    # Achievements & Awards
    raw_ach = raw_cand.get("achievements") or raw_sd.get("achievements") or []
    norm_ach = []
    if isinstance(raw_ach, list):
        for a in raw_ach:
            if isinstance(a, dict):
                norm_ach.append({
                    "title": str(a.get("title") or ""),
                    "description": str(a.get("description") or ""),
                    "date": str(a.get("date") or ""),
                    "organization": str(a.get("organization") or "")
                })
            elif isinstance(a, str):
                norm_ach.append({"title": a, "description": "", "date": "", "organization": ""})

    raw_awards = raw_cand.get("awards") or raw_sd.get("awards") or []
    norm_awards = []
    if isinstance(raw_awards, list):
        for aw in raw_awards:
            if isinstance(aw, dict):
                norm_awards.append({
                    "name": str(aw.get("name") or aw.get("title") or ""),
                    "issuer": str(aw.get("issuer") or aw.get("organization") or ""),
                    "date": str(aw.get("date") or ""),
                    "description": str(aw.get("description") or "")
                })
            elif isinstance(aw, str):
                norm_awards.append({"name": aw, "issuer": "", "date": "", "description": ""})

    # Languages
    raw_langs = raw_cand.get("languages") or raw_sd.get("languages") or []
    norm_langs = []
    if isinstance(raw_langs, list):
        for l in raw_langs:
            if isinstance(l, dict):
                norm_langs.append({
                    "language": str(l.get("language") or l.get("name") or ""),
                    "proficiency": str(l.get("proficiency") or l.get("level") or "")
                })
            elif isinstance(l, str):
                parts = l.split("(")
                lang_name = parts[0].strip()
                prof = parts[1].replace(")", "").strip() if len(parts) > 1 else ""
                norm_langs.append({"language": lang_name, "proficiency": prof})

    # Additional & Optional Sections
    pubs = raw_cand.get("publications") if isinstance(raw_cand.get("publications"), list) else []
    vol = raw_cand.get("volunteer_experience") or raw_cand.get("volunteer") or []
    if not isinstance(vol, list): vol = []
    intern = raw_cand.get("internships") if isinstance(raw_cand.get("internships"), list) else []
    interests = raw_cand.get("interests") if isinstance(raw_cand.get("interests"), list) else []
    refs = raw_cand.get("references") if isinstance(raw_cand.get("references"), list) else []
    add_info = raw_cand.get("additional_information", {}) if isinstance(raw_cand.get("additional_information"), dict) else {}

    candidate = {
        "personal_information": personal_info,
        "professional_summary": summary,
        "career_objective": objective,
        "work_experience": norm_exp,
        "education": norm_edu,
        "skills": skills_obj,
        "projects": norm_proj,
        "certifications": norm_certs,
        "achievements": norm_ach,
        "awards": norm_awards,
        "languages": norm_langs,
        "publications": pubs,
        "volunteer_experience": vol,
        "internships": intern,
        "interests": interests,
        "references": refs,
        "additional_information": add_info
    }

    # ── 3. AI Analysis & Scoring ──────────────────────────────────────────────
    raw_analysis = unwrapped.get("analysis", {}) if isinstance(unwrapped.get("analysis"), dict) else {}

    # Calculate intelligent default scores if not provided by model
    completeness = 40
    if personal_info["full_name"]: completeness += 10
    if personal_info["email"] and personal_info["phone"]: completeness += 10
    if summary: completeness += 10
    if norm_exp: completeness += 15
    if norm_edu: completeness += 10
    if any(skills_obj.values()): completeness += 5
    completeness = min(100, completeness)

    ats_score = int(raw_analysis.get("ats_score") or (completeness - 5))
    quality_score = int(raw_analysis.get("overall_quality_score") or completeness)

    all_detected_skills = []
    for k, v in skills_obj.items():
        if isinstance(v, list):
            all_detected_skills.extend(v)

    analysis = {
        "overall_quality_score": quality_score,
        "ats_score": ats_score,
        "completeness_score": int(raw_analysis.get("completeness_score") or completeness),
        "skills_detected": raw_analysis.get("skills_detected") or list(dict.fromkeys(all_detected_skills)),
        "missing_sections": raw_analysis.get("missing_sections") if isinstance(raw_analysis.get("missing_sections"), list) else [],
        "missing_information": raw_analysis.get("missing_information") if isinstance(raw_analysis.get("missing_information"), list) else [],
        "potential_errors": raw_analysis.get("potential_errors") if isinstance(raw_analysis.get("potential_errors"), list) else [],
        "recommendations": raw_analysis.get("recommendations") if isinstance(raw_analysis.get("recommendations"), list) else [
            "Quantify your work experience achievements with measurable metrics (%, $, numbers).",
            "Tailor skill keywords specifically to match target job descriptions."
        ]
    }

    # ── 4. Extraction Metrics ────────────────────────────────────────────────
    raw_ext = unwrapped.get("extraction", {}) if isinstance(unwrapped.get("extraction"), dict) else {}
    extraction = {
        "confidence": float(raw_ext.get("confidence") or 0.98),
        "field_confidence": raw_ext.get("field_confidence") if isinstance(raw_ext.get("field_confidence"), dict) else {
            "personal_information": 1.0,
            "work_experience": 0.98 if norm_exp else 0.5,
            "education": 0.99 if norm_edu else 0.5,
            "skills": 0.95 if any(skills_obj.values()) else 0.5
        },
        "uncertain_fields": raw_ext.get("uncertain_fields") if isinstance(raw_ext.get("uncertain_fields"), list) else [],
        "source_references": raw_ext.get("source_references") if isinstance(raw_ext.get("source_references"), list) else []
    }

    raw_text = parsed.get("raw_text") or raw_fallback or ""

    # ── Backward-compatible structured_data alias ────────────────────────────
    all_skills_flat = []
    for s_list in skills_obj.values():
        if isinstance(s_list, list):
            all_skills_flat.extend(s_list)

    structured_data_compat = {
        "name": personal_info["full_name"],
        "title": personal_info["job_title"],
        "email": personal_info["email"],
        "phone": personal_info["phone"],
        "address": f"{personal_info['location']['city']}, {personal_info['location']['country']}".strip(", "),
        "website": personal_info["website"],
        "linkedin": personal_info["linkedin"],
        "github": personal_info["github"],
        "portfolio": personal_info["portfolio"],
        "summary": summary,
        "skills": ", ".join(dict.fromkeys(all_skills_flat)),
        "languages": [f"{l['language']} ({l['proficiency']})".replace(" ()", "") for l in norm_langs],
        "experience": [
            {
                "title": e["job_title"],
                "company": e["company_name"],
                "duration": f"{e['start_date']} – {e['end_date']}".strip(" –"),
                "location": e["location"],
                "description": e["description"]
            }
            for e in norm_exp
        ],
        "education": [
            {
                "degree": f"{ed['degree']} {ed['field_of_study']}".strip(),
                "university": ed["institution"],
                "year": f"{ed['start_date']} – {ed['end_date']}".strip(" –"),
                "gpa": ed["gpa"]
            }
            for ed in norm_edu
        ],
        "certifications": [c["name"] for c in norm_certs],
        "projects": [
            {
                "name": p["project_name"],
                "description": p["description"],
                "tech_stack": ", ".join(p["technologies"]),
                "link": p["project_url"] or p["github_url"]
            }
            for p in norm_proj
        ],
        "achievements": [a["title"] for a in norm_ach],
        "custom_sections": []
    }

    return {
        "document": doc,
        "candidate": candidate,
        "analysis": analysis,
        "extraction": extraction,
        "structured_data": structured_data_compat,
        "raw_text": str(raw_text)
    }


# ────────────────────────────────────────────────────────────────────────────
# Universal File Extraction Parsers
# ────────────────────────────────────────────────────────────────────────────
def _extract_pdf_text(file_path: str) -> str:
    """Extract text from a digital PDF using pdfplumber."""
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                pt = page.extract_text(layout=True) or page.extract_text() or ""
                if pt.strip():
                    text_parts.append(pt.strip())
                # Also extract table text
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        row_cells = [str(c).strip() for c in row if c and str(c).strip()]
                        if row_cells:
                            text_parts.append(" | ".join(row_cells))
        return "\n\n".join(text_parts)
    except Exception as e:
        logger.error(f"PDF extraction with pdfplumber failed: {e}")
        return ""


def _pdf_page_to_image(file_path: str) -> Optional[bytes]:
    """Convert page 1 of a PDF to high-resolution PNG bytes for vision analysis."""
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            if pdf.pages:
                # Render first page at 150 DPI
                page_img = pdf.pages[0].to_image(resolution=150).original
                buf = io.BytesIO()
                page_img.save(buf, format="PNG")
                return buf.getvalue()
    except Exception as e:
        logger.warning(f"pdfplumber page rendering failed: {e}")

    try:
        import fitz  # PyMuPDF fallback if available
        doc = fitz.open(file_path)
        if len(doc) > 0:
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=150)
            return pix.tobytes("png")
    except Exception:
        pass

    return None


def _extract_docx_text(file_path: str) -> str:
    """Extract text and tables from Word (.docx)."""
    try:
        from docx import Document
        doc = Document(file_path)
        lines = []

        # Headers & Footers
        for section in doc.sections:
            for hp in section.header.paragraphs:
                if hp.text.strip(): lines.append(hp.text.strip())

        # Body paragraphs
        for para in doc.paragraphs:
            if para.text.strip():
                lines.append(para.text.strip())

        # Tables
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    lines.append(" | ".join(cells))

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"DOCX extraction failed: {e}")
        return ""


def _extract_plain_text(file_path: str) -> str:
    """Extract text from TXT, MD, CSV, JSON with multi-encoding fallback."""
    encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252", "utf-16"]
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.warning(f"Error reading text file with {enc}: {e}")
    return ""


def _extract_fallback_text(file_path: str) -> str:
    """Extract readable strings from binary/unsupported formats (.doc, .rtf, .odt)."""
    try:
        with open(file_path, "rb") as f:
            raw_bytes = f.read()

        # Try plain text decode
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                decoded = raw_bytes.decode(enc)
                # Remove RTF control sequences if present
                if "{\\rtf" in decoded:
                    clean = re.sub(r"\\[a-zA-Z0-9\-]+ ?", " ", decoded)
                    clean = re.sub(r"[{}\\]", " ", clean)
                    return re.sub(r"\s+", " ", clean).strip()
                return decoded
            except UnicodeDecodeError:
                continue

        # Printable ASCII / UTF-8 string regex extractor
        strings = re.findall(rb"[\x20-\x7E\t\n\r]{4,}", raw_bytes)
        return "\n".join(s.decode("latin-1", errors="ignore") for s in strings)
    except Exception as e:
        logger.error(f"Fallback text extraction failed: {e}")
        return ""


def _dict_to_text(resume_dict: dict) -> str:
    """Flatten a resume dict to plain text for AI analysis."""
    lines = [
        f"Name: {resume_dict.get('name', '')}",
        f"Title: {resume_dict.get('title', '')}",
        f"Summary: {resume_dict.get('summary', '')}",
        f"Skills: {resume_dict.get('skills', '')}",
    ]
    for exp in resume_dict.get("experience", []):
        if isinstance(exp, dict):
            lines.append(f"Experience: {exp.get('title')} at {exp.get('company')} ({exp.get('duration')})")
            lines.append(f"  {exp.get('description', '')}")
    for edu in resume_dict.get("education", []):
        if isinstance(edu, dict):
            lines.append(f"Education: {edu.get('degree')} from {edu.get('university')} ({edu.get('year')})")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
# AI History logger
# ────────────────────────────────────────────────────────────────────────────
def _log_ai_history(action, prompt, response, model, tokens, success, error=None, resume_id=None):
    """Persist an AIHistory row — silently skipped if outside app context."""
    try:
        from flask import g, has_app_context
        if not has_app_context():
            return

        from backend.models import AIHistory
        from backend.extensions import db

        user_id = None
        if hasattr(g, "current_user") and g.current_user:
            user_id = getattr(g.current_user, "id", None)

        record = AIHistory(
            user_id       = user_id,
            resume_id     = resume_id,
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

