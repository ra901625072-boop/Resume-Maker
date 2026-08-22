/**
 * WISAXIS Resume Maker — Frontend Configuration
 */
window.API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.protocol === 'file:'
    ? 'http://127.0.0.1:5050'
    : 'https://resume-maker-8ljc.onrender.com';
