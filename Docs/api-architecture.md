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
