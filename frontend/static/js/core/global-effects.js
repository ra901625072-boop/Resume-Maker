/* ==========================================================
   WISAXIS Resume Maker — Global Cinematic Motion Interactions
   ========================================================== */

document.addEventListener('DOMContentLoaded', () => {
    // 1. Cinematic Scroll Reveal Observer (Highly Performant)
    const revealElements = document.querySelectorAll('.cinematic-reveal, .reveal, .fade-up');

    if (revealElements.length > 0) {
        if ('IntersectionObserver' in window) {
            const observerOptions = {
                root: null, // viewport
                rootMargin: '0px 0px -80px 0px', // trigger slightly before entering viewport
                threshold: 0.1 // trigger when 10% of the element is visible
            };

            const observer = new IntersectionObserver((entries, observer) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('active');
                        // Unobserve immediately after reveal to save CPU/GPU cycles
                        observer.unobserve(entry.target);
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
                    if (rect.top < windowHeight - 80) {
                        el.classList.add('active');
                    }
                });
            };

            window.addEventListener('scroll', scrollRevealFallback);
            scrollRevealFallback(); // Initial trigger
        }
    }

    // 2. Cinematic Entrance Triggers (Applies page-enter on load)
    const mainContainers = document.querySelectorAll('.form-container, .profile-container, .hero-inner');
    mainContainers.forEach(container => {
        container.classList.add('page-enter');
    });
});
