/**
 * WISAXIS Resume Maker — API Client
 * =================================
 * Centralized fetch client that:
 * 1. Automatically prefixes relative paths with window.API_BASE_URL
 * 2. Injects the Bearer Authorization header from AuthGuard
 * 3. Handles standard JSON content-type and FormData payloads
 * 4. Catches 401 Unauthorized responses and redirects to /login.html
 */

(function () {
    'use strict';

    async function apiFetch(path, options = {}) {
        const apiBase = window.API_BASE_URL || '';
        let url = path;

        if (path.startsWith('/') && !path.startsWith('//')) {
            url = `${apiBase}${path}`;
        }

        const headers = Object.assign({}, options.headers || {});

        // Attach Bearer token if available
        if (window.AuthGuard && typeof window.AuthGuard.getToken === 'function') {
            const token = window.AuthGuard.getToken();
            if (token && !headers['Authorization'] && !headers['authorization']) {
                headers['Authorization'] = `Bearer ${token}`;
            }
        }

        // Set Content-Type to JSON if body is a plain object or string and not FormData
        let body = options.body;
        if (body && typeof body === 'object' && !(body instanceof FormData) && !(body instanceof Blob)) {
            if (!headers['Content-Type'] && !headers['content-type']) {
                headers['Content-Type'] = 'application/json';
            }
            body = JSON.stringify(body);
        }

        const fetchOptions = Object.assign({}, options, {
            headers: headers,
            body: body
        });

        try {
            const response = await fetch(url, fetchOptions);

            // If unauthorized and not already on an auth page, redirect to login
            if (response.status === 401) {
                const currentPath = window.location.pathname.toLowerCase();
                const isAuthPage = currentPath.endsWith('login.html') ||
                                   currentPath.endsWith('signup.html') ||
                                   currentPath.endsWith('login') ||
                                   currentPath.endsWith('signup');

                if (!isAuthPage) {
                    if (window.AuthGuard && typeof window.AuthGuard.clearAuth === 'function') {
                        window.AuthGuard.clearAuth();
                    }
                    const next = encodeURIComponent(window.location.pathname + window.location.search);
                    window.location.href = `/login.html?next=${next}`;
                    return response;
                }
            }

            return response;
        } catch (err) {
            console.error(`API Fetch Error [${options.method || 'GET'} ${url}]:`, err);
            throw err;
        }
    }

    window.apiFetch = apiFetch;
    window.ApiClient = { fetch: apiFetch };
})();
