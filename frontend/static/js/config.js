/**
 * WISAXIS Resume Maker — Frontend Configuration
 */
window.API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.protocol === 'file:'
    ? 'http://127.0.0.1:5050'
    : ''; // In production, set to your backend deployment URL, e.g. 'https://wisaxis-api.onrender.com'
