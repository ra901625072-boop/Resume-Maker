/**
 * WISAXIS Resume Maker — Header & Dropdown Controller
 * ====================================================
 * Handles scroll blur effects and global mobile/desktop dropdown menu interactions.
 */

(function () {
  'use strict';

  // 1. Header Scroll Blur Controller
  const initHeaderScroll = () => {
    const header = document.querySelector('.app-header');
    if (!header) return;

    const handleScroll = () => {
      if (window.scrollY > 30) {
        header.classList.add('scrolled');
      } else {
        header.classList.remove('scrolled');
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();
  };

  // 2. Universal Delegated Dropdown Controller
  const initDropdown = () => {
    // Click / Tap Handler with Event Delegation
    document.addEventListener('click', (e) => {
      const trigger = e.target.closest('#userDropdownBtn, .user-dropdown-trigger');

      if (trigger) {
        e.stopPropagation();
        e.preventDefault();
        const container = trigger.closest('.user-dropdown');
        if (!container) return;

        const isActive = container.classList.toggle('active');
        trigger.setAttribute('aria-expanded', isActive ? 'true' : 'false');
        return;
      }

      // Close menu if a dropdown item link is clicked
      if (e.target.closest('.dropdown-menu a, .dropdown-menu button')) {
        setTimeout(() => {
          document.querySelectorAll('.user-dropdown.active').forEach(d => {
            d.classList.remove('active');
            const btn = d.querySelector('.user-dropdown-trigger, #userDropdownBtn');
            if (btn) btn.setAttribute('aria-expanded', 'false');
          });
        }, 150);
        return;
      }

      // Click outside -> close all active dropdowns
      if (!e.target.closest('.user-dropdown')) {
        document.querySelectorAll('.user-dropdown.active').forEach(d => {
          d.classList.remove('active');
          const btn = d.querySelector('.user-dropdown-trigger, #userDropdownBtn');
          if (btn) btn.setAttribute('aria-expanded', 'false');
        });
      }
    });

    // Keyboard Escape Key Handler
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        document.querySelectorAll('.user-dropdown.active').forEach(d => {
          d.classList.remove('active');
          const btn = d.querySelector('.user-dropdown-trigger, #userDropdownBtn');
          if (btn) {
            btn.setAttribute('aria-expanded', 'false');
            btn.focus();
          }
        });
      }
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      initHeaderScroll();
      initDropdown();
    });
  } else {
    initHeaderScroll();
    initDropdown();
  }
})();
