/* ==========================================================
   WISAXIS Resume Maker — Global Cinematic Motion Interactions
   ========================================================== */

document.addEventListener('DOMContentLoaded', () => {
    // 1. Cinematic Scroll & Stagger Reveal Observer (High Performance)
    const revealElements = document.querySelectorAll(
        '.cinematic-reveal, .reveal, .fade-up, .stagger-grid, .stagger-group, .features-section'
    );

    if (revealElements.length > 0) {
        if ('IntersectionObserver' in window) {
            const observerOptions = {
                root: null, // viewport
                rootMargin: '0px 0px -60px 0px', // trigger smoothly before entering viewport
                threshold: 0.08 // trigger when 8% of the element is visible
            };

            const observer = new IntersectionObserver((entries, obs) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('active', 'visible');
                        // Also activate inner stagger grids if present
                        const innerStaggers = entry.target.querySelectorAll('.stagger-grid, .stagger-group');
                        innerStaggers.forEach(s => s.classList.add('active', 'visible'));
                        // Unobserve immediately after reveal to save CPU/GPU cycles
                        obs.unobserve(entry.target);
                    }
                });
            }, observerOptions);

            revealElements.forEach(el => observer.observe(el));
        } else {
            // High-performance fallback for older platforms
            const scrollRevealFallback = () => {
                revealElements.forEach(el => {
                    const rect = el.getBoundingClientRect();
                    const windowHeight = window.innerHeight;
                    if (rect.top < windowHeight - 60) {
                        el.classList.add('active', 'visible');
                    }
                });
            };

            window.addEventListener('scroll', scrollRevealFallback, { passive: true });
            scrollRevealFallback(); // Initial trigger
        }
    }

    // 2. Cinematic Entrance Triggers (Applies page-enter on load)
    const mainContainers = document.querySelectorAll('.form-container, .profile-container, .hero-inner, .auth-card');
    mainContainers.forEach(container => {
        container.classList.add('page-enter');
    });
});

