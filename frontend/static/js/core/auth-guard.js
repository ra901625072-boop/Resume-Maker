/**
 * WISAXIS Resume Maker — Auth Guard & Controller
 * Handles client-side authentication checks, session caching, and redirects.
 */
(function() {
    // 1. Initial quick class application based on localStorage cache
    const isLoggedIn = localStorage.getItem('wisaxis_logged_in') === 'true';
    if (isLoggedIn) {
        document.documentElement.classList.add('user-logged-in');
        document.documentElement.classList.remove('user-logged-out');
    } else {
        document.documentElement.classList.add('user-logged-out');
        document.documentElement.classList.remove('user-logged-in');
    }

    // Apply basic styling to hide elements before class is resolved
    const style = document.createElement('style');
    style.innerHTML = `
        .auth-only, .guest-only { display: none !important; }
        .user-logged-in .auth-only { display: block !important; }
        .user-logged-in nav.desktop-nav .auth-only, 
        .user-logged-in nav.mobile-nav-pills .auth-only,
        .user-logged-in .header-actions-wrap .auth-only,
        .user-logged-in .user-dropdown .auth-only { display: inline-flex !important; }
        .user-logged-in a.auth-only { display: inline-block !important; }
        
        .user-logged-out .guest-only { display: block !important; }
        .user-logged-out nav.desktop-nav .guest-only,
        .user-logged-out nav.mobile-nav-pills .guest-only,
        .user-logged-out .header-actions-wrap .guest-only { display: inline-flex !important; }
        .user-logged-out a.guest-only { display: inline-block !important; }
    `;
    document.head.appendChild(style);

    // Apply cached username/avatar if available
    window.addEventListener('DOMContentLoaded', () => {
        const cachedName = localStorage.getItem('wisaxis_user_name');
        if (cachedName && isLoggedIn) {
            document.querySelectorAll('.js-user-name').forEach(el => el.textContent = cachedName);
            document.querySelectorAll('.js-user-avatar').forEach(el => el.textContent = cachedName[0].toUpperCase());
        }
    });

    // 2. Perform background validation against the API
    window.addEventListener('load', async () => {
        const isProtectedPage = document.body.classList.contains('protected-page');
        const isGuestOnlyPage = document.body.classList.contains('guest-page');
        
        try {
            const apiBase = window.API_BASE_URL || '';
            const res = await fetch(`${apiBase}/api/me`, {
                credentials: 'include'
            });
            
            if (res.ok) {
                const data = await res.json();
                const user = data.data;
                
                // Cache user info
                localStorage.setItem('wisaxis_logged_in', 'true');
                localStorage.setItem('wisaxis_user_name', user.name || 'User');
                localStorage.setItem('wisaxis_user_email', user.email || '');
                
                // Update classes
                document.documentElement.classList.remove('user-logged-out');
                document.documentElement.classList.add('user-logged-in');
                
                // Populate dynamic user-name/avatar elements
                document.querySelectorAll('.js-user-name').forEach(el => el.textContent = user.name);
                document.querySelectorAll('.js-user-avatar').forEach(el => el.textContent = (user.name || 'U')[0].toUpperCase());

                // Redirect if on login/signup page
                if (isGuestOnlyPage) {
                    const useHtmlExt = window.location.pathname.endsWith('.html') || window.location.protocol === 'file:';
                    window.location.href = useHtmlExt ? '/dashboard.html' : '/dashboard';
                }
            } else {
                throw new Error('Unauthorized');
            }
        } catch (err) {
            // Not authenticated / error
            localStorage.setItem('wisaxis_logged_in', 'false');
            localStorage.removeItem('wisaxis_user_name');
            localStorage.removeItem('wisaxis_user_email');
            
            document.documentElement.classList.remove('user-logged-in');
            document.documentElement.classList.add('user-logged-out');
            
            if (isProtectedPage) {
                // Clear any cached credentials
                const currentPath = window.location.pathname + window.location.search;
                const useHtmlExt = window.location.pathname.endsWith('.html') || window.location.protocol === 'file:';
                const loginPath = useHtmlExt ? '/login.html' : '/login';
                window.location.href = `${loginPath}?next=${encodeURIComponent(currentPath)}`;
            }
        }
    });
})();
