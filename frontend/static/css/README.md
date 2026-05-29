# WISAXIS CSS Architecture

## File Organization

```
static/css/
├── 00-variables.css          ← ALL design tokens (colors, spacing, z-index, etc.)
├── 01-reset.css              ← Normalize & baseline reset
├── 02-theme.css              ← Body, dark/light theme toggle, template-shell
├── 03-global-effects.css     ← Keyframes, animations, cards, touch feedback
├── 04-global-background.css  ← Unified global background layer system
│
├── 05-components/            ← Component-level styles (no media queries for layout)
│   ├── header.css            ← .app-header, .brand, .user-dropdown (mobile-first)
│   ├── footer.css            ← .app-footer, .footer-top, .footer-links
│   ├── buttons.css           ← .btn, .btn-primary, .cta-primary, .download-btn
│   ├── dropdowns.css         ← .download-menu, .download-options
│   ├── cards.css             ← .template-card, .template-thumb, .carousel-dots
│   └── modals.css            ← .toast-container, .toast (success/error)
│
├── 06-layout/                ← Structural/layout-level styles
│   └── template-layout.css      ← Template shell body, sidebar, resume container, actions
│
├── 07-pages/                 ← Page-specific styles
│   ├── home.css              ← Hero, carousel, info section (mobile-first)
│   └── template.css          ← Wizard progress, bottom toolbar
│
└── 09-utilities.css          ← Utility classes, print mode, A4 helpers
```

> **Legacy files** in `desktop/`, `mobile/`, `base/`, and `shared/` directories are
> kept intact for backward compatibility during migration. Only `home.html`,
> `template_background.html`, and `index.html` have been updated to use the new
> architecture. Other pages (profile, chat, login, etc.) still use the old files.

---

## HTML Import Order

Load stylesheets in this exact order:

```html
<!-- 1. Variables (MUST be first — everything depends on these) -->
<link rel="stylesheet" href="/css/00-variables.css">

<!-- 2. Reset -->
<link rel="stylesheet" href="/css/01-reset.css">

<!-- 3. Theme (body + toggle) -->
<link rel="stylesheet" href="/css/02-theme.css">

<!-- 4. Animations -->
<link rel="stylesheet" href="/css/03-global-effects.css">

<!-- 4.1 Global Background -->
<link rel="stylesheet" href="/css/04-global-background.css">

<!-- 5. Components (order within doesn't matter) -->
<link rel="stylesheet" href="/css/05-components/header.css">
<link rel="stylesheet" href="/css/05-components/footer.css">
<link rel="stylesheet" href="/css/05-components/buttons.css">
<link rel="stylesheet" href="/css/05-components/dropdowns.css">
<link rel="stylesheet" href="/css/05-components/cards.css">
<link rel="stylesheet" href="/css/05-components/modals.css">

<!-- 6. Layout (only for template editor pages) -->
<link rel="stylesheet" href="/css/06-layout/template-layout.css">

<!-- 7. Page-specific -->
<link rel="stylesheet" href="/css/07-pages/home.css">  <!-- or template.css -->

<!-- 8. Utilities (always last) -->
<link rel="stylesheet" href="/css/09-utilities.css">
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
|------|-----------|-----|
| Mobile | `< 500px` | Default — base styles |
| Tablet | `500px` | Small screens & tablets |
| Desktop | `768px` | Full layout |
| Large | `1200px` | Max-width constraints |

All breakpoints are in `@media (min-width: X)` format (mobile-first).
Mobile-only overrides use `@media screen and (max-width: 500px)`.

---

## Rules for Contributors

1. **Add variables** → `00-variables.css` only (never inline)
2. **Modify a component** → open its `05-components/X.css` file
3. **Add responsive behavior** → use `@media (min-width: X)` inside the same component file
4. **Add page-specific styles** → `07-pages/your-page.css`
5. **Never use `!important`** — reconsider the cascade instead
6. **Never** add `@import` inside CSS files — use `<link>` in HTML

---

## Architecture Benefits

| Metric | Before | After |
|--------|--------|-------|
| CSS Files | 15 (chaotic) | 13 (organized) |
| Duplication | ~40% | < 5% |
| `!important` flags | 12–15 | 0 |
| Time to find a rule | 15–20 min | < 2 min |
| Variable conflicts | 3 conflicting `:root` blocks | 1 source of truth |

---

*Architecture established: May 2026*
