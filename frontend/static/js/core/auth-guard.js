/**
 * WISAXIS Resume Maker — Authentication Guard & Client Controller
 * ================================================================
 * Handles token storage, route protection, and dynamic nav synchronization.
 */

(function () {
    'use strict';

    const TOKEN_KEY = 'wisaxis_token';
    const USER_KEY = 'wisaxis_user';

    const AuthGuard = {
        getToken() {
            try {
                return localStorage.getItem(TOKEN_KEY) || '';
            } catch (e) {
                return '';
            }
        },

        getUser() {
            try {
                const stored = localStorage.getItem(USER_KEY);
                return stored ? JSON.parse(stored) : null;
            } catch (e) {
                return null;
            }
        },

        isAuthenticated() {
            return Boolean(this.getToken());
        },

        setAuth(token, user) {
            try {
                if (token) localStorage.setItem(TOKEN_KEY, token);
                if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
            } catch (e) {
                console.error('Failed to save auth to localStorage:', e);
            }
            this.syncUserElements();
        },

        clearAuth() {
            try {
                localStorage.removeItem(TOKEN_KEY);
                localStorage.removeItem(USER_KEY);
            } catch (e) {
                console.error('Failed to clear auth from localStorage:', e);
            }
            this.syncUserElements();
        },

        logout() {
            this.clearAuth();
            window.location.href = '/login.html';
        },

        getInitials(name) {
            if (!name) return 'U';
            const parts = name.trim().split(/\s+/);
            if (parts.length >= 2) {
                return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
            }
            return parts[0][0].toUpperCase();
        },

        syncUserElements() {
            const isAuth = this.isAuthenticated();
            const user = this.getUser() || { name: 'Account', email: '' };

            // Update user name / email / initials text
            document.querySelectorAll('.user-name, [data-user-name]').forEach(el => {
                el.textContent = isAuth ? (user.name || 'User') : 'Account';
            });

            document.querySelectorAll('.user-email, [data-user-email]').forEach(el => {
                el.textContent = isAuth ? (user.email || '') : '';
            });

            document.querySelectorAll('.user-initials, [data-user-initials]').forEach(el => {
                el.textContent = isAuth ? this.getInitials(user.name) : 'U';
            });

            // Update auth-dependent elements
            document.querySelectorAll('[data-show-auth]').forEach(el => {
                el.style.display = isAuth ? '' : 'none';
            });

            document.querySelectorAll('[data-show-guest]').forEach(el => {
                el.style.display = isAuth ? 'none' : '';
            });

            // Wire up any explicit logout buttons
            document.querySelectorAll('.btn-logout, [data-action="logout"]').forEach(btn => {
                btn.onclick = (e) => {
                    e.preventDefault();
                    this.logout();
                };
            });
        },

        initGuard() {
            const path = window.location.pathname.toLowerCase();
            const isAuth = this.isAuthenticated();

            const isAuthPage = path.endsWith('/login.html') ||
                               path.endsWith('/login') ||
                               path.endsWith('/signup.html') ||
                               path.endsWith('/signup');

            const isProtectedPage = path.endsWith('/dashboard.html') ||
                                    path.endsWith('/dashboard') ||
                                    path.endsWith('/profile.html') ||
                                    path.endsWith('/profile') ||
                                    path.endsWith('/chat.html') ||
                                    path.endsWith('/chat') ||
                                    path.endsWith('/json.html') ||
                                    path.endsWith('/json') ||
                                    path.endsWith('/resume.html') ||
                                    path.endsWith('/resume');

            if (isProtectedPage && !isAuth) {
                const next = encodeURIComponent(window.location.pathname + window.location.search);
                window.location.replace(`/login.html?next=${next}`);
            } else if (isAuthPage && isAuth) {
                const urlParams = new URLSearchParams(window.location.search);
                const next = urlParams.get('next') || '/dashboard';
                window.location.replace(next.startsWith('/') ? next : '/dashboard');
            }
        }
    };

    window.AuthGuard = AuthGuard;

    // Run guard check immediately to minimize unauthenticated content flashing
    AuthGuard.initGuard();

    // Sync user details on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => AuthGuard.syncUserElements());
    } else {
        AuthGuard.syncUserElements();
    }
})();
