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
