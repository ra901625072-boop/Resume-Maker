// theme-controller.js — Production version
(function() {
  const STORAGE_KEY = 'wisaxis-theme';
  const SYSTEM_PREFERS_DARK = window.matchMedia('(prefers-color-scheme: dark)');

  function getInitialTheme() {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return stored;
    return SYSTEM_PREFERS_DARK.matches ? 'dark' : 'light';
  }

  function applyTheme(theme) {
    const html = document.documentElement;
    const toggle = document.getElementById('theme-toggle');

    if (theme === 'light') {
      html.setAttribute('data-theme', 'light');
      if (toggle) toggle.setAttribute('aria-pressed', 'true');
    } else {
      html.removeAttribute('data-theme');
      if (toggle) toggle.setAttribute('aria-pressed', 'false');
    }

    localStorage.setItem(STORAGE_KEY, theme);
  }

  // Initialize
  applyTheme(getInitialTheme());

  // Toggle handler
  document.addEventListener('DOMContentLoaded', () => {
    // Re-apply to synchronize the theme toggle button state upon DOM load
    applyTheme(getInitialTheme());

    const toggle = document.getElementById('theme-toggle');
    if (!toggle) return;

    toggle.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme');
      applyTheme(current === 'light' ? 'dark' : 'light');
    });
  });

  // Listen for system changes
  SYSTEM_PREFERS_DARK.addEventListener('change', (e) => {
    if (!localStorage.getItem(STORAGE_KEY)) {
      applyTheme(e.matches ? 'dark' : 'light');
    }
  });
})();
