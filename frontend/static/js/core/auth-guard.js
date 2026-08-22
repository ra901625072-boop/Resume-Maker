/**
 * WISAXIS Resume Maker — Auth Guard & Controller (v2.0)
 * ======================================================
 * Universal authentication manager supporting:
 *   - Bearer Token & Session dual-authentication
 *   - Transparent Fetch Interceptor with auto Authorization headers
 *   - Optimistic Zero-Flicker page rendering
 *   - Automatic background session validation & user profile sync
 *   - Protected page routing and return-to-next redirect handling
 */

(function() {
    'use strict';

    const TOKEN_KEY = 'wisaxis_auth_token';
    const USER_KEY = 'wisaxis_user';
    const LOGGED_IN_KEY = 'wisaxis_logged_in';
    const USER_NAME_KEY = 'wisaxis_user_name';
    const USER_EMAIL_KEY = 'wisaxis_user_email';

    // ────────────────────────────────────────────────────────────────────────
    // AuthGuard Object API
    // ────────────────────────────────────────────────────────────────────────
    const AuthGuard = {
        getToken() {
            return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY) || '';
        },

        getUser() {
            try {
                const userJson = localStorage.getItem(USER_KEY) || sessionStorage.getItem(USER_KEY);
                if (userJson) return JSON.parse(userJson);
            } catch (e) {
                // Ignore parse errors
            }
            const fallbackName = localStorage.getItem(USER_NAME_KEY) || 'User';
            const fallbackEmail = localStorage.getItem(USER_EMAIL_KEY) || '';
            return { name: fallbackName, email: fallbackEmail };
        },

        isAuthenticated() {
            return !!this.getToken();
        },

        setAuth(token, user = {}, remember = true) {
            const storage = remember ? localStorage : sessionStorage;
            const otherStorage = remember ? sessionStorage : localStorage;

            // Clear opposite storage to avoid desync
            otherStorage.removeItem(TOKEN_KEY);
            otherStorage.removeItem(USER_KEY);

            if (token) {
                storage.setItem(TOKEN_KEY, token);
            }

            if (user && typeof user === 'object') {
                storage.setItem(USER_KEY, JSON.stringify(user));
                if (user.name) localStorage.setItem(USER_NAME_KEY, user.name);
                if (user.email) localStorage.setItem(USER_EMAIL_KEY, user.email);
            }

            localStorage.setItem(LOGGED_IN_KEY, 'true');

            // Apply classes
            document.documentElement.classList.remove('user-logged-out');
            document.documentElement.classList.add('user-logged-in');

            // Update UI elements
            this.syncUserElements(user);
        },

        clearAuth() {
            localStorage.removeItem(TOKEN_KEY);
            localStorage.removeItem(USER_KEY);
            localStorage.setItem(LOGGED_IN_KEY, 'false');
            localStorage.removeItem(USER_NAME_KEY);
            localStorage.removeItem(USER_EMAIL_KEY);

            sessionStorage.removeItem(TOKEN_KEY);
            sessionStorage.removeItem(USER_KEY);

            document.documentElement.classList.remove('user-logged-in');
            document.documentElement.classList.add('user-logged-out');
        },

        async logout(redirectUrl = '/login') {
            const apiBase = window.API_BASE_URL || '';
            const token = this.getToken();

            try {
                if (token) {
                    await fetch(`${apiBase}/logout`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`
                        },
                        credentials: 'include'
                    });
                }
            } catch (e) {
                // Ignore network errors during logout
            } finally {
                this.clearAuth();
                if (window.showToast) {
                    window.showToast('You have been signed out.', 'info');
                }
                setTimeout(() => {
                    window.location.href = redirectUrl;
                }, 300);
            }
        },

        syncUserElements(user) {
            const u = user || this.getUser();
            const name = u.name || 'User';
            const initial = (name.trim()[0] || 'U').toUpperCase();

            document.querySelectorAll('.js-user-name').forEach(el => {
                el.textContent = name;
            });
            document.querySelectorAll('.js-user-avatar').forEach(el => {
                el.textContent = initial;
            });
            document.querySelectorAll('.js-user-email').forEach(el => {
                el.textContent = u.email || '';
            });
        }
    };

    // Expose globally
    window.AuthGuard = AuthGuard;

    // ────────────────────────────────────────────────────────────────────────
    // Step 1: Immediate Optimistic Styling (Before DOM Renders)
    // ────────────────────────────────────────────────────────────────────────
    const hasToken = AuthGuard.isAuthenticated();
    if (hasToken) {
        document.documentElement.classList.add('user-logged-in');
        document.documentElement.classList.remove('user-logged-out');
    } else {
        document.documentElement.classList.add('user-logged-out');
        document.documentElement.classList.remove('user-logged-in');
    }

    // Dynamic style sheet to hide/show auth-only & guest-only elements instantly
    const styleEl = document.createElement('style');
    styleEl.id = 'auth-guard-styles';
    styleEl.innerHTML = `
        .auth-only, .guest-only { display: none !important; }
        .user-logged-in .auth-only { display: block !important; }
        .user-logged-in nav.desktop-nav .auth-only,
        .user-logged-in nav.mobile-nav-pills .auth-only,
        .user-logged-in .header-actions-wrap .auth-only,
        .user-logged-in .user-dropdown,
        .user-logged-in .user-dropdown .auth-only { display: inline-flex !important; }
        .user-logged-in a.auth-only { display: inline-block !important; }
        
        .user-logged-out .user-dropdown { display: none !important; }
        .user-logged-out .guest-only { display: block !important; }
        .user-logged-out nav.desktop-nav .guest-only,
        .user-logged-out nav.mobile-nav-pills .guest-only,
        .user-logged-out .header-actions-wrap .guest-only { display: inline-flex !important; }
        .user-logged-out a.guest-only { display: inline-block !important; }
    `;
    if (document.head) {
        document.head.appendChild(styleEl);
    } else {
        document.addEventListener('DOMContentLoaded', () => document.head.appendChild(styleEl));
    }

    // ────────────────────────────────────────────────────────────────────────
    // Step 2: Transparent Fetch Interceptor (Attaches Bearer Token automatically)
    // ────────────────────────────────────────────────────────────────────────
    const originalFetch = window.fetch;
    window.fetch = async function(resource, init = {}) {
        const token = AuthGuard.getToken();
        const options = { ...init };

        // Ensure credentials include for cross-origin cookies if supported
        if (options.credentials === undefined) {
            options.credentials = 'include';
        }

        // Attach Authorization header if token exists and not explicitly overridden
        if (token) {
            if (options.headers instanceof Headers) {
                if (!options.headers.has('Authorization')) {
                    options.headers.set('Authorization', `Bearer ${token}`);
                }
            } else if (Array.isArray(options.headers)) {
                const hasAuth = options.headers.some(([k]) => k.toLowerCase() === 'authorization');
                if (!hasAuth) {
                    options.headers.push(['Authorization', `Bearer ${token}`]);
                }
            } else {
                options.headers = {
                    ...options.headers,
                    'Authorization': `Bearer ${token}`
                };
            }
        }

        try {
            const response = await originalFetch.call(this, resource, options);

            // If a protected API call returned 401 Unauthorized
            if (response.status === 401) {
                const isProtectedPage = document.body && document.body.classList.contains('protected-page');
                const isGuestPage = document.body && document.body.classList.contains('guest-page');

                // If on a protected page, clear expired auth and redirect
                if (isProtectedPage && !isGuestPage) {
                    AuthGuard.clearAuth();
                    const currentPath = window.location.pathname + window.location.search;
                    window.location.href = `/login?next=${encodeURIComponent(currentPath)}`;
                }
            }

            return response;
        } catch (err) {
            throw err;
        }
    };

    // ────────────────────────────────────────────────────────────────────────
    // Step 3: DOM Content Loaded Initializer
    // ────────────────────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        // Sync cached user to DOM elements
        AuthGuard.syncUserElements();

        // Attach logout interceptor to all logout buttons and links
        document.querySelectorAll('a[href="/logout"], .js-logout-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                AuthGuard.logout('/login');
            });
        });
    });

    // ────────────────────────────────────────────────────────────────────────
    // Step 4: Background Session & Token Validation
    // ────────────────────────────────────────────────────────────────────────
    async function validateAuth() {
        const isProtectedPage = document.body && document.body.classList.contains('protected-page');
        const isGuestOnlyPage = document.body && document.body.classList.contains('guest-page');
        const token = AuthGuard.getToken();

        // 1. If on protected page without a token, redirect immediately to login
        if (isProtectedPage && !token) {
            AuthGuard.clearAuth();
            const currentPath = window.location.pathname + window.location.search;
            window.location.href = `/login?next=${encodeURIComponent(currentPath)}`;
            return;
        }

        // 2. If token exists, verify with backend /api/me
        if (token) {
            try {
                const apiBase = window.API_BASE_URL || '';
                const res = await originalFetch(`${apiBase}/api/me`, {
                    headers: {
                        'Authorization': `Bearer ${token}`
                    },
                    credentials: 'include'
                });

                if (res.ok) {
                    const data = await res.json();
                    if (data.success && data.data) {
                        // Refresh user cache
                        AuthGuard.setAuth(token, data.data);

                        // If user is currently on login or signup page, redirect to destination
                        if (isGuestOnlyPage) {
                            const urlParams = new URLSearchParams(window.location.search);
                            const next = urlParams.get('next');
                            window.location.href = (next && next.startsWith('/')) ? next : '/dashboard';
                        }
                        return;
                    }
                }

                // If /api/me returned unauthorized (invalid/expired token)
                if (res.status === 401 || res.status === 403) {
                    AuthGuard.clearAuth();
                    if (isProtectedPage) {
                        const currentPath = window.location.pathname + window.location.search;
                        window.location.href = `/login?next=${encodeURIComponent(currentPath)}`;
                    }
                }
            } catch (err) {
                // If offline or network unreachable, keep optimistic state if on protected page
                console.warn('Auth validation network error:', err);
            }
        }
    }

    // Run validation after DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', validateAuth);
    } else {
        validateAuth();
    }

})();
