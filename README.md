# AI Integration Architecture — WISAXIS Resume Maker

> **Provider:** OpenRouter API · **Protocol:** OpenAI-compatible REST · **Module:** `backend/services/ai_service.py`

---

## 1. Why OpenRouter?

OpenRouter is a unified API gateway that provides access to 100+ AI models (GPT-4o, Claude, Llama, Gemini, Mistral, etc.) through a single OpenAI-compatible endpoint. Key advantages for this project:

| Advantage | Detail |
|---|---|
| **Free tier** | `meta-llama/llama-3.1-8b-instruct:free` — zero cost for development |
| **Model flexibility** | Switch models by changing one `.env` variable — no code changes |
| **OpenAI-compatible** | Standard `POST /v1/chat/completions` format |
| **Fallback routing** | OpenRouter can automatically fall back to other models if one is unavailable |
| **Transparent pricing** | Per-token pricing shown on the dashboard |

---

## 2. AI Module Architecture

```
backend/services/ai_service.py
│
├── AIService (static class — no instantiation needed)
│   │
│   ├── Public Methods (called by route handlers)
│   │   ├── generate_summary(name, title, skills, experience_titles)
│   │   ├── generate_experience(title, company, duration, skills)
│   │   ├── chat(message, history)
│   │   ├── ats_score(resume_dict)
│   │   ├── generate_cover_letter(name, title, company, job_desc, skills)
│   │   ├── improve_grammar(text)
│   │   ├── suggest_skills(job_title, existing_skills)
│   │   └── extract_resume_from_file(file_path, ext)
│   │
│   └── Private Methods
│       ├── _call(prompt, action, max_tokens)
│       ├── _call_with_messages(messages, action, max_tokens)
│       └── (helpers) _log_ai_history, _dict_to_text, _extract_text_from_file
```

**Design:** All route handlers delegate to `AIService` methods. The service reads configuration from Flask's `current_app.config` — this means it always uses the current app's API key and model without needing them passed as arguments.

---

## 3. API Request Architecture

### 3.1 HTTP Request Structure

```python
headers = {
    "Authorization":  f"Bearer {api_key}",
    "Content-Type":   "application/json",
    "HTTP-Referer":   "https://wisaxis.com",    # For OpenRouter billing attribution
    "X-Title":        "WISAXIS Resume Maker",    # Shown in OpenRouter dashboard
}

payload = {
    "model":       "meta-llama/llama-3.1-8b-instruct:free",
    "messages":    [{"role": "user", "content": "..."}],
    "max_tokens":  1024,
    "temperature": 0.7,
}

response = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers=headers,
    json=payload,
    timeout=30,
)
```

### 3.2 Response Parsing

```python
content     = response.json()["choices"][0]["message"]["content"].strip()
tokens_used = response.json().get("usage", {}).get("total_tokens", 0)
```

---

## 4. Prompt Engineering Strategy

### 4.1 Professional Summary Prompt

**Design philosophy:** Explicit constraints prevent the AI from producing generic, clichéd output (e.g., "results-driven team player").

```python
prompt = f"""
Write a professional resume summary for {name}, a {title} with experience as {exp_context}.
Key skills: {skills}.

Requirements:
- 3-5 sentences, first-person style
- ATS-friendly with strong action verbs
- Highlight value, not just responsibilities
- Do not include a heading or label
- Do not use clichés like 'results-driven' or 'team player'
"""
```

**Temperature:** `0.7` — high enough for varied, natural language; low enough to stay professional.

### 4.2 Experience Bullet Points (CAR Framework)

The **CAR framework** (Challenge → Action → Result) is explicitly requested:

```python
prompt = f"""
Job Title: {title}
Company: {company}
Duration: {duration}
Skills used: {skills}

Write 3-5 impactful resume bullet points for this work experience.
Requirements:
- Use the CAR framework (Challenge → Action → Result)
- Start each bullet with a strong past-tense action verb
- Include quantifiable results where possible (percentages, numbers)
- ATS-optimised keywords for the job title
- Output only bullet points, no headings
- Format each bullet on a new line starting with •
"""
```

### 4.3 Multi-Turn Chat System Prompt

The chat uses a **system message** to maintain consistent persona across all turns:

```python
{
    "role": "system",
    "content": (
        "You are WISAXIS AI, an expert resume writer and career coach. "
        "You specialise in ATS optimisation, impactful wording, and professional formatting. "
        "Be concise, professional, and always practical. "
        "When writing resume content, use strong action verbs and quantifiable achievements. "
        "Format using markdown."
    )
}
```

### 4.4 ATS Score — Structured JSON Output

The ATS scorer requests a **structured JSON response** to enable frontend processing:

```python
prompt = f"""
Analyse the following resume and give an ATS compatibility score from 0 to 100.

Resume:
{resume_text}

Return a JSON object with exactly these keys:
  "score": integer 0-100
  "summary": one sentence overall assessment
  "strengths": array of 2-3 strong points
  "improvements": array of 3-5 specific improvements

Return ONLY the JSON, no extra text.
"""
```

The response is then parsed with `json.loads()`. If parsing fails (the model returns extra text), the raw string is returned as-is.

---

## 5. Context Window Management

### Chat History Truncation

To prevent exceeding the model's context window, only the **last 10 turns** of chat history are sent:

```python
for turn in history[-10:]:   # Most recent 10 turns
    if turn.get("role") in ("user", "assistant") and turn.get("content"):
        messages.append({"role": turn["role"], "content": turn["content"]})
```

At ~200 tokens per turn average, 10 turns = ~2,000 tokens of history, leaving plenty of room for the system prompt, current message, and response within an 8K context window.

### Token Budget by Action

| Action | `max_tokens` | Rationale |
|---|---|---|
| `generate_summary` | 1024 (default) | 3-5 sentences — needs ~300 tokens |
| `generate_experience` | 1024 (default) | 3-5 bullets — needs ~400 tokens |
| `chat` | 2048 | Longer conversational responses |
| `ats_score` | 512 | Structured JSON output is compact |
| `cover_letter` | 1024 | ~400 words |
| `improve_grammar` | 1024 | Same length as input |
| `suggest_skills` | 256 | Short comma-separated list |
| `extract_resume` | 2048 | Full resume JSON extraction |

---

## 6. Error Handling & Fallback Strategy

### Error Classification

```python
except requests.exceptions.Timeout:
    # User-facing: "AI request timed out. Please try again."
    # Cause: Network latency or model overload

except requests.exceptions.HTTPError as e:
    if e.response.status_code == 401:
        "Invalid OpenRouter API key."
    elif e.response.status_code == 402:
        "OpenRouter credit balance is too low."
    elif e.response.status_code == 429:
        "AI rate limit reached. Please wait a moment."
    else:
        f"AI API error: {status_code}"

except Exception:
    "An unexpected error occurred with the AI service."
```

### Frontend Fallback

When an AI endpoint returns `{ success: false }`, the frontend shows a toast and **does not clear** the existing form data. The user can retry without losing their work.

---

## 7. AI History Logging

Every AI call — success or failure — is logged to the `ai_history` table:

```python
record = AIHistory(
    user_id       = current_user.id,
    action        = action,             # 'generate_summary', 'chat', etc.
    prompt        = prompt[:2000],      # Truncated to prevent DB bloat
    response      = content[:4000],     # Truncated
    model_used    = model,              # 'meta-llama/llama-3.1-8b-instruct:free'
    tokens_used   = tokens_used,
    success       = True,
    error_message = None,
)
```

**Benefits:**
1. Debug production issues by inspecting prompts/responses
2. Track per-user token consumption
3. Analytics: which features are used most?
4. A/B test different prompts by comparing outputs

---

## 8. AI Resume Data Extraction (JSON Parser)

When a user uploads a PDF/DOCX on the JSON features page:

```
1. File saved to /uploads/tmp_<uuid>.<ext>
2. Text extraction:
   - PDF:  pdfplumber → extract_text() per page → join with \n
   - DOCX: python-docx → paragraph.text → join with \n
3. Text (first 4000 chars) sent to AI with structured extraction prompt
4. AI returns JSON matching WISAXIS resume schema
5. json.loads() parses the response
6. Stored in Flask session as session['import_data']
7. User redirected to /dashboard
8. Temporary file deleted (finally block)
```

**Optional dependencies:** `pdfplumber` and `python-docx` are not in `requirements.txt` by default — they are listed as commented-out optional deps. Install them if you need PDF/DOCX extraction.

---

## 9. Token Optimization Strategy

| Technique | Implementation |
|---|---|
| **Prompt brevity** | Prompts are ~50-100 words; no verbose preamble |
| **Response constraints** | `max_tokens` set per action type (not a blanket 2048) |
| **History truncation** | Last 10 turns only in chat |
| **Text truncation** | Resume text capped at 4000 chars for ATS analysis |
| **Skip empty fields** | Empty experience/skills not included in prompts |

**Future optimization — Response caching:**
```python
import hashlib, json
from functools import lru_cache

def _cache_key(action: str, **kwargs) -> str:
    return hashlib.sha256(
        json.dumps({"action": action, **kwargs}, sort_keys=True).encode()
    ).hexdigest()

# Cache identical prompts in Redis with TTL=3600 (1 hour)
```
This would reduce API costs by ~30-40% since many users ask for similar summaries for the same job title.

---

## 10. Multi-Model Support

The model is configured via a single `.env` variable:

```env
OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct:free
```

**Available free alternatives on OpenRouter:**
| Model | Best For |
|---|---|
| `meta-llama/llama-3.1-8b-instruct:free` | Default — fast, capable |
| `mistralai/mistral-7b-instruct:free` | Good instruction following |
| `google/gemma-3-4b-it:free` | Compact, fast |

**Premium models (paid):**
| Model | Best For |
|---|---|
| `openai/gpt-4o-mini` | Cost-effective premium |
| `anthropic/claude-3.5-haiku` | Excellent at professional writing |
| `openai/gpt-4o` | Best quality, highest cost |

**Future enhancement:** Allow users to select their preferred model from the UI (store in `user_settings.preferred_ai_model`).

---

## 11. AI Feature Roadmap

| Feature | Status | Implementation |
|---|---|---|
| Summary generation | ✅ Done | `AIService.generate_summary()` |
| Experience bullets | ✅ Done | `AIService.generate_experience()` |
| AI chat assistant | ✅ Done | `AIService.chat()` |
| ATS scoring | ✅ Done | `AIService.ats_score()` |
| Cover letter | ✅ Done | `AIService.generate_cover_letter()` |
| Grammar improvement | ✅ Done | `AIService.improve_grammar()` |
| Skill suggestions | ✅ Done | `AIService.suggest_skills()` |
| File extraction | ✅ Done | `AIService.extract_resume_from_file()` |
| Response caching | 🔲 Planned | Redis + hash-based cache key |
| Async generation | 🔲 Planned | Celery task queue |
| Job description matching | 🔲 Planned | Compare resume vs JD, give gap analysis |
| LinkedIn import | 🔲 Planned | Parse LinkedIn profile JSON export |
| Interview prep | 🔲 Planned | Generate likely interview questions from resume |

# API Architecture — WISAXIS Resume Maker

> **Style:** REST · JSON · Session auth · CSRF-protected · Rate-limited

---

## 1. API Design Principles

