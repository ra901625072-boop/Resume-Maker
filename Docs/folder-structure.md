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
│   ├── __init__.py             # Exposes all modular models for backward-compatibility.
│   ├── user.py                 # User & UserSettings models.
│   ├── resume.py               # Resume, Experience, Education, and ResumeVersion models.
│   ├── export_history.py       # ExportHistory model.
│   ├── ai_history.py           # AIHistory model.
│   └── template.py             # Template model and seeding logic.
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
└── static/                     # Publicly served assets (/static/...)
    ├── css/                    # Modular CSS Architecture
    │   ├── 00-variables.css    # Design tokens (colors, spacing, typography)
    │   ├── 01-reset.css        # Browser normalization
    │   ├── 02-theme.css        # Dark/light mode variables and body styles
    │   ├── 03-global-effects.css # Keyframe animations and glassmorphism
    │   ├── 04-global-background.css # Background layer styles
    │   ├── 05-components/      # Isolated component styles (buttons.css, header.css, etc.)
    │   ├── 06-layout/          # Structural layout styles
    │   ├── 07-pages/           # Page-specific styles (auth.css, home.css)
    │   └── 09-utilities.css    # Helper classes and print-mode specific CSS
    │
    ├── images/                 # Template preview thumbnails and logos
    ├── fonts/                  # Locally hosted fonts (empty, reserved)
    │
    └── js/                     # Client-side JavaScript
        ├── wizard-vue.js       # Core Vue 3 application logic managing the resume builder state
        ├── toast.js            # Custom toast notification system
        ├── theme-controller.js # Manages the dark/light mode toggle and localStorage
        ├── carousel.js         # Logic for the landing page template carousel
        └── ...                 # Other interaction scripts
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
