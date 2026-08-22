# WISAXIS CSS Architecture

This folder contains the styling system for the WISAXIS Resume Maker. The architecture follows a modular, mobile-first design token-driven system.

## File Organization

```
static/css/
├── base/                     ← Core baseline tokens and structural foundations
│   ├── variables.css         ← ALL design tokens (colors, spacing, z-index, typography, HSL values)
│   ├── reset.css             ← Reset and normalize browser styling baselines
│   ├── theme.css             ← Core theme (body styling, dark/light theme, toggle shell)
│   ├── effects.css           ← Global keyframes, hover animations, shadow levels, transitions
│   └── background.css        ← Unified background grid patterns and gradient layer effects
│
├── components/               ← Component-level styles (self-contained, reusable, no layout-level constraints)
│   ├── header.css            ← Navbar, logo branding, and user dropdown elements
│   ├── footer.css            ← Footers and social links
│   ├── buttons.css           ← Buttons, pill styling, CTAs, loading states
│   ├── dropdowns.css         ← Selection menus and download dropdowns
│   ├── cards.css             ← Resume cards, preview thumbnails, and hover grids
│   └── modals.css            ← Notifications, alerts, popups, and toast messages
│
├── layout/                   ← Structural/layout-level systems
│   └── template-layout.css   ← Grid shells, sidebars, print sheet containers, toolbar layouts
│
├── pages/                    ← Page-specific layout structures
│   ├── auth.css              ← Login & signup screen layouts
│   ├── home.css              ← Hero sections, template carousels, and landing grids
│   ├── template.css          ← Wizard steps, inputs, and form controls
│   ├── chat-desktop.css      ← Desktop-specific layout for AI assistant page
│   ├── chat-mobile.css       ← Mobile-specific layout for AI assistant page
│   ├── dashboard-desktop.css ← Desktop-specific wizard UI
│   ├── dashboard-mobile.css  ← Mobile-specific wizard UI
│   ├── profile-desktop.css   ← Desktop history / profile UI
│   └── profile-mobile.css    ← Mobile history / profile UI
│
├── resumes/                  ← Resume templates styling sheets
│   ├── desktop/              ← Desktop layouts for templates 1–8
│   │   ├── template1.css ... template8.css
│   │
│   └── mobile/               ← Mobile-optimized layouts for templates 1–8
│       ├── template1.css ... template8.css
│
└── utilities/                ← Utility helper classes
    └── utilities.css         ← Margin/padding helpers, print helpers, A4 page size handlers
```

---

## HTML Import Order

Load stylesheets in this exact order:

```html
<!-- 1. Base files (MUST be first) -->
<link rel="stylesheet" href="/static/css/base/variables.css">
<link rel="stylesheet" href="/static/css/base/reset.css">
<link rel="stylesheet" href="/static/css/base/theme.css">
<link rel="stylesheet" href="/static/css/base/effects.css">
<link rel="stylesheet" href="/static/css/base/background.css">

<!-- 2. Components (order within components doesn't matter) -->
<link rel="stylesheet" href="/static/css/components/header.css">
<link rel="stylesheet" href="/static/css/components/buttons.css">
<link rel="stylesheet" href="/static/css/components/cards.css">
<link rel="stylesheet" href="/static/css/components/dropdowns.css">
<link rel="stylesheet" href="/static/css/components/modals.css">

<!-- 3. Layout (only for layout containers) -->
<link rel="stylesheet" href="/static/css/layout/template-layout.css">

<!-- 4. Page-Specific / Legacy -->
<link rel="stylesheet" href="/static/css/pages/home.css">

<!-- 5. Utilities (always last) -->
<link rel="stylesheet" href="/static/css/utilities/utilities.css">
```

---

## Variable Naming Convention

| Token | Use |
|-------|-----|
| `--text-main` | Primary body text |
| `--text-muted` | Secondary / subdued text |
| `--text-inverse` | Text on colored backgrounds |
| `--primary` | Brand color (indigo) |
| `--primary-hover` | Interactive state of primary |
| `--secondary` | Success / emerald |
| `--accent` | Highlight / amber |
| `--danger` | Error / red |
| `--surface` | Glassmorphic panel background |
| `--surface-border` | Panel/card border |
| `--glass-blur` | Backdrop-filter value |
| `--space-1` … `--space-8` | 8pt spacing grid (4px–64px) |
| `--radius-sm/md/lg/xl` | Border radius scale |
| `--z-header` | z-index for sticky header (1200) |
| `--z-actions` | z-index for action bar (1100) |
| `--z-template-scroll` | z-index for sidebar (500) |

---

## Breakpoints (Mobile-First)

| Name | Min-Width | Use |
|-------|-----------|-----|
| Mobile | `< 500px` | Default — base styles |
| Tablet | `500px` | Small screens & tablets |
| Desktop | `768px` | Full layout |
| Large | `1200px` | Max-width constraints |

All breakpoints are in `@media (min-width: X)` format (mobile-first).
Mobile-only overrides use `@media screen and (max-width: 500px)`.

---

## Rules for Contributors

1. **Add variables** &rarr; `base/variables.css` only (never inline).
2. **Modify a component** &rarr; open its corresponding `components/X.css` file.
3. **Add responsive behavior** &rarr; use `@media (min-width: X)` inside the same component file.
4. **Add page-specific styles** &rarr; `pages/your-page.css`.
5. **Never use `!important`** — reconsider the cascade instead.
6. **Never** add `@import` inside CSS files — use `<link>` in HTML.
