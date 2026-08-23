/**
 * WISAXIS Resume Maker — Header & Dropdown Controller
 * ====================================================
 * Handles scroll blur effects and global mobile/desktop dropdown menu interactions.
 */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Header scroll effect
  const header = document.querySelector('.app-header');
  if (header) {
    const handleScroll = () => {
      if (window.scrollY > 30) {
        header.classList.add('scrolled');
      } else {
        header.classList.remove('scrolled');
      }
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();
  }

  // 2. Global Dropdown Menu Controller
  const dropdownTrigger = document.getElementById('userDropdownBtn') || document.querySelector('.user-dropdown-trigger');
  const dropdownContainer = document.querySelector('.user-dropdown');

  if (dropdownTrigger && dropdownContainer) {
    const toggleMenu = (e) => {
      e.stopPropagation();
      const isActive = dropdownContainer.classList.toggle('active');
      dropdownTrigger.setAttribute('aria-expanded', isActive ? 'true' : 'false');
    };

    const closeMenu = () => {
      if (dropdownContainer.classList.contains('active')) {
        dropdownContainer.classList.remove('active');
        dropdownTrigger.setAttribute('aria-expanded', 'false');
      }
    };

    // Toggle on trigger click
    dropdownTrigger.addEventListener('click', toggleMenu);

    // Close on click outside
    document.addEventListener('click', (e) => {
      if (!dropdownContainer.contains(e.target)) {
        closeMenu();
      }
    });

    // Close on escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeMenu();
      }
    });

    // Close on clicking any link inside dropdown
    dropdownContainer.querySelectorAll('a, button').forEach(item => {
      item.addEventListener('click', () => {
        // Small delay to allow navigation
        setTimeout(closeMenu, 150);
      });
    });
  }
});
