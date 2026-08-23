/* ==========================================================
   WISAXIS Resume Maker — Global Cinematic Motion Interactions
   Physics-based scroll reveals, micro-interactions, ripple dynamics,
   staggered cascades, and smooth viewport choreography.
   ========================================================== */

(function () {
    'use strict';

    // 1. Cinematic Scroll & Stagger Reveal Observer
    const initScrollReveals = () => {
        const revealElements = document.querySelectorAll(
            '.cinematic-reveal, .reveal, .fade-up, .stagger-grid, .stagger-group, .features-section, .bento-grid, .history-grid'
        );

        if (revealElements.length === 0) return;

        if ('IntersectionObserver' in window) {
            const observerOptions = {
                root: null,
                rootMargin: '0px 0px -40px 0px',
                threshold: 0.06
            };

            const observer = new IntersectionObserver((entries, obs) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('active', 'visible');

                        // Auto-assign stagger delays if not already set
                        const children = entry.target.querySelectorAll(':scope > *');
                        children.forEach((child, index) => {
                            if (!child.style.transitionDelay && index < 16) {
                                child.style.transitionDelay = `${(index * 0.05).toFixed(2)}s`;
                            }
                        });

                        // Activate nested stagger groups
                        const innerStaggers = entry.target.querySelectorAll('.stagger-grid, .stagger-group');
                        innerStaggers.forEach(s => s.classList.add('active', 'visible'));

                        obs.unobserve(entry.target);
                    }
                });
            }, observerOptions);

            revealElements.forEach(el => observer.observe(el));
        } else {
            // Fallback for older browsers
            const scrollFallback = () => {
                const windowHeight = window.innerHeight;
                revealElements.forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.top < windowHeight - 40) {
                        el.classList.add('active', 'visible');
                    }
                });
            };
            window.addEventListener('scroll', scrollFallback, { passive: true });
            scrollFallback();
        }
    };

    // 2. Tactile Button Click Ripple Wave Effect
    const initRippleEffect = () => {
        document.addEventListener('click', (e) => {
            const btn = e.target.closest(
                '.btn-primary, .cta-primary, .cta-secondary, .btn-auth-submit, .btn-wizard, .ai-btn, .ai-pill-btn, .add-btn, .action-btn'
            );
            if (!btn) return;

            const rect = btn.getBoundingClientRect();
            const circle = document.createElement('span');
            const diameter = Math.max(rect.width, rect.height);
            const radius = diameter / 2;

            circle.style.width = circle.style.height = `${diameter}px`;
            circle.style.left = `${e.clientX - rect.left - radius}px`;
            circle.style.top = `${e.clientY - rect.top - radius}px`;
            circle.classList.add('button-ripple');

            // Remove existing ripple
            const existingRipple = btn.querySelector('.button-ripple');
            if (existingRipple) {
                existingRipple.remove();
            }

            btn.appendChild(circle);

            setTimeout(() => {
                circle.remove();
            }, 600);
        });
    };

    // 3. Smooth In-Page Anchor Navigation with Header Offset
    const initSmoothAnchorScroll = () => {
        document.addEventListener('click', (e) => {
            const anchor = e.target.closest('a[href^="#"]:not([href="#"])');
            if (!anchor) return;

            const targetId = anchor.getAttribute('href');
            if (!targetId || targetId === '#') return;

            const targetEl = document.querySelector(targetId);
            if (!targetEl) return;

            e.preventDefault();

            const headerHeight = document.querySelector('.app-header')?.offsetHeight || 72;
            const targetPosition = targetEl.getBoundingClientRect().top + window.pageYOffset - headerHeight - 16;

            window.scrollTo({
                top: Math.max(0, targetPosition),
                behavior: 'smooth'
            });

            // Update URL hash without jumping
            if (history.pushState) {
                history.pushState(null, null, targetId);
            }
        });
    };

    // 4. Page Entrance Triggers (Applies smooth entrance on load)
    const initPageEntrances = () => {
        const containers = document.querySelectorAll(
            '.form-container, .profile-container, .hero-inner, .auth-card, .chat-container, .json-features-container, .template-shell'
        );
        containers.forEach(container => {
            container.classList.add('page-enter');
        });
    };

    // Initialize all global motion systems
    const init = () => {
        initScrollReveals();
        initRippleEffect();
        initSmoothAnchorScroll();
        initPageEntrances();
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