| Principle | Implementation |
|---|---|
| **Consistency** | All JSON responses use `{ "success": bool, "data": ..., "error": ... }` envelope |
| **Authentication** | Flask-Login session cookie (not JWT) — appropriate for a web app with server-rendered pages |
| **CSRF protection** | Every state-mutating request requires a valid CSRF token |
| **Ownership** | Every DB query includes `user_id=current_user.id` — users can never access other users' data |
| **Rate limiting** | Flask-Limiter with per-endpoint limits; AI endpoints are stricter |
| **Error clarity** | Validation errors return `422`; auth errors return `401/403`; not-found returns `404` |

---

## 2. Standard Response Envelope

### Success
```json
{
  "success": true,
  "data": { ... }
}
```

### Error
```json
{
  "success": false,
  "error": "Human-readable error message"
}
```

### Paginated List
```json
{
  "success": true,
  "data": [ ... ],
  "meta": {
    "page": 1,
    "per_page": 12,
    "total": 47,
    "pages": 4,
    "has_next": true,
    "has_prev": false
  }
}
```

---

## 3. Authentication Flow

### Session-Based (Web)
```
1. User submits POST /login with email + password + csrf_token
2. Server validates credentials
3. login_user(user) → Flask-Login sets session cookie
4. Subsequent requests include the session cookie automatically
5. @login_required decorator checks current_user.is_authenticated
```

### CSRF Token Flow
```
1. Page renders with {{ csrf_token() }} in a hidden input or <meta> tag
2. Forms: <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
3. fetch() calls: headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content }
4. Flask-WTF validates the token on every state-mutating request
5. Invalid token → 400 Bad Request
```

---

## 4. Complete Endpoint Reference

### 4.1 Authentication Endpoints

#### `POST /login`
**Rate limit:** 10/minute  
**Body:** `application/x-www-form-urlencoded`

| Field | Type | Required | Validation |
|---|---|---|---|
| `email` | string | ✅ | Valid email format |
| `password` | string | ✅ | Non-empty |
| `csrf_token` | string | ✅ | Valid WTF token |

**Responses:**
- `302` → `/dashboard` (success)
- `401` → Login page + flash "Invalid email or password"
- `400` → Login page + flash "Email and password are required"

---

#### `POST /signup`
**Rate limit:** 5/minute  
**Body:** `application/x-www-form-urlencoded`

| Field | Type | Required | Validation |
|---|---|---|---|
| `name` | string | ✅ | Min 2 characters |
| `email` | string | ✅ | Valid format, unique |
| `password` | string | ✅ | Min 8 characters |
| `confirm_password` | string | ✅ | Must match `password` |
| `csrf_token` | string | ✅ | Valid WTF token |

**Responses:**
- `302` → `/dashboard` (auto-logged in)
- `409` → Signup page + flash "Email already exists"
- `400` → Signup page + validation errors

---

### 4.2 Resume CRUD Endpoints

#### `POST /generate`
**Auth:** Required  
**Rate limit:** 30/hour  
**Content-Type:** `application/json`

**Request body:**
```json
{
  "resume_id": null,
  "template": "template1",
  "name": "Jane Doe",
  "title": "Senior Designer",
  "email": "jane@example.com",
  "phone": "1234567890",
  "address": "New York, NY",
  "photo": "/uploads/abc123.jpg",
  "summary": "Experienced designer...",
  "skills": ["Figma", "CSS", "React"],
  "languages": ["English (Native)", "French (B2)"],
  "experience": [
    {
      "title": "Lead Designer",
      "company": "Lumina Labs",
      "duration": "2023 – Present",
      "description": "• Led redesign of core product..."
    }
  ],
  "education": [
    {
      "degree": "B.A. Graphic Design",
      "university": "Parsons",
      "year": "2019"
    }
  ]
}
```

**Responses:**
```json
// 200 Success
{ "success": true, "redirect": "/resume/42", "resume_id": 42 }

// 422 Validation Error
{ "success": false, "error": "Name is required.; A valid email address is required." }

// 500 Server Error
{ "success": false, "error": "Failed to save resume. Please try again." }
```

---

#### `GET /resume/<id>`
**Auth:** Required  
**Response:** Rendered HTML (template page)  
**Ownership check:** `filter_by(id=id, user_id=current_user.id)`  
**404 if:** Resume doesn't exist OR belongs to another user

---

#### `GET /resume/<id>/download`
**Auth:** Required  
**Response:** JSON file download  
**Content-Disposition:** `attachment; filename="resume_Jane_Doe.json"`  
**Side effect:** Creates an `ExportHistory` record

---

#### `POST /resume/<id>/delete`
**Auth:** Required  
**Body:** `csrf_token` (form)  
**Action:** Sets `is_deleted=TRUE` (soft delete)  
**Response:** `302` → `/profile`

---

#### `POST /resume/<id>/duplicate`
**Auth:** Required  
**Body:** `duplicate_template=template2` + `csrf_token`  
**Action:** Deep-copies resume + all experience/education rows with new template  
**Response:** `302` → `/resume/<new_id>`

---

#### `POST /resume/<id>/switch-template`
**Auth:** Required  
**Body:** `template=template3` + `csrf_token`  
**Action:** Snapshots current version, updates `resume.template` in-place  
**Response:** `302` → `/resume/<id>`

---

### 4.3 AI Generation Endpoints

All AI endpoints share this contract:
- **Method:** POST
- **Auth:** Required
- **Content-Type:** `application/json`
- **Response envelope:** `{ "success": bool, "data": string, "tokens": int }`

#### `POST /api/generate-summary`
**Rate limit:** 20/hour

**Request:**
```json
{ "name": "Jane Doe", "title": "Senior Designer", "skills": "Figma, CSS" }
```

**Response:**
```json
{
  "success": true,
  "data": "Creative Senior Designer with 6+ years of experience...",
  "tokens": 187
}
```

---

#### `POST /api/generate-experience`
**Rate limit:** 20/hour

**Request:**
```json
{
  "title": "Lead UI/UX Designer",
  "company": "Lumina Labs",
  "duration": "2023 – Present",
  "skills": "Figma, React, CSS"
}
```

**Response:**
```json
{
  "success": true,
  "data": "• Spearheaded redesign of core product, increasing user retention by 34%\n• Led cross-functional team of 5...",
  "tokens": 203
}
```

---

#### `POST /api/ats-score`
**Rate limit:** 10/hour

**Request:**
```json
{ "resume_id": 42 }
```

**Response:**
```json
{
  "success": true,
  "data": {
    "score": 78,
    "summary": "Strong resume with good keyword density but missing quantifiable achievements.",
    "strengths": ["Clear job titles", "Relevant skills listed"],
    "improvements": ["Add measurable results to bullet points", "Include more industry keywords"]
  }
}
```

---

#### `POST /api/chat`
**Rate limit:** 60/hour

**Request:**
```json
{
  "message": "Write a professional summary for a Python developer.",
  "history": [
    { "role": "user", "content": "Hi" },
    { "role": "assistant", "content": "Hello! How can I help?" }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "data": "**Professional Summary:**\n\nResults-driven Python developer with 4+ years...",
  "tokens": 312
}
```

---

### 4.4 General API Endpoints

#### `GET /api/health`
**Auth:** None  
**Use:** Uptime monitors, deployment health checks

**Response:**
```json
{
  "status": "ok",
  "db": "ok",
  "app": "WISAXIS Resume Maker",
  "version": "2.0.0"
}
```

---

#### `POST /upload-photo`
**Auth:** Required  
**Rate limit:** 20/hour  
**Content-Type:** `multipart/form-data`

**Request:** Form field `photo` with image file  
**Validation:** Extension: jpg/jpeg/png/webp · Max size: 5MB

**Response:**
```json
{ "success": true, "url": "/uploads/abc123def456.jpg" }
```

---

#### `GET /api/resumes`
**Auth:** Required  
**Query params:** `?page=1`

**Response:** Paginated list of resumes (see Standard Response Envelope above)

---

#### `GET /api/templates`
**Auth:** None

**Response:**
```json
{
  "success": true,
  "data": [
    { "id": 1, "slug": "template1", "name": "Executive", "tag": "Professional", "preview_img": "templateA.webp" },
    ...
  ]
}
```

---

## 5. Rate Limiting Reference

| Endpoint | Limit | Storage |
|---|---|---|
| Global default | 200/hour, 50/min | Memory (dev) / Redis (prod) |
| `POST /login` | 10/min | Per IP |
| `POST /signup` | 5/min | Per IP |
| `POST /generate` | 30/hour | Per user |
| `POST /api/generate-summary` | 20/hour | Per user |
| `POST /api/generate-experience` | 20/hour | Per user |
| `POST /api/suggest-skills` | 15/hour | Per user |
| `POST /api/improve-grammar` | 15/hour | Per user |
| `POST /api/ats-score` | 10/hour | Per user |
| `POST /api/cover-letter` | 10/hour | Per user |
| `POST /api/chat` | 60/hour | Per user |
| `POST /upload-photo` | 20/hour | Per user |

**Rate limit exceeded response (429):**
```json
{ "success": false, "error": "Rate limit exceeded. Please wait." }
```

---

## 6. Validation Strategy

### Server-Side Validation Layers

```
Layer 1: Flask-WTF CSRF check (automatic on all POST/PUT/DELETE)
Layer 2: Type checking (request.get_json(silent=True) returns None on malformed JSON)
Layer 3: Field presence check (is field present and non-empty?)
Layer 4: Format validation (email regex, template whitelist, file extension whitelist)
Layer 5: Business logic (is this resume owned by the current user?)
Layer 6: Database constraints (unique email, foreign key integrity)
```

### Validation Response Format

```json
{
  "success": false,
  "error": "Name is required.; A valid email address is required."
}
```

Errors are joined with `"; "` for simplicity. In a future version, switch to a structured `errors` object:
```json
{
  "success": false,
  "errors": {
    "name": "Name is required.",
    "email": "A valid email address is required."
  }
}
```

---

## 7. API Versioning Strategy

The current API has no version prefix. To add versioning without breaking existing clients:

**Option A (Recommended — URL prefix):**
```
Current: /api/chat
v2:      /api/v2/chat
```

Register a new blueprint with `url_prefix="/api/v2"` and deprecate the old routes with a `Deprecation: true` response header.

**Option B (Header-based):**
```
Accept: application/vnd.wisaxis.v2+json
```

For a resume maker at this scale, Option A is simpler and more explicit.

---

## 8. Secure API Communication

| Concern | Implementation |
|---|---|
| Transport | HTTPS enforced in production (`SESSION_COOKIE_SECURE=True`) |
| CSRF | `X-CSRFToken` header required on all fetch() calls |
| Auth | Session cookie (`HttpOnly`, `SameSite=Lax`) |
| CORS | Restricted to `/api/*` routes; `CORS_ORIGINS` env var |
| Input size | `MAX_CONTENT_LENGTH=5MB` Flask config hard cap |
| SQL injection | SQLAlchemy parameterized queries only |
| Output encoding | Jinja2 auto-escapes all `{{ variables }}` |

# Backend Architecture — WISAXIS Resume Maker

> **Stack:** Python 3.12+ · Flask 3.1 · SQLAlchemy 2.0 · Flask-Login · Flask-WTF · Flask-Limiter

