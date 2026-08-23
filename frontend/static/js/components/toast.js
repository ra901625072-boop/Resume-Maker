/**
 * WISAXIS Resume Maker — Universal Toast Notification System
 * ==========================================================
 * Spring-based pop-in entrance, icon badges, progress timer bar,
 * queue management, and smooth dismissal.
 */

(function () {
  'use strict';

  const ICONS = {
    success: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`,
    error: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    warning: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
    info: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`
  };

  window.showToast = function (message, type = 'success', duration = 3800) {
    let container = document.querySelector('.toast-container');
    if (!container) {
      container = document.createElement('div');
      container.className = 'toast-container';
      document.body.appendChild(container);
    }

    const normalizedType = (type === 'danger' || type === 'error') ? 'error' : (type === 'warning' ? 'warning' : 'success');
    const toast = document.createElement('div');
    toast.className = `toast toast-${normalizedType}`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'polite');

    const iconWrap = document.createElement('span');
    iconWrap.className = 'toast-icon';
    iconWrap.style.display = 'inline-flex';
    iconWrap.style.alignItems = 'center';
    iconWrap.style.flexShrink = '0';
    iconWrap.innerHTML = ICONS[normalizedType] || ICONS.info;

    const msgSpan = document.createElement('span');
    msgSpan.className = 'toast-text';
    msgSpan.style.flex = '1';
    msgSpan.innerText = message;

    const closeBtn = document.createElement('button');
    closeBtn.className = 'toast-close-btn';
    closeBtn.setAttribute('aria-label', 'Close notification');
    closeBtn.style.background = 'none';
    closeBtn.style.border = 'none';
    closeBtn.style.color = 'inherit';
    closeBtn.style.opacity = '0.7';
    closeBtn.style.cursor = 'pointer';
    closeBtn.style.padding = '0 0 0 8px';
    closeBtn.style.display = 'inline-flex';
    closeBtn.style.alignItems = 'center';
    closeBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;

    toast.appendChild(iconWrap);
    toast.appendChild(msgSpan);
    toast.appendChild(closeBtn);
    container.appendChild(toast);

    let isDismissed = false;
    const dismiss = () => {
      if (isDismissed) return;
      isDismissed = true;
      toast.classList.add('toast-dismissing');
      setTimeout(() => {
        toast.remove();
        if (container && container.children.length === 0) {
          container.remove();
        }
      }, 300);
    };

    closeBtn.addEventListener('click', dismiss);

    // Auto dismiss after timer
    const timer = setTimeout(dismiss, duration);

    // Pause on hover
    toast.addEventListener('mouseenter', () => clearTimeout(timer));
    toast.addEventListener('mouseleave', () => setTimeout(dismiss, 1500));
  };

  document.addEventListener('DOMContentLoaded', () => {
    // Process any server-rendered flash messages
    const flashMessages = document.querySelectorAll(
      '.flash-messages .alert, .profile-container [style*="background: rgba(99, 102, 241, 0.1)"]'
    );

    if (flashMessages.length > 0) {
      flashMessages.forEach(msg => {
        const text = msg.innerText.trim();
        const isError =
          msg.classList.contains('alert-error') ||
          msg.classList.contains('error') ||
          msg.innerText.toLowerCase().includes('fail') ||
          msg.innerText.toLowerCase().includes('error');

        window.showToast(text, isError ? 'error' : 'success');
        msg.remove();
      });
    }
  });
})();
