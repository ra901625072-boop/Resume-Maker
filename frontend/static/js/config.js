/**
 * WISAXIS Resume Maker — Frontend Configuration
 *
 * In production, Vercel rewrites proxy /api/*, /login, /signup, etc. to the
 * Render backend, so the browser only ever talks to the Vercel domain —
 * making session cookies first-party.  API_BASE_URL is therefore '' (relative).
 *
 * The only exception is opening raw .html files via file:// protocol (local
 * double-click), where we need the full backend URL.
 */
window.API_BASE_URL = window.location.protocol === 'file:'
    ? 'http://127.0.0.1:5050'
    : '';