---

## 1. Architecture Philosophy

The backend follows the **Application Factory pattern** with **Blueprint-based modular routing**. This means:

- The `Flask` app object is never a module-level global — it is always created inside `create_app()`
- Every concern (auth, resume CRUD, AI, general API) lives in its own Blueprint
- Extensions (DB, login manager, CSRF, rate limiter) are instantiated once in `extensions.py` and registered via `extension.init_app(app)` inside the factory
- This design makes the app fully testable (pass `TestingConfig` to `create_app()`) and supports multiple app instances

---

## 2. Entry Points

| File | Command | Purpose |
|---|---|---|
| `app.py` | `python app.py` | Development server (Werkzeug reloader) |
| `backend/__init__.py` | `gunicorn "backend:create_app()"` | Production WSGI server |

---

## 3. Application Factory — `backend/__init__.py`

```python
def create_app(config_override=None) -> Flask:
    app = Flask(
        __name__,
        template_folder='../frontend/templates',
        static_folder='../frontend/static',
        static_url_path='/static',
    )
    app.config.from_object(config_override or get_config())

    # Extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": "*"}})
    limiter.init_app(app)

    # Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(resume_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(api_bp)

    # One-time DB setup
    with app.app_context():
        db.create_all()
        seed_templates()

    return app
```

**Key design choices:**
- `template_folder` and `static_folder` point to the `frontend/` directory — Flask serves all templates and assets without a separate web server in development
- `/js/<filename>` is served via a dedicated `send_from_directory` route for the `frontend/js/` directory
- `db.create_all()` runs inside `app_context()` — tables are created automatically on first run, no migration command needed for SQLite

---

## 4. Configuration System — `backend/config.py`

Three configuration classes share a common `Config` base:

```
Config (base)
├── DevelopmentConfig   FLASK_ENV=development (default)
├── TestingConfig       FLASK_ENV=testing  (in-memory SQLite, no CSRF)
└── ProductionConfig    FLASK_ENV=production (secure cookies, HTTPS)
```

**Resolution:** `get_config()` reads `FLASK_ENV` from the environment and returns the matching class. `create_app()` calls `get_config()` unless a `config_override` is passed (used in tests).

**Critical config values:**

| Key | Default | Notes |
|---|---|---|
| `SECRET_KEY` | *env var required* | Used for session signing + CSRF tokens |
| `SQLALCHEMY_DATABASE_URI` | `sqlite:///instance/wisaxis.db` | Auto-resolved to absolute path |
| `UPLOAD_FOLDER` | `instance/uploads/` | Created automatically |
| `MAX_CONTENT_LENGTH` | 5 MB | Flask enforces this on all requests |
| `OPENROUTER_API_KEY` | *env var required* | AI features disabled if missing |
| `RATELIMIT_STORAGE_URL` | `memory://` | Switch to `redis://` for multi-worker |

---

## 5. Extensions — `backend/extensions.py`

All extensions are module-level singletons:

```python
db           = SQLAlchemy()       # ORM
login_manager = LoginManager()   # Session auth
csrf         = CSRFProtect()     # CSRF tokens
limiter      = Limiter(...)      # Rate limiting
cors         = CORS()            # Cross-origin
```

**Why this matters:** By instantiating extensions here (not inside `create_app()`), any module can do `from backend.extensions import db` and use it safely — circular imports are avoided because no `app` object is referenced at import time.

---

## 6. Blueprint Structure

### 6.1 Auth Blueprint — `backend/routes/auth.py`

**Prefix:** none (routes: `/login`, `/signup`, `/logout`)

| Route | Method | Rate Limit | Logic |
|---|---|---|---|
| `/login` | GET | — | Render login form |
| `/login` | POST | 10/min | Validate → check hash → `login_user()` → redirect |
| `/signup` | GET | — | Render signup form |
| `/signup` | POST | 5/min | Validate → check duplicate email → create User + UserSettings → `login_user()` → redirect |
| `/logout` | GET | — | `logout_user()` → `session.clear()` → redirect to home |

**Security decisions:**
- Login error message is generic: *"Invalid email or password"* — never reveals whether the email exists (prevents user enumeration attacks)
- `login_user(user, remember=True)` sets a persistent cookie (7-day lifetime via `PERMANENT_SESSION_LIFETIME`)
- `last_login_at` is updated on every successful login for audit purposes
- `UserSettings` row is created with defaults at signup — ensures every user has preferences

### 6.2 Main Blueprint — `backend/routes/main.py`

**Prefix:** none (page routes)

| Route | Auth | Template | Key context |
|---|---|---|---|
| `GET /` | No | `home.html` | Redirects logged-in users |
| `GET /dashboard` | Yes | `index.html` | `editing=False`, `resume_data=None` |
| `GET /edit/<id>` | Yes | `index.html` | `editing=True`, `resume_data=resume.to_dict()` |
| `GET /profile` | Yes | `profile.html` | `resumes=[]`, `total_prints=N` |
| `GET /chat` | Yes | `chat.html` | `user=current_user.name` |
| `GET /json` | Yes | `json_features.html` | `user=current_user.name` |

The edit route calls `Resume.query.filter_by(id=..., user_id=current_user.id)` — the `user_id` filter prevents one user from editing another's resume (IDOR protection).

### 6.3 Resume Blueprint — `backend/routes/resume.py`

**Prefix:** none

The most complex blueprint. Handles all resume lifecycle operations.

**POST `/generate` — Create/Update Logic:**

```
1. Parse JSON body
2. Validate required fields (name, title, email, template)
3. if resume_id present:
     - Fetch resume, verify ownership
     - Snapshot current state → ResumeVersion table
     - Increment version counter
     - DELETE old Experience + Education rows
4. else:
     - Create new Resume row
5. Populate all fields
6. INSERT new Experience rows (skip blank titles)
7. INSERT new Education rows (skip blank degrees)
8. db.session.commit()
9. Return { success: true, redirect: "/resume/<id>" }
```

**Version snapshots** are created before every update by calling `_snapshot_resume(resume)`, which serializes `resume.to_dict()` to JSON and stores it in `ResumeVersion`. Users can retrieve up to 20 versions via `GET /resume/<id>/versions`.

### 6.4 AI Blueprint — `backend/routes/ai.py`

**Prefix:** `/api`

All routes are `POST`, require `@login_required`, and are rate-limited per-hour. They delegate to `AIService` methods and return `{ success, data }` or `{ success, error }` JSON.

### 6.5 API Blueprint — `backend/routes/api.py`

**Prefix:** none

General-purpose API routes:
- `GET /api/health` — no auth, used by uptime monitors and deployment platforms
- `POST /api/chat` — the AI chat assistant endpoint (60/hr rate limit)
- `POST /upload-photo` — file validation, UUID rename, save to `UPLOAD_FOLDER`
- `GET /api/resumes` — paginated resume list (12 per page)
- `GET /api/resumes/<id>` — single resume as JSON
- `GET /api/templates` — template catalogue (no auth — used on landing page)
- `GET /api/me` — current user profile JSON

---

## 7. Service Layer — `backend/services/ai_service.py`

The `AIService` class is a pure static-method utility. It has no state and no `__init__`. All methods are `@classmethod` so they can be called as `AIService.method()` without instantiation.

**Separation of concerns:** Route handlers (in `ai.py`) only validate input and format responses. All AI API communication, prompt construction, error handling, and logging live in `ai_service.py`. This makes the service independently testable and swappable (e.g., switch from OpenRouter to OpenAI by changing only this file).

---

## 8. Error Handling

Five global error handlers are registered in `create_app()`:

| Code | Handler | API response | Page response |
|---|---|---|---|
| 400 | `bad_request` | `{"success": false, "error": "..."}` | `404.html` |
| 401 | `unauthorized` | `{"success": false, "error": "Unauthorized"}` | Redirect to `/login` |
| 403 | `forbidden` | `{"success": false, "error": "Forbidden"}` | `404.html` |
| 404 | `not_found` | `{"success": false, "error": "Not found"}` | `404.html` |
| 429 | `too_many_requests` | `{"success": false, "error": "Rate limit exceeded"}` | `404.html` |
| 500 | `internal_error` | `{"success": false, "error": "Internal server error"}` | `404.html` |

The 500 handler calls `db.session.rollback()` before responding — this prevents broken database transactions from persisting across requests.

**API detection:** The `_is_api_request()` helper checks `request.path.startswith('/api/')` or `request.is_json` to decide whether to return JSON or an HTML error page.

---

## 9. Logging System

```python
# Rotating file handler — 10MB per file, 5 backups = max 50MB disk usage
RotatingFileHandler(log_file, maxBytes=10_000_000, backupCount=5)
```

