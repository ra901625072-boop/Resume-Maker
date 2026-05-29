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

    // 3. Secure Logout Interception
    const logoutLinks = document.querySelectorAll('a[href*="/logout"]');
    logoutLinks.forEach(link => {
        link.addEventListener('click', async (e) => {
            e.preventDefault();
            
            // 1. Clear all client-side authentication/state storage immediately
            localStorage.clear();
            sessionStorage.clear();
            
            // 2. Clear Vue/JS cached data if any
            if (window.INITIAL_RESUME_DATA) window.INITIAL_RESUME_DATA = null;
            
            // 3. Execute secure POST logout
            // Try form input first, then meta tag, then proceed without CSRF (server exempt)
            const csrfInput = document.querySelector('input[name="csrf_token"]');
            const csrfMeta = document.querySelector('meta[name="csrf-token"]');
            const csrfToken = (csrfInput ? csrfInput.value : null) || (csrfMeta ? csrfMeta.getAttribute('content') : '') || '';
            
            try {
                const response = await fetch('/logout', {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrfToken,
                        'Content-Type': 'application/json'
                    }
                });
                
                if (!response.ok) {
                    throw new Error('POST logout failed, falling back to GET');
                }
                
                // 4. Force hard redirect to home with cache-busting parameter
                // This guarantees the browser fetches the fresh unauthenticated state
                window.location.href = '/?t=' + new Date().getTime();
            } catch (err) {
                // Fallback to standard GET logout if network error occurs
                window.location.href = '/logout?t=' + new Date().getTime();
            }
        });
    });
});
