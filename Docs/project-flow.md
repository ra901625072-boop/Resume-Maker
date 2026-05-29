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