- Log format: `[timestamp] LEVEL in module: message`
- Log file: `instance/app.log`
- Only active in non-debug mode (development uses Werkzeug's built-in logging)
- AI service logs every API call at INFO level and every error at ERROR level

---

## 10. Session & Authentication

Flask-Login manages the session. Key configuration:

```python
login_manager.login_view = "auth.login"       # redirect destination
SESSION_COOKIE_HTTPONLY = True                 # JS cannot read the cookie
SESSION_COOKIE_SAMESITE = "Lax"               # CSRF mitigation
PERMANENT_SESSION_LIFETIME = timedelta(days=7) # 7-day session
SESSION_COOKIE_SECURE = True  # (production only) — HTTPS only
```

**User loader:**
```python
@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))
```

This is called on every request where a session cookie is present. Flask-Login caches the result per request via `g` so the DB is queried at most once per request.

---

## 11. File Upload Handling

Upload pipeline for profile photos:

```
1. Receive file via request.files.get('photo')
2. secure_filename() — strips path traversal characters
3. Extension check against ALLOWED_PHOTO_EXTENSIONS = {jpg, jpeg, png, webp}
4. Size check: read to end (seek), verify < MAX_CONTENT_LENGTH
5. Generate UUID4 filename: uuid4().hex + '.' + ext
6. Save to UPLOAD_FOLDER (instance/uploads/)
7. Return URL: /uploads/<uuid_filename>
```

UUID filenames prevent:
- Filename collisions between users
- Path traversal attacks
- Enumeration of other users' photos

---

## 12. Production-Ready Considerations

| Concern | Current Implementation | Production Upgrade |
|---|---|---|
| Database | SQLite (file) | PostgreSQL (connection pool) |
| Sessions | Cookie-based (Flask) | Redis-backed sessions |
| Rate limiting | In-memory | Redis-backed (`RATELIMIT_STORAGE_URL=redis://`) |
| File storage | Local disk | S3 / Cloudflare R2 |
| Workers | Single (dev) | Gunicorn 2–4 workers |
| Caching | None | Redis + Flask-Caching |
| Background tasks | Synchronous AI calls | Celery + Redis queue |
| Monitoring | Log file | Sentry (DSN in `.env`) |

---

## 13. Backend Optimization Strategy

1. **Database connection pooling** — add `SQLALCHEMY_ENGINE_OPTIONS = {"pool_size": 10, "max_overflow": 20}` for PostgreSQL
2. **AI response caching** — cache identical prompts (same job title + skills) with a Redis TTL of 1 hour; reduces OpenRouter costs by ~40%
3. **Async AI calls** — move AI generation to Celery tasks; return a job ID immediately, poll for result
4. **Paginate AI history** — the `ai_history` table will grow fast; add a cleanup job to delete records older than 90 days
5. **Resume query optimization** — the profile page query already uses `.order_by(Resume.updated_at.desc())`; add a composite index on `(user_id, is_deleted, updated_at)`

# Database Architecture — WISAXIS Resume Maker

> **Engine:** SQLite (development) · PostgreSQL-compatible (production) · ORM: SQLAlchemy 2.0

---

## 1. Design Philosophy

The database schema is designed around three principles:

1. **Frontend-aligned data shape** — `Resume.to_dict()` returns a dict that exactly mirrors the Vue wizard's `formData` object, so the backend can hydrate the form for editing without any transformation layer
2. **Ownership isolation** — every query for user-owned data includes `user_id=current_user.id` in the filter, making horizontal data isolation a database guarantee, not just an application concern
3. **Lightweight denormalization where it makes sense** — Skills (comma-separated text) and Languages (JSON array) are stored as single columns because the wizard treats them as single inputs. Normalizing them into separate tables would add complexity with zero query benefit at this scale.

---

## 2. Complete Table Definitions

### 2.1 `users`

```sql
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          VARCHAR(120)  NOT NULL,
    email         VARCHAR(254)  NOT NULL UNIQUE,
    password_hash VARCHAR(256)  NOT NULL,
    is_admin      BOOLEAN       NOT NULL DEFAULT FALSE,
    is_active     BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME,
    last_login_at DATETIME
);
CREATE INDEX ix_users_email ON users (email);
```

**Notes:**
- `email` has a unique constraint enforced both at DB level and application level
- `password_hash` stores the output of `werkzeug.security.generate_password_hash` (PBKDF2-SHA256, never plaintext)
- `is_active=FALSE` soft-disables an account without deleting data (admin feature)
- `last_login_at` is updated on every successful login — useful for audit trails and inactive user cleanup

---

### 2.2 `user_settings`

```sql
CREATE TABLE user_settings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    default_template    VARCHAR(50)  DEFAULT 'template1',
    email_notifications BOOLEAN      DEFAULT TRUE,
    theme_preference    VARCHAR(20)  DEFAULT 'dark',
    updated_at          DATETIME
);
```

**Notes:**
- 1-to-1 relationship enforced by `UNIQUE` on `user_id`
- Created automatically with defaults at signup via `db.session.flush()` + `UserSettings(user_id=new_user.id)`
- `ON DELETE CASCADE` — deleting a user removes their settings

---

### 2.3 `resumes`

```sql
CREATE TABLE resumes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    template    VARCHAR(50)  NOT NULL DEFAULT 'template1',
    name        VARCHAR(120) NOT NULL,
    title       VARCHAR(120) NOT NULL,
    email       VARCHAR(254) NOT NULL,
    phone       VARCHAR(30),
    address     VARCHAR(255),
    photo_url   VARCHAR(512),
    summary     TEXT,
    skills      TEXT,          -- "Python, Flask, SQL" (comma-separated)
    languages   TEXT,          -- '["English (Native)", "French (B2)"]' (JSON)
    version     INTEGER NOT NULL DEFAULT 1,
    is_deleted  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME
);
CREATE INDEX ix_resumes_user_id ON resumes (user_id);
```

**Denormalization rationale:**
- **`skills`** — stored as comma-separated string because the wizard input is `<input type="text" placeholder="Python, Flask, SQL">`. No query ever needs to filter by individual skill at this scale. The `skills_list` property on the model converts it to a list on demand.
- **`languages`** — stored as JSON array string because `json.loads()` is O(1) and the list is always loaded as a whole unit.

**Soft delete:** `is_deleted=TRUE` hides a resume from the user's profile without destroying the data. All queries add `filter_by(is_deleted=False)`. A cron job can hard-delete records older than 30 days.

---

### 2.4 `experiences`

```sql
CREATE TABLE experiences (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id   INTEGER NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL DEFAULT 0,
    title       VARCHAR(150) NOT NULL,
    company     VARCHAR(150),
    duration    VARCHAR(100),   -- "Jan 2020 – Present"
    description TEXT
);
CREATE INDEX ix_experiences_resume_id ON experiences (resume_id);
```

**Update strategy:** On every resume save, all experience rows for that `resume_id` are deleted (`DELETE WHERE resume_id=X`) and re-inserted in order. This is simpler and more reliable than diffing individual rows, and at the scale of 1–5 experience entries per resume, the performance difference is negligible.

---

### 2.5 `educations`

```sql
CREATE TABLE educations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id   INTEGER NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL DEFAULT 0,
    degree      VARCHAR(200),   -- "B.Sc Computer Science"
    university  VARCHAR(200),
    year        VARCHAR(50)     -- "2021" or "2018–2022"
);
CREATE INDEX ix_educations_resume_id ON educations (resume_id);
```

---

### 2.6 `resume_versions`

```sql
CREATE TABLE resume_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id   INTEGER NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    version_num INTEGER NOT NULL,
    snapshot    TEXT    NOT NULL,   -- JSON blob of Resume.to_dict()
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_resume_versions_resume_id ON resume_versions (resume_id);
```

**Version control strategy:**
1. Before any update, `_snapshot_resume(resume)` is called
2. It creates a `ResumeVersion` row with the current `resume.version` number and a full JSON snapshot
3. `resume.version` is then incremented
4. On rollback (future feature), deserialize the snapshot and re-apply it

The API returns up to 20 versions ordered by `version_num DESC`.

---

### 2.7 `export_history`

```sql
CREATE TABLE export_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id   INTEGER NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    format      VARCHAR(10) DEFAULT 'pdf',   -- 'pdf' | 'json' | 'doc'
    exported_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_export_history_resume_id ON export_history (resume_id);
```

**Use cases:**
- Analytics: "How many resumes were downloaded last month?"
- Per-user: "How many times has this resume been exported?"
- Format breakdown: PDF vs JSON preference

---

### 2.8 `ai_history`

```sql
CREATE TABLE ai_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    resume_id     INTEGER REFERENCES resumes(id) ON DELETE SET NULL,
    action        VARCHAR(60) NOT NULL,   -- 'generate_summary', 'chat', 'ats_score', ...
    prompt        TEXT,                  -- truncated to 2000 chars
    response      TEXT,                  -- truncated to 4000 chars
    model_used    VARCHAR(100),
    tokens_used   INTEGER DEFAULT 0,
    success       BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_ai_history_user_id ON ai_history (user_id);
```

**Design decisions:**
- `resume_id` is nullable (`ON DELETE SET NULL`) — AI history is preserved even if the resume is deleted
- `prompt` and `response` are truncated at storage time (2000/4000 chars) to prevent unbounded growth
- `tokens_used` enables per-user token budgeting (future: add a monthly cap)
- `error_message` captures API error details when `success=FALSE`

---

### 2.9 `templates`

```sql
CREATE TABLE templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        VARCHAR(50) NOT NULL UNIQUE,   -- 'template1'
    name        VARCHAR(80) NOT NULL,           -- 'Executive'
    tag         VARCHAR(50),                    -- 'Professional'
    preview_img VARCHAR(120),                   -- 'templateA.webp'
    is_active   BOOLEAN DEFAULT TRUE,
    sort_order  INTEGER DEFAULT 0
);
```

**Seed data:** 8 rows are inserted on first startup by `seed_templates()`. This function is idempotent — it checks for existing slugs before inserting, so calling it multiple times is safe.

---

## 3. Entity-Relationship Diagram

```
users ──────────────────────────────────────────────┐
  │ 1                                                │ 1
  │ ∞                                                │ 1
  ├── resumes                                        └── user_settings
  │     │ 1
  │     ├── experiences (∞)
  │     ├── educations  (∞)
  │     ├── resume_versions (∞)
  │     └── export_history (∞)
  │
  └── ai_history (∞)
          │ (nullable FK)
          └── resumes
```

**Cardinalities:**
| Relationship | Type | On Delete |
|---|---|---|
| User → Resumes | 1-to-many | CASCADE |
| User → UserSettings | 1-to-1 | CASCADE |
| User → AIHistory | 1-to-many | CASCADE |
| Resume → Experiences | 1-to-many | CASCADE |
| Resume → Educations | 1-to-many | CASCADE |
| Resume → ResumeVersions | 1-to-many | CASCADE |
| Resume → ExportHistory | 1-to-many | CASCADE |
| Resume → AIHistory | 1-to-many | SET NULL |

---

## 4. Normalization Analysis

| Level | Status | Notes |
|---|---|---|
| 1NF | ✅ | All columns hold atomic values; skills/languages are intentional denormalizations |
| 2NF | ✅ | No partial dependencies; all non-key columns depend on the full primary key |
| 3NF | ✅ | No transitive dependencies between non-key columns |
| BCNF | ✅ | No non-trivial functional dependencies on non-superkeys |

---

## 5. Indexing Strategy

| Table | Index Columns | Query Pattern |
|---|---|---|
| `users` | `email` | Login lookup: `WHERE email = ?` |
| `resumes` | `user_id` | Profile page: `WHERE user_id = ? AND is_deleted = FALSE` |
| `resumes` | `(user_id, is_deleted, updated_at)` | *(Recommended)* Profile + sort |
| `experiences` | `resume_id` | Eager loading with resume |
| `educations` | `resume_id` | Eager loading with resume |
| `resume_versions` | `resume_id` | Version history list |
| `export_history` | `resume_id` | Export count query |
| `ai_history` | `user_id` | Per-user AI history |

---

## 6. SQLAlchemy ORM Configuration

```python
SQLALCHEMY_DATABASE_URI = "sqlite:///instance/wisaxis.db"
SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_pre_ping": True,   # Test connections before use
    "pool_recycle": 300,     # Recycle stale connections every 5 min
}
```

**Eager loading:** Experience and Education rows use `lazy="selectin"` — when a `Resume` is loaded, SQLAlchemy issues a single `SELECT ... WHERE resume_id IN (...)` to load all child rows, instead of N+1 queries.

---

## 7. Query Optimization Patterns

### Profile page query
```python
Resume.query
    .filter_by(user_id=current_user.id, is_deleted=False)
    .order_by(Resume.updated_at.desc())
    .all()
```
Add a composite index: `CREATE INDEX ix_resumes_user_active_date ON resumes(user_id, is_deleted, updated_at DESC)`

### Paginated resume API
```python
Resume.query
    .filter_by(user_id=current_user.id, is_deleted=False)
    .order_by(Resume.updated_at.desc())
    .paginate(page=page, per_page=12, error_out=False)
```

### AI history cleanup (recommended cron)
```sql
DELETE FROM ai_history
WHERE created_at < datetime('now', '-90 days');
```

---

## 8. Migration Strategy (SQLite → PostgreSQL)

When you outgrow SQLite (typically at >10K users or high write concurrency):

1. **Change `DATABASE_URL`** in `.env` to a PostgreSQL connection string — SQLAlchemy's dialect abstraction handles the rest
2. **Generate a schema dump** from SQLite: `sqlite3 wisaxis.db .dump > schema.sql`
3. **Apply with Alembic** for future schema changes:
   ```bash
   flask db init
   flask db migrate -m "initial"
   flask db upgrade
   ```
4. **Data migration** using `pg_restore` or a custom script

**Incompatibilities to watch:**
- SQLite's `BOOLEAN` stores as 0/1 integers — PostgreSQL uses native `BOOLEAN`
- `AUTOINCREMENT` → `SERIAL` / `BIGSERIAL` in PostgreSQL
- `DATETIME` → `TIMESTAMP WITH TIME ZONE` in PostgreSQL

---

## 9. Scalability Planning

| Milestone | Users | Action Required |
|---|---|---|
| Current | 0–10K | SQLite (default) |
| Phase 2 | 10K–100K | PostgreSQL + connection pooling (PgBouncer) |
| Phase 3 | 100K+ | Read replicas + query caching (Redis) |
| Phase 4 | 1M+ | Horizontal sharding or switch to a managed DB (PlanetScale / Neon) |

# Deployment Architecture — WISAXIS Resume Maker

> Comprehensive guide for deploying the WISAXIS Resume Maker to both development and production environments.

---

## 1. Local Development Setup

### 1.1 Prerequisites
- Python 3.12 or higher
- Git

### 1.2 Installation Steps

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd resume2.0
   ```

2. **Create and activate a virtual environment (recommended):**
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   - Copy the example config: `cp .env.example .env` (or `copy .env.example .env` on Windows)
   - Open `.env` and add your `OPENROUTER_API_KEY`. Get a free key at [openrouter.ai](https://openrouter.ai).
   - Ensure `FLASK_ENV=development` is set.

5. **Run the development server:**
   ```bash
   python app.py
   ```
   The application will be available at `http://127.0.0.1:5050`. The SQLite database (`instance/wisaxis.db`) will be created automatically on the first request.

---

## 2. Production Deployment

For a production environment, you should never use the built-in Flask development server. A WSGI server like Gunicorn is required.

### 2.1 Environment Configuration (`.env`)

In production, these variables MUST be set securely in your hosting provider's dashboard, not committed to code:

```env
FLASK_ENV=production
FLASK_DEBUG=false
SECRET_KEY=generate_a_secure_64_character_random_string_here
OPENROUTER_API_KEY=your_production_openrouter_key
```

**Optional but recommended for production:**
- `DATABASE_URL`: Set to a PostgreSQL connection string instead of relying on the default SQLite database.
- `REDIS_URL`: Set to a Redis connection string to enable shared, persistent rate-limiting across multiple worker processes.

### 2.2 Running with Gunicorn

Start the application using Gunicorn:

```bash
gunicorn "backend:create_app()" --bind 0.0.0.0:8000 --workers 4
```

*Rule of thumb for workers:* `(2 x $num_cores) + 1`

---

## 3. Deployment Platforms

### 3.1 Render.com (Recommended for ease of use)

1. Connect your GitHub repository to Render.
2. Create a new **Web Service**.
3. **Environment:** Python 3
4. **Build Command:** `pip install -r requirements.txt`
5. **Start Command:** `gunicorn "backend:create_app()" --bind 0.0.0.0:$PORT --workers 2`
6. Add Environment Variables in the Render dashboard:
   - `PYTHON_VERSION`: 3.12.x
   - `SECRET_KEY`: (generate a random string)
   - `OPENROUTER_API_KEY`: (your key)
7. Render provisions a PostgreSQL database easily if you wish to upgrade from SQLite.

### 3.2 Railway.app

1. Deploy from GitHub repository.
2. Railway automatically detects the Python environment and `requirements.txt`.
3. Set the custom Start Command in settings: `gunicorn "backend:create_app()" --bind 0.0.0.0:$PORT`
4. Add your Environment Variables.
5. Railway allows easy provisioning of PostgreSQL and Redis services within the same project.

---

## 4. Scaling Strategy

As the application grows, the current architecture supports scaling through these phases:

### Phase 1: Vertical Scaling (Current)
- **Database:** SQLite (file-based). Suitable for up to ~10k users.
- **Compute:** Increase server RAM/CPU and add more Gunicorn workers.
- **Limitation:** SQLite locks the entire database on writes. Concurrent writes will eventually bottleneck.

### Phase 2: Horizontal Scaling
To run the application across multiple servers (horizontal scaling), you must eliminate local state:
1. **Database:** Migrate from SQLite to a managed PostgreSQL instance (e.g., AWS RDS, Supabase).
2. **File Uploads:** Move user profile photos (`instance/uploads`) from local disk to object storage (e.g., AWS S3, Cloudflare R2). Update the upload route in `routes/api.py` to upload directly to S3 and store the S3 URL in the database.
3. **Rate Limiting:** Provide a `REDIS_URL` in the environment so Flask-Limiter tracks request counts centrally rather than in the local memory of each worker process.

### Phase 3: Performance Optimization
- **Database Connection Pooling:** Implement PgBouncer or configure SQLAlchemy engine options (`pool_size`, `max_overflow`).
- **CDN:** Serve all static assets (`frontend/static/css`, `frontend/static/js`, `frontend/static/images`) through a CDN like Cloudflare to reduce server load.
- **Async AI Generation:** Currently, AI calls block the HTTP request thread. For high concurrency, offload `AIService` calls to a Celery task queue (backed by Redis or RabbitMQ). The frontend would poll for task completion or use WebSockets.

---

## 5. CI/CD Pipeline Suggestions

Implement a basic GitHub Actions workflow (`.github/workflows/main.yml`) to enforce code quality before deployment:

1. **Linting & Formatting:** Use `ruff` or `flake8` to enforce Python styling.
2. **Type Checking:** Run `mypy` to catch type errors.
3. **Testing:** Run a `pytest` suite. Set `FLASK_ENV=testing` to use the in-memory database and skip external API calls by mocking `AIService`.
4. **Deployment Trigger:** If tests pass on the `main` branch, trigger a deployment webhook to your hosting provider (Render/Railway).

# Folder Structure & Architecture — WISAXIS Resume Maker

> A detailed breakdown of the complete project architecture, explaining the responsibility of every directory and key file.

---

## 1. High-Level Architecture Overview

The WISAXIS Resume Maker employs a decoupled, modular architecture within a monolithic repository. It leverages a Flask-based backend acting as both a server-side renderer (for page layouts) and a JSON API (for the frontend Vue application and AI interactions).

```plaintext
resume2.0/
├── app.py                      # Development entry point
├── requirements.txt            # Python dependencies
├── .env                        # Environment variables (secrets)
├── .env.example                # Template for environment variables
├── instance/                   # Local storage (git-ignored)
├── backend/                    # Python Flask application source
├── frontend/                   # Client-side assets and HTML templates
└── docs/                       # Technical documentation
```

---

## 2. The `backend/` Directory

The backend strictly follows the **Application Factory pattern** and uses **Flask Blueprints** to separate concerns. This prevents circular imports and makes testing significantly easier.

```plaintext
backend/
├── __init__.py                 # create_app() factory. Wires blueprints, DB, and extensions.
├── config.py                   # Configuration classes (Development/Production/Testing).
├── extensions.py               # Instantiates extensions (SQLAlchemy, LoginManager, Limiter) without app context.
│
├── models/                     # Database Layer
│   └── __init__.py             # Defines all SQLAlchemy classes (User, Resume, Experience, etc.) and relationships.
│
├── routes/                     # API and Routing Layer (Blueprints)
│   ├── __init__.py
│   ├── auth.py                 # Handles /login, /signup, /logout.
│   ├── main.py                 # Handles page rendering for /, /dashboard, /profile, /chat, /json.
│   ├── resume.py               # Handles Resume CRUD operations (POST /generate, DELETE, duplicate, download).
│   ├── ai.py                   # Specific API endpoints called by the wizard for inline AI generation.
│   └── api.py                  # General API routes: health check, photo upload, paginated resume fetching.
│
└── services/                   # Business Logic Layer
    ├── __init__.py
    └── ai_service.py           # Centralized integration with the OpenRouter API. Handles prompts, errors, and logging.
```

### Architecture Rule: Service Layer Abstraction
Route handlers (`routes/`) are responsible *only* for HTTP concerns: parsing requests, validating input, checking authentication, and formatting JSON responses. Complex business logic and external API communication (like OpenRouter) are strictly abstracted into the `services/` layer.

---

## 3. The `frontend/` Directory

The frontend combines server-side rendered (SSR) Jinja2 templates with client-side Vue.js reactivity where complex state management is needed (specifically, the resume builder wizard).

```plaintext
frontend/
├── templates/                  # Jinja2 HTML Templates
│   ├── home.html               # Landing page
│   ├── index.html              # The Vue.js Resume Builder Wizard page
│   ├── login.html & signup.html# Authentication views
│   ├── profile.html            # User dashboard showing resume history
│   ├── chat.html               # Dedicated AI assistant chat interface
│   ├── json_features.html      # UI for parsing resumes from PDF/DOCX/JSON
│   ├── template1.html ... template8.html # The actual resume visual layouts
│   ├── template_background.html# The base wrapper layout used by template1-8
│   │
│   └── partials/               # Reusable UI fragments
│       ├── export_toolbar.html # The PDF/DOC download floating menu
│       ├── template_switcher.html # The horizontal template selection strip
│       └── global_bg.html      # The mesh gradient background elements
│
├── static/                     # Publicly served assets (/static/...)
│   ├── css/                    # Modular CSS Architecture
│   │   ├── 00-variables.css    # Design tokens (colors, spacing, typography)
│   │   ├── 01-reset.css        # Browser normalization
│   │   ├── 02-theme.css        # Dark/light mode variables and body styles
│   │   ├── 03-global-effects.css # Keyframe animations and glassmorphism
│   │   ├── 04-global-background.css # Background layer styles
│   │   ├── 05-components/      # Isolated component styles (buttons.css, header.css, etc.)
│   │   ├── 06-layout/          # Structural layout styles
│   │   ├── 07-pages/           # Page-specific styles (auth.css, home.css)
│   │   └── 09-utilities.css    # Helper classes and print-mode specific CSS
│   │
│   ├── images/                 # Template preview thumbnails and logos
│   └── fonts/                  # Locally hosted fonts
│
└── js/                         # Client-side JavaScript
    ├── wizard-vue.js           # Core Vue 3 application logic managing the resume builder state
    ├── toast.js                # Custom toast notification system
    ├── theme-controller.js     # Manages the dark/light mode toggle and localStorage
    ├── carousel.js             # Logic for the landing page template carousel
    └── ...                     # Other interaction scripts
```

### Architecture Rule: CSS Organization
The CSS is structured in a strict numerical loading order (00 to 09). `00-variables.css` acts as the single source of truth for the design system. Components (05) are isolated and never rely on page context. This ensures a highly maintainable, collision-free styling system.

---

## 4. The `instance/` Directory

This directory is automatically generated by Flask. It is used to store local state and should **always** be included in `.gitignore`.

```plaintext
instance/
├── wisaxis.db                  # The SQLite database file (created on first run).
├── uploads/                    # Directory where user profile photos are saved before being linked to a resume.
└── app.log                     # Application logs generated by the RotatingFileHandler.
```

---

## 5. Recommended Architecture for Future Scaling

As the platform moves towards enterprise scale, consider the following structural evolutions:

1. **Decouple the Frontend (SPA Transition):**
   Separate the `frontend/` directory entirely into a standalone Next.js or Nuxt.js repository. Convert the Flask backend into a pure JSON REST API. This allows independent scaling and deployment of the client and server.

2. **Module-Based Backend Structure:**
   If the feature set grows significantly, switch from the current layer-based structure (`routes/`, `models/`, `services/`) to a domain-driven structure (e.g., `backend/users/`, `backend/resumes/`, `backend/ai/`), where each module contains its own routes, models, and services.

3. **Background Task Queue:**
   Introduce a `tasks/` directory to hold Celery workers for asynchronous processing (e.g., PDF generation on the server, batch AI processing, sending emails).

# Frontend Architecture — WISAXIS Resume Maker

> **Stack:** HTML5 · Vanilla CSS (design-token system) · JavaScript · Vue 3 (CDN) · Jinja2 templating

---

## 1. Overview

The frontend is a server-rendered multi-page application (MPA) built on Flask/Jinja2 templates, enhanced with selective Vue 3 reactivity for the resume wizard. This hybrid architecture gives fast initial page loads (SSR) with rich interactivity where it counts (the form wizard and AI chat), without the complexity of a full SPA framework.

---

## 2. Page-by-Page Breakdown

### 2.1 Landing Page — `home.html`

**Route:** `GET /` (unauthenticated only — redirects authenticated users to dashboard)

**Sections:**
| Section | Class | Purpose |
|---|---|---|
| Header | `.app-header` | Brand + Login/Signup nav + theme toggle |
| Hero | `.hero` | H1 tagline, CTA buttons, trust badges |
| Template carousel | `.template-section` | Auto-scrolling infinite loop of 8 templates |
| Info strip | `.info-section` | ATS pitch + feature pills |
| Footer | `.app-footer` | Links, copyright |

**Key interactions:**
- Template carousel uses CSS animation (`@keyframes scroll`) — no JavaScript needed for the loop, only for hover-pause (handled in `carousel.js`)
- "Build My Resume" CTA → `url_for('main.dashboard')` (requires login; redirects to login if not authenticated)
- "View Templates" CTA scrolls to `#templates` anchor

**JavaScript loaded:** `header-scroll.js` · `carousel.js` · `global-effects.js` · `toast.js` · `theme-controller.js`

---

### 2.2 Authentication Pages — `login.html` / `signup.html`

**Routes:** `GET/POST /login` · `GET/POST /signup`

**Form fields:**

| Page | Field | Type | Validation |
|---|---|---|---|
| Login | Email | `email` | Required, format |
| Login | Password | `password` | Required |
| Signup | Full Name | `text` | Required, min 2 chars |
| Signup | Email | `email` | Required, format, unique |
| Signup | Password | `password` | Required, min 8 chars |
| Signup | Confirm Password | `password` | Must match password |

**UX features:**
- Flash messages rendered as styled `<ul class="auth-error-list">` above the form
- CSRF token in hidden input (`{{ csrf_token() }}`)
- SVG icon per input field for visual context
- Minimal header — no navigation, only brand + theme toggle
- Trust badges on signup page: "✓ 100% Free · ✓ 8+ Templates · ✓ ATS-Optimized"

**Redirect logic:**
- Successful login → `url_for('main.dashboard')`
- Successful signup → `url_for('main.dashboard')` (auto-logged in)
- Already authenticated → redirected away from auth pages immediately

---

### 2.3 Resume Wizard — `index.html` + `wizard-vue.js`

**Route:** `GET /dashboard` (create) · `GET /edit/<id>` (edit)

This is the most complex page. A Vue 3 application is mounted on `#vueApp`.

#### 4-Step Wizard Architecture

```
Step 1: Personal Info
  └── name, title, email, phone, address, photo (optional)

Step 2: Experience & Education
  └── experience[] → { title, company, duration, description }
  └── education[]  → { degree, university, year }
  └── AI Generate button per experience item

Step 3: Summary & Skills
  └── summary (textarea) + Auto Generate AI button
  └── skills (comma-separated text input)
  └── languages[] → { value: "English (Native)" }

Step 4: Template Selection
  └── 4 radio-button visual cards (Executive, Modern, Creative, Minimalist)
  └── Submit button → POST /generate
```

#### Vue State Object (`formData`)
```javascript
{
  resume_id: '',      // null = create, integer = update
  template: '',       // 'template1' … 'template8'
  name: '',
  title: '',
  email: '',
  phone: '',
  address: '',
  summary: '',
  skills: '',         // comma-separated string
  languages: [{ value: '' }],
  experience: [{ id, title, company, duration, description, isGenerating }],
  education:  [{ id, degree, university, year }]
}
```

#### State Flags
| Flag | Type | Purpose |
|---|---|---|
| `currentStep` | Number | Active wizard step (1–4) |
| `totalSteps` | Number | Always 4 |
| `isSaving` | Boolean | Disables submit during API call |
| `isImporting` | Boolean | Disables import button during JSON parse |
| `isGeneratingSummary` | Boolean | Shows skeleton-loader on summary textarea |
| `exp.isGenerating` | Boolean | Per-experience AI loading state |
| `errors` | Object | Field-keyed validation errors |
| `photoFile` | File | Raw file for upload |
| `photoPreviewUrl` | String | Base64 data URL for live preview |

#### Navigation Flow
```
changeStep(+1) → validateCurrentStep() → advance OR show toast error
changeStep(-1) → no validation → go back immediately
```

#### AI Integration Points in the Wizard
1. **Experience description** — `POST /api/generate-experience` with `{ title, company, duration, skills }`
2. **Professional summary** — `POST /api/generate-summary` with `{ name, title, skills }`
3. **JSON import** — client-side JSON.parse from `.json` file, calls `populateData()`

#### Form Submission Flow
```
submitForm()
  → validateCurrentStep()
  → if photoFile: POST /upload-photo → get URL
  → build payload (clean isGenerating flags, filter empty entries)
  → POST /generate (JSON)
  → on success: window.location.href = result.redirect
  → on error:   showToast(err.message, 'error')
```

#### Edit Mode Pre-fill
When `window.INITIAL_RESUME_DATA` is defined (injected by Jinja), `mounted()` calls `populateData()` to hydrate all form fields. This makes editing seamless — no separate edit form needed.

---

### 2.4 Resume View Pages — `template1.html` … `template8.html`

**Route:** `GET /resume/<id>`

These are rendered Jinja2 templates wrapped by `template_background.html`. Each template receives the full resume data dict as context variables and renders them into its unique visual layout.

**Wrapper: `template_background.html`**
- Sets `data-theme` from `localStorage` to prevent FOUC (flash of unstyled content)
- Loads `html2pdf.bundle.min.js` (CDN) for client-side PDF export
- Includes: `export_toolbar.html` · `template_switcher.html` · `global_bg.html`
- `<body>` receives `data-pdf-filename` and `data-print-mode` attributes for export logic

**Template switcher (`template_switcher.html`):**
- Scrolling horizontal pill strip showing all 8 templates (excluding current)
- Each pill submits a `POST /resume/<id>/switch-template` form to change template in-place

**Export toolbar (`export_toolbar.html`):**
- PDF: client-side via `html2pdf.js` — `document.querySelector('.resume-container')` is converted to PDF A4 with scale=2 for quality
- DOC: server-side `GET /resume/<id>/download-doc` → plain text download

---

### 2.5 Profile Page — `profile.html`

**Route:** `GET /profile`

**Hero section:** Avatar (first letter of name), user name, email, resume count stat

**Resume history grid (`.history-grid`):**
Each `resume-card` shows:
- Template badge + last updated date
- Resume title (job title)
- 4-action row: **View** · **Edit** · **JSON download** · **Delete**
- Clone row: `<select>` template dropdown + Clone button (POST to `/resume/<id>/duplicate`)

**Empty state:** Illustrative SVG + "Create First Resume" CTA when no resumes exist

---

### 2.6 AI Chat Page — `chat.html`

**Route:** `GET /chat`

**Layout:** Two-column — left sidebar (suggestion pills) + right chat window

**Sidebar suggestion pills:** Pre-written prompts (e.g., "Summary for Frontend Developer") that `applySuggestion(text)` pastes into the input on click — no click-to-submit, user can edit first.

**Chat engine (JavaScript):**
```
submitChat(e)
  → appendMessage('user', message)   // render immediately
  → showLoading()                    // typing indicator (3-dot animation)
  → POST /api/chat { message, history }
  → removeLoading()
  → appendMessage('assistant', result.data)
  → save chatHistory to sessionStorage
```

**Persistence:** `chatHistory` array persisted in `sessionStorage` as `wisaxis_chat_history` — survives page refresh but not browser close.

**Markdown rendering:** Custom `formatMarkdown()` function handles `**bold**`, `` `code` ``, `` ```blocks``` ``, and `* bullet` lists without a full markdown library.

**Copy button:** Each assistant bubble has a "Copy Content" button that calls `navigator.clipboard.writeText()`.

---

### 2.7 JSON Parser Page — `json_features.html`

**Route:** `GET /json`

**Features:**
- Drag-and-drop upload zone (visual CSS highlight on `dragenter`/`dragover`)
- File type validation client-side via `accept=".json,.pdf,.docx"`
- File name display on selection
- JSON schema example displayed in a styled code block
- Form submits to `POST /resume/process-json`

---

## 3. CSS Design System

### 3.1 Architecture (Numbered Layer System)

```
00-variables.css    ← Single source of truth for all design tokens
01-reset.css        ← Normalize + baseline
02-theme.css        ← Dark/light theme, body, template-shell
03-global-effects.css  ← Keyframes, animations, glassmorphic cards
04-global-background.css ← Layered mesh gradient background
05-components/      ← Isolated component styles (header, buttons, cards…)
06-layout/          ← Template shell layout
07-pages/           ← Page-specific overrides (home, auth, template)
09-utilities.css    ← Helpers, print mode, A4 formatting
```

**Loading order is enforced** — every page loads in this exact sequence via `<link>` tags.

### 3.2 Design Tokens

| Category | Token Example | Value |
|---|---|---|
| Brand | `--primary` | Indigo |
| Text | `--text-main`, `--text-muted` | Layered grays |
| Surface | `--surface`, `--surface-border` | Glassmorphic backgrounds |
| Spacing | `--space-1` → `--space-8` | 4px → 64px (8-pt grid) |
| Radius | `--radius-sm/md/lg/xl` | 4px → 24px |
| Z-index | `--z-header` (1200), `--z-actions` (1100) | Layering control |
| Glass | `--glass-blur` | `backdrop-filter` value |

### 3.3 Responsive Strategy

**Mobile-first breakpoints:**
| Breakpoint | Width | Strategy |
|---|---|---|
| Mobile | `< 500px` | Default — base styles apply |
| Tablet | `≥ 500px` | Progressive enhancement via `min-width` |
| Desktop | `≥ 768px` | Full layouts |
| Large | `≥ 1200px` | Max-width constraints |

The wizard uses `@media screen and (max-width: 500px)` for mobile-specific overrides — a separate mobile CSS file (`css/mobile/index.css`) is conditionally loaded with the HTML `media` attribute.

### 3.4 Theme System

Theme toggle stores the user's preference in `localStorage` under the key `wisaxis-theme`. The anti-FOUC script reads this value and sets `data-theme` on `<html>` synchronously before the page renders:

```javascript
// Inline script in <head> — runs before CSS paints
(function(){
  var t = localStorage.getItem('wisaxis-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', t);
})()
```

CSS theme variables are defined under `[data-theme="dark"]` and `[data-theme="light"]` selectors in `00-variables.css`.

---

## 4. JavaScript Modules

| File | Responsibility |
|---|---|
| `wizard-vue.js` | Complete Vue 3 resume wizard logic |
| `theme-controller.js` | Dark/light toggle + localStorage persistence |
| `toast.js` | Toast notification system (`showToast(msg, type)`) |
| `header-scroll.js` | Adds `.scrolled` class to header on scroll for glass effect |
| `global-effects.js` | Intersection Observer for `.fade-up` scroll animations |
| `carousel.js` | Pause-on-hover for template carousel |
| `template-scroll.js` | Template switcher smooth scroll behavior |
| `template-background.js` | Resume view page interactions |

---

## 5. User Dropdown Navigation

The user dropdown (`.user-dropdown`) is used on authenticated pages. It is pure vanilla JS:

```javascript
dropdownTrigger.addEventListener('click', (e) => {
  e.stopPropagation();
  const isActive = dropdownContainer.classList.toggle('active');
  dropdownTrigger.setAttribute('aria-expanded', isActive ? 'true' : 'false');
});
// Close on outside click and Escape key
```

Full ARIA compliance: `aria-haspopup`, `aria-expanded`, `role="menu"`, `role="menuitem"`.

---

## 6. Frontend Optimization Recommendations

| Priority | Recommendation | Impact |
|---|---|---|
| 🔴 High | Bundle/minify CSS into a single file for production | −40% requests |
| 🔴 High | Add `loading="lazy"` to template preview images | Faster FCP |
| 🟡 Medium | Replace CDN Vue with self-hosted + tree-shaken build | Remove ~50KB unused |
| 🟡 Medium | Add Service Worker for offline asset caching | PWA capability |
| 🟡 Medium | Auto-save wizard draft every 30s (`setInterval` + PATCH API) | Data loss prevention |
| 🟢 Low | Convert skill input to chip/tag UI | Better UX |
| 🟢 Low | Add live preview panel on wizard Step 4 | Confidence builder |
| 🟢 Low | Persist wizard state in `localStorage` (not just sessionStorage) | Cross-tab resilience |

---

## 7. Scalability Analysis

The current MPA + Vue islands architecture scales well to ~10K users without changes. For higher scale:

1. **Move to a proper SPA** (Next.js/Nuxt) for full client-side routing and code splitting
2. **Extract Vue wizard to a standalone component** — already self-contained in `wizard-vue.js`
3. **CDN for static assets** — serve CSS/images/JS from a CDN (Cloudflare, AWS CloudFront)
4. **Image optimization** — convert template preview `.webp` images to a responsive `<picture>` element

# Project Flow — WISAXIS Resume Maker

> A complete walkthrough of every user journey, data flow, and system interaction.

---

## 1. User Onboarding Flow

```
New visitor → lands on GET /
        │
        ├── Not authenticated:
        │     └── Sees home.html (landing page)
        │           → Clicks "Build My Resume" / "Get Started"
        │           → GET /signup
        │           → Fills name, email, password, confirm
        │           → POST /signup
        │                 ├── Validation fails → flash errors + stay on page
        │                 ├── Email taken → flash "Email already exists"
        │                 └── Success:
        │                       → Create User + UserSettings (db.session.commit)
        │                       → login_user(new_user)  ← auto-logged in
        │                       → 302 → GET /dashboard
        │
        └── Authenticated:
              → 302 → GET /dashboard (bypasses landing page)
```

---

## 2. Authentication Flow

### Login
```
GET  /login         → Render login.html
                    (If already logged in → redirect to /dashboard)

POST /login
  1. CSRF token validated (Flask-WTF)
  2. Rate limit checked (10/min per IP)
  3. email + password extracted from form
  4. User.query.filter_by(email=email).first()
  5. user.check_password(password) → Werkzeug hash compare
  6. If fail → "Invalid email or password" (same message always)
  7. If success:
       user.last_login_at = utcnow()
       db.session.commit()
       login_user(user, remember=True)   ← Sets session cookie
       302 → /dashboard (or ?next= param)
```

### Logout
```
GET /logout
  1. @login_required enforced
  2. logout_user()   ← Flask-Login clears session
  3. session.clear() ← Remove any remaining session data
  4. flash "See you soon, {name}!"
  5. 302 → /  (landing page)
```

---

## 3. Resume Creation Flow (Full)

```
GET /dashboard
  └── Render index.html
       └── Vue app mounts on #vueApp
            ├── currentStep = 1
            ├── formData = empty object
            └── No INITIAL_RESUME_DATA → fresh form


── STEP 1: Personal Info ──────────────────────────────────────────

User fills: name, title, email, phone, address
Optional: clicks photo upload input

  Photo upload sub-flow:
    1. User selects image file
    2. Vue: photoPreviewUrl = URL.createObjectURL(file) → live preview
    3. photoFile stored in component state
    (Photo is NOT uploaded yet — deferred until submit)

Clicks "Next" →
  validateCurrentStep() checks: name, title, email required
  Pass → currentStep = 2


── STEP 2: Experience & Education ──────────────────────────────────

User fills 1+ experience blocks: title, company, duration, description

  AI Generate sub-flow (per experience):
    1. exp.isGenerating = true → shows spinner
    2. POST /api/generate-experience { title, company, duration, skills }
    3. Headers include X-CSRFToken
    4. OpenRouter API called → returns bullet points
    5. AIHistory record inserted
    6. exp.description = result.data
    7. exp.isGenerating = false

User fills 1+ education blocks: degree, university, year

Clicks "Next" → currentStep = 3


── STEP 3: Summary & Skills ─────────────────────────────────────────

User fills summary textarea

  AI Auto Generate sub-flow:
    1. isGeneratingSummary = true → skeleton loader on textarea
    2. POST /api/generate-summary { name, title, skills }
    3. OpenRouter API called → returns paragraph
    4. formData.summary = result.data
    5. isGeneratingSummary = false

User fills skills (comma-separated text)
User adds languages (+ button adds { value: '' } to list)

Clicks "Next" → currentStep = 4


── STEP 4: Template Selection ───────────────────────────────────────

4 template cards shown (radio button style)
User clicks a card → formData.template = 'template1' (or 2/3/4)

Clicks "Generate Resume" →


── FORM SUBMISSION ──────────────────────────────────────────────────

submitForm():
  1. isSaving = true → button disabled, shows "Saving..."
  2. If photoFile:
       POST /upload-photo (FormData with photo)
       formData.photo = result.url   ← Save returned URL
  3. Build payload:
       { resume_id, template, name, title, email, phone, address,
         photo, summary, skills, languages,
         experience: [clean entries], education: [clean entries] }
  4. POST /generate { payload, headers: { X-CSRFToken } }
  5. Server:
       → Validate fields
       → Save to DB (Create or Update)
       → Snapshot if update
       → Return { success: true, redirect: "/resume/42" }
  6. window.location.href = result.redirect
  7. Browser navigates to the rendered resume page
```

---

## 4. Resume Editing Flow

```
Profile page → user clicks "Edit" on a resume card
  → GET /edit/<resume_id>
  → Server: Resume.query.filter_by(id=..., user_id=...).first_or_404()
  → Render index.html with:
       editing=True
       resume_data=resume.to_dict()
  → Jinja injects into page:
       <script>
         window.INITIAL_RESUME_DATA = {{ resume_data | tojson | safe }};
       </script>
  → Vue mounted() hook:
       if (window.INITIAL_RESUME_DATA) this.populateData(window.INITIAL_RESUME_DATA)
  → Form is pre-filled with existing data
  → formData.resume_id = existing_id
  → User edits, clicks "Save Changes"
  → POST /generate with resume_id set → triggers UPDATE path
```

---

## 5. AI Chat Flow

```
GET /chat → Render chat.html

On page load:
  chatHistory = JSON.parse(sessionStorage.getItem('wisaxis_chat_history')) || []
  Render existing chat bubbles from history

User clicks suggestion pill → applySuggestion(text) → fills message input
User types message and submits form:

submitChat(e):
  1. e.preventDefault()
  2. message = input.value.trim()
  3. if !message → return
  4. appendMessage('user', message) → render bubble immediately
  5. chatInput.value = '' → clear input
  6. showLoading() → render typing indicator dots
  7. chatHistory.push({ role: 'user', content: message })
  8. POST /api/chat { message, history: chatHistory[-10] }
       Server → AIService.chat(message, history)
                  → Build messages array: [system + history + current]
                  → POST to OpenRouter
                  → Return content
  9. removeLoading()
  10. appendMessage('assistant', result.data) → with markdown formatting
  11. chatHistory.push({ role: 'assistant', content: result.data })
  12. sessionStorage.setItem('wisaxis_chat_history', JSON.stringify(chatHistory))
```

---

## 6. Template View & Export Flow

```
After resume saved → browser navigates to GET /resume/<id>

Server:
  1. Ownership check (user_id filter)
  2. resume.to_dict() → unpacked as template context
  3. render_template('template_background.html', **data)
  4. Jinja renders: template content + header + toolbar + switcher

User sees: Full resume rendered in chosen visual template

── PDF Export ──────────────────────────────────────────────────────

User clicks Download → PDF option:
  1. pdfOption.addEventListener('click')
  2. setLoading(true) → button shows spinner
  3. element = document.querySelector('.resume-container')
  4. html2pdf().set({ margin:0, filename: body.data-pdf-filename,
                       html2canvas: { scale: 2, useCORS: true },
                       jsPDF: { unit: 'mm', format: 'a4' } })
                .from(element).save()
  5. setLoading(false)
  ← No server involved — pure client-side PDF generation

── JSON Download ────────────────────────────────────────────────────

User clicks Download → DOC option:
  → GET /resume/<id>/download
  → Server: resume.to_dict() → json.dumps(indent=2)
  → Response: Content-Disposition: attachment; filename="resume_Name.json"
  → Creates ExportHistory record
  ← Browser downloads JSON file

── Template Switch ──────────────────────────────────────────────────

User clicks a template thumbnail in the horizontal scroll strip:
  → POST /resume/<id>/switch-template { template: 'template3', csrf_token }
  → Server: _snapshot_resume(resume) → create version
             resume.template = new_template
             resume.version += 1
             db.session.commit()
  → 302 → GET /resume/<id>  (page re-renders with new template)
```

---

## 7. JSON Import Flow

```
GET /json → Render json_features.html

User drags file onto upload zone (or clicks to select):
  → JS drag events highlight zone with CSS class
  → File name displayed in UI

User clicks "Parse Resume":
  → POST /resume/process-json (multipart/form-data with file)
  → Server:
       1. Validate file type (json/pdf/docx)
       2. If JSON: json.loads(file.read())
       3. If PDF/DOCX:
            a. Save to /uploads/tmp_<uuid>.<ext>
            b. AIService.extract_resume_from_file(path, ext)
               → Extract text with pdfplumber / python-docx
               → POST to OpenRouter with extraction prompt
               → json.loads(AI response)
            c. Delete temp file
       4. session['import_data'] = parsed_dict
       5. 302 → /dashboard

On /dashboard:
  → Vue mounted() checks window.INITIAL_RESUME_DATA (set from session by Jinja)
  → populateData(data) fills all form fields
  → User reviews, edits, submits
```

---

## 8. Frontend ↔ Backend ↔ Database Communication Map

```
BROWSER                         FLASK SERVER                        SQLITE
───────                         ─────────────                       ──────

[Vue wizard]
  form submit
  ──POST /generate──────────────→ resume.py:generate()
                                    ├── validate payload
                                    ├── Resume.query.filter_by()  →→  SELECT resumes
                                    ├── Experience.query.delete()  →→  DELETE experiences
                                    ├── db.session.add(Resume)     →→  INSERT resumes
                                    ├── db.session.add(Experience) →→  INSERT experiences
                                    ├── db.session.add(Education)  →→  INSERT educations
                                    └── db.session.commit()        →→  COMMIT
  ←─{ success, redirect }──────────

[Browser navigates]
  GET /resume/42 ───────────────→ resume.py:view_resume()
                                    └── Resume.query.filter_by()  →→  SELECT + eager-load
  ←─ HTML (rendered template) ──────

[AI button click]
  ──POST /api/generate-summary──→ ai.py:generate_summary()
                                    └── AIService.generate_summary()
                                          └── POST → openrouter.ai ──→ AI API
                                          ←── content ←─────────────────
                                          └── AIHistory.add()         →→  INSERT ai_history
  ←─{ success, data }───────────────
```

---

## 9. Profile Page CRUD Flow

```
GET /profile ───────────────────→ Fetch all resumes for user
                                     Resume.query.filter_by(user_id=..., is_deleted=False)
                                     .order_by(updated_at.desc())
                                  → Render profile.html with resumes list

View:   GET /resume/<id>         → Rendered template page
Edit:   GET /edit/<id>           → Wizard pre-filled
JSON:   GET /resume/<id>/download → JSON file download
Delete: POST /resume/<id>/delete  → is_deleted=True → redirect to profile
Clone:  POST /resume/<id>/duplicate → Deep copy with new template → view new resume
```

# Security Architecture — WISAXIS Resume Maker

> This document covers every security layer in the application. Each section explains the threat being mitigated and the specific implementation.

---

## 1. Authentication Security

### 1.1 Password Hashing

**Implementation:** `werkzeug.security.generate_password_hash` / `check_password_hash`

**Algorithm chain:**
```
User password → PBKDF2 → SHA-256 → 260,000 iterations → salted hash
```

Stored format: `pbkdf2:sha256:260000$<salt>$<hash>` — the algorithm, iterations, and salt are all embedded in the stored string, making future algorithm upgrades trivial.

**Why not bcrypt?** Werkzeug's PBKDF2 implementation is part of the standard library, requires no C extensions, and is FIPS-compliant. It is appropriate for this scale. For higher security requirements, switch to bcrypt or argon2 with `passlib`.

```python
# Never store plaintext — always use these helpers
user.set_password(raw_password)       # Hashes + stores
user.check_password(raw_password)     # Returns True/False
```

### 1.2 User Enumeration Prevention

**Threat:** An attacker queries `POST /login` with different emails to discover which emails have accounts.

**Mitigation:** The login error message is always identical regardless of whether the email exists:

```python
if not user or not user.check_password(password):
    flash("Invalid email or password.", "error")  # Same message both cases
```

`check_password_hash` is always called (even when the user is `None`) via a dummy hash comparison, preventing timing attacks that could distinguish "user not found" from "wrong password" based on response time.

### 1.3 Account Lockout (Future)

Currently, rate limiting (10 req/min on `/login`) provides brute-force protection. A proper account lockout after N failed attempts can be added using `ai_history`-style tracking in a `login_attempts` table.

---

## 2. Session Security

### 2.1 Session Cookie Configuration

```python
SESSION_COOKIE_HTTPONLY = True    # JS cannot read the cookie (prevents XSS theft)
SESSION_COOKIE_SAMESITE = "Lax"  # Prevents CSRF for cross-site navigations
SESSION_COOKIE_SECURE  = True    # (production) HTTPS only
PERMANENT_SESSION_LIFETIME = timedelta(days=7)
```

**`HttpOnly`:** Prevents JavaScript (including injected XSS scripts) from reading the session cookie via `document.cookie`.

**`SameSite=Lax`:** The browser only sends the cookie with same-origin requests and top-level navigations (e.g., clicking a link). It blocks cookies being sent with cross-site POST requests — the primary CSRF vector.

**`Secure`:** Ensures the cookie is only transmitted over HTTPS in production. This is set to `False` in `DevelopmentConfig` to allow HTTP on `localhost`.

### 2.2 Session Invalidation

`logout()` calls both `logout_user()` and `session.clear()`:

```python
logout_user()    # Flask-Login clears the user session
session.clear()  # Clears any other session data (e.g., 'import_data')
```

---

## 3. CSRF Protection

### 3.1 Form-Based CSRF

Flask-WTF generates and validates a per-session CSRF token. Every HTML form includes:

```html
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

Flask-WTF automatically validates this token on all `POST`, `PUT`, `PATCH`, and `DELETE` requests.

### 3.2 AJAX/fetch() CSRF

For JavaScript fetch() calls, the token is read from a `<meta>` tag or a hidden form field:

```javascript
// From chat.html — reads from <meta name="csrf-token">
const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

// From wizard-vue.js — reads from the hidden form field
const csrfToken = document.querySelector('input[name="csrf_token"]').value;

// Sent as a custom header
fetch('/api/chat', {
    method: 'POST',
    headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history })
});
```

Flask-WTF checks `X-CSRFToken` in addition to the `csrf_token` form field — both approaches work.

### 3.3 CSRF Exemptions

The `GET /api/health` endpoint is read-only and does not need CSRF protection. Flask-WTF automatically exempts `GET` requests.

---

## 4. Horizontal Authorization (IDOR Prevention)

**Threat:** Insecure Direct Object Reference — a logged-in user changes the resume ID in the URL to access another user's resume.

**Mitigation:** Every database query for user-owned resources includes `user_id=current_user.id`:

```python
# CORRECT — always filter by user_id
resume = Resume.query.filter_by(
    id=resume_id,
    user_id=current_user.id,   # ← Ownership check
    is_deleted=False
).first_or_404()

