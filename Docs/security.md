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
