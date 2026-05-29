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