# WRONG — never do this
resume = Resume.query.get(resume_id)  # No ownership check!
```

`first_or_404()` returns a `404` (not `403`) when the resume doesn't exist or belongs to another user. This prevents an attacker from discovering which IDs belong to other users via error code differences.

---

## 5. SQL Injection Prevention

**Implementation:** SQLAlchemy ORM with parameterized queries — all values are passed as bound parameters, never string-interpolated into SQL.

```python
# Safe — SQLAlchemy parameterizes automatically
Resume.query.filter_by(user_id=current_user.id, id=resume_id)

# Safe — explicit parameterization
db.session.execute(db.text("SELECT 1"))  # No user input in raw SQL

# NEVER do this — vulnerable to injection
db.session.execute(f"SELECT * FROM resumes WHERE id = {resume_id}")
```

The application never uses raw SQL with user-supplied data.

---

## 6. XSS Prevention

### 6.1 Jinja2 Auto-Escaping

All template variables are auto-escaped by Jinja2 by default:

```html
<!-- Safe — Jinja2 escapes < > " ' & automatically -->
<span>{{ user.name }}</span>

<!-- Explicit escape filter for extra safety -->
<span>{{ user.name | e }}</span>

<!-- Only use 'safe' filter for trusted server-generated HTML -->
<span>{{ server_generated_html | safe }}</span>
```

The application never uses `| safe` on user-supplied content.

### 6.2 Content Security Policy (Recommended)

Add these headers in production:

```python
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response
```

---

## 7. File Upload Security

Upload pipeline security layers:

```
1. File size cap: MAX_CONTENT_LENGTH = 5MB (Flask rejects larger requests with 413)
2. Extension whitelist: {jpg, jpeg, png, webp} for photos; {json, pdf, docx} for resumes
3. secure_filename(): strips path traversal characters (e.g., "../../etc/passwd.jpg" → "passwd.jpg")
4. UUID filename: uuid4().hex + ext → prevents enumeration and collisions
5. Isolated directory: files saved to instance/uploads/ — not inside the web root
6. Serve via dedicated route: /uploads/<filename> → send_from_directory()
```

**Threat mitigated by UUID filenames:** If an attacker uploaded a file named `admin.php`, `secure_filename()` preserves the name but the UUID rename makes it unreachable. The original filename is never used for storage.

---

## 8. Rate Limiting

**Library:** Flask-Limiter  
**Default:** 200 req/hour, 50 req/minute per IP

**Sensitive endpoint limits:**

| Endpoint | Limit | Threat Mitigated |
|---|---|---|
| `POST /login` | 10/min | Brute-force password attacks |
| `POST /signup` | 5/min | Account creation spam |
| `POST /generate` | 30/hour | Resume spam / DB flooding |
| AI endpoints | 10-20/hour | OpenRouter API cost abuse |
| `POST /upload-photo` | 20/hour | Storage abuse |

**429 response:**
```json
{ "success": false, "error": "Rate limit exceeded. Please wait." }
```

**Production storage:** Switch from `memory://` to `redis://` when deploying with multiple Gunicorn workers — in-memory storage does not share state between processes.

