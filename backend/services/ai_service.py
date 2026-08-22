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
# Dynamic High-Fidelity Extraction Prompt
# ────────────────────────────────────────────────────────────────────────────
def _get_extraction_prompt(mode: str = "auto") -> str:
    return """You are a world-class Multimodal Document & Resume Intelligence AI.
Analyze ALL visual, structural, and textual information from this document with 100% accuracy.

CRITICAL INSTRUCTIONS:
1. Return ONLY valid, well-formed JSON. No markdown codeblock wrapper, no preamble, no trailing commentary.
2. Extract ALL details: contact info, full work experience, bullet points, education, technical and soft skills, projects, certifications, languages, awards, and any other sections.
3. If a section is tabular or multi-column, preserve the exact column relationships.
4. If a field is not present, use null or an empty array/string. Do NOT invent or hallucinate data.

You MUST follow this exact JSON schema:
{
  "raw_text": "Full extracted plain text of the entire document verbatim...",
  "structured_data": {
    "name": "Full Name / Candidate Name",
    "title": "Professional Title / Headline / Target Role",
    "email": "email@example.com",
    "phone": "+1 234 567 8900",
    "address": "City, State / Country",
    "website": "https://personalwebsite.com",
    "linkedin": "https://linkedin.com/in/username",
    "github": "https://github.com/username",
    "portfolio": "https://...",
    "summary": "Professional background summary or executive overview",
    "skills": "Skill 1, Skill 2, Skill 3, Python, JavaScript, Leadership",
    "languages": ["English (Native)", "Spanish (Fluent)"],
    "experience": [
      {
        "title": "Job Title / Role",
        "company": "Company Name / Organization",
        "duration": "Jan 2021 – Present",
        "location": "City, Country or Remote",
        "description": "• Built scalable microservices\n• Managed a team of 5 engineers"
      }
    ],
    "education": [
      {
        "degree": "B.S. in Computer Science",
        "university": "University Name",
        "year": "2017 – 2021",
        "gpa": "3.8/4.0",
        "honors": "Magna Cum Laude"
      }
    ],
    "certifications": ["AWS Solutions Architect", "PMP"],
    "projects": [
      {
        "name": "Project Name",
        "description": "Comprehensive project overview and achievements",
        "tech_stack": "React, Node.js, PostgreSQL",
        "link": "https://github.com/..."
      }
    ],
    "achievements": [
      "Won 1st place in 2023 National Hackathon",
      "Published research paper on AI Optimization"
    ],
    "publications": [],
    "volunteer": [],
    "custom_sections": [
      {
        "heading": "Section Heading",
        "content": "Full section content or key details"
      }
    ]
  },
  "metadata": {
    "document_type": "Resume",
    "language": "en",
    "confidence_score": 0.98,
    "total_sections_detected": 6
  }
}

Return ONLY the raw JSON object now."""


# ────────────────────────────────────────────────────────────────────────────
# Image Pre-processor & Optimizer
# ────────────────────────────────────────────────────────────────────────────
def _optimize_image_bytes(file_bytes: bytes, filename: str) -> tuple[bytes, str]:
    """
    Auto-orient EXIF, resize massive images to max 2048px (ideal for high-accuracy OCR),
    and output optimized PNG or JPEG bytes.
    """
    try:
        img = Image.open(io.BytesIO(file_bytes))
        # Auto-rotate according to EXIF tags (e.g. mobile photos)
        img = ImageOps.exif_transpose(img)

        # Scale down if larger than 2048 on longest edge
        max_dim = 2048
        w, h = img.size
        if w > max_dim or h > max_dim:
            scale = max_dim / max(w, h)
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        # Determine output format
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
        if ext in ("png", "webp", "gif"):
            out_buf = io.BytesIO()
            img.save(out_buf, format="PNG", optimize=True)
            return out_buf.getvalue(), "image/png"
        else:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            out_buf = io.BytesIO()
            img.save(out_buf, format="JPEG", quality=90, optimize=True)
            return out_buf.getvalue(), "image/jpeg"
    except Exception as e:
        logger.warning(f"Image optimization skipped: {e}")
        mime = "image/jpeg" if "jpg" in filename or "jpeg" in filename else "image/png"
        return file_bytes, mime


# ────────────────────────────────────────────────────────────────────────────
# JSON Parser & Schema Normalizer
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


_REQUIRED_RESUME_KEYS = {
    "name": "", "title": "", "email": "", "phone": "", "address": "",
    "website": "", "linkedin": "", "github": "", "portfolio": "",
    "summary": "", "skills": "",
    "languages": [], "experience": [], "education": [],
    "certifications": [], "projects": [], "achievements": [],
    "publications": [], "volunteer": [], "custom_sections": [],
}


def _parse_and_validate_resume_json(raw: str, raw_fallback: str = "") -> dict:
    """Validate and normalize parsed JSON to match standard WISAXIS schema."""
    parsed = _safe_parse_json(raw, {})
    if not isinstance(parsed, dict):
        parsed = {}

    # Extract structured_data or treat the whole parsed dict as structured_data
    if "structured_data" in parsed and isinstance(parsed["structured_data"], dict):
        raw_sd = parsed["structured_data"]
    else:
        raw_sd = {k: v for k, v in parsed.items() if k not in ("raw_text", "metadata")}

    result_structured = {**_REQUIRED_RESUME_KEYS, **raw_sd}

    # Normalize array fields
    for arr_key in ("languages", "experience", "education", "certifications",
                    "projects", "achievements", "publications", "volunteer", "custom_sections"):
        val = result_structured.get(arr_key)
        if not isinstance(val, list):
            result_structured[arr_key] = [val] if val else []

    # Normalize string fields
    for str_key in ("name", "title", "email", "phone", "address",
                    "website", "linkedin", "github", "portfolio", "summary", "skills"):
        val = result_structured.get(str_key)
        if isinstance(val, list):
            result_structured[str_key] = ", ".join(str(x) for x in val if x)
        elif val is None:
            result_structured[str_key] = ""
        else:
            result_structured[str_key] = str(val)

    # Normalize experience items
    norm_exp = []
    for item in result_structured["experience"]:
        if isinstance(item, dict):
            norm_exp.append({
                "title": str(item.get("title") or item.get("job_title") or ""),
                "company": str(item.get("company") or item.get("organization") or ""),
                "duration": str(item.get("duration") or item.get("dates") or item.get("year") or ""),
                "location": str(item.get("location") or ""),
                "description": str(item.get("description") or item.get("responsibilities") or item.get("details") or ""),
            })
        elif isinstance(item, str):
            norm_exp.append({"title": item, "company": "", "duration": "", "description": ""})
    result_structured["experience"] = norm_exp

    # Normalize education items
    norm_edu = []
    for item in result_structured["education"]:
        if isinstance(item, dict):
            norm_edu.append({
                "degree": str(item.get("degree") or item.get("qualification") or ""),
                "university": str(item.get("university") or item.get("institution") or item.get("school") or ""),
                "year": str(item.get("year") or item.get("duration") or item.get("graduation_year") or ""),
                "gpa": str(item.get("gpa") or ""),
                "honors": str(item.get("honors") or ""),
            })
        elif isinstance(item, str):
            norm_edu.append({"degree": item, "university": "", "year": ""})
    result_structured["education"] = norm_edu

    # Metadata & raw_text
    metadata = parsed.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    metadata.setdefault("document_type", "Document")
    metadata.setdefault("confidence_score", 0.95)

    raw_text = parsed.get("raw_text") or raw_fallback or ""

    return {
        "raw_text": str(raw_text),
        "structured_data": result_structured,
        "metadata": metadata
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