---

## 9. Environment Variable Security

**Rule:** No secrets in source code, ever.

```python
# CORRECT — read from environment
SECRET_KEY = os.environ.get("SECRET_KEY", "fallback-only-for-dev")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# WRONG — hardcoded secrets
SECRET_KEY = "my-super-secret-key"
```

**`.gitignore` must include:**
```
.env
instance/
*.db
*.log
__pycache__/
```

**Secret key generation for production:**
```bash
python -c "import secrets; print(secrets.token_hex(64))"
```

---

## 10. CORS Configuration

```python
cors.init_app(app, resources={
    r"/api/*": {"origins": app.config.get("CORS_ORIGINS", "*")}
})
```

CORS is only enabled for `/api/*` routes. HTML page routes (`/`, `/dashboard`, etc.) do not need CORS headers as they are same-origin.

In production, set `CORS_ORIGINS` to your specific domain:
```env
CORS_ORIGINS=https://yourapp.com
```

---

## 11. Production Security Checklist

| Item | Status | Action |
|---|---|---|
| `SESSION_COOKIE_SECURE=True` | ✅ (ProductionConfig) | Requires HTTPS |
| `FLASK_DEBUG=False` | ✅ (ProductionConfig) | Debug mode off |
| `SECRET_KEY` from env | ✅ | Generate 64-char random key |
| HTTPS enforced | 🔲 | Configure at reverse proxy (nginx/Caddy) |
| CSP headers | 🔲 | Add `@app.after_request` hook |
| Dependency audit | 🔲 | Run `pip-audit` in CI |
| Error pages hide stack traces | ✅ | `DEBUG=False` prevents trace exposure |
| DB backups | 🔲 | Daily backup of `instance/wisaxis.db` |
| Log monitoring | 🔲 | Set `SENTRY_DSN` in production |
| File storage isolation | ✅ | `instance/uploads/` not in web root |
| Rate limiting with Redis | 🔲 | Set `REDIS_URL` for multi-worker |

