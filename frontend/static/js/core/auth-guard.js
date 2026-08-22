/**
 * WISAXIS Resume Maker — Client Controller (Open Access)
 * =======================================================
 * Auth restrictions removed: All pages and API endpoints are directly accessible.
 */

(function() {
    'use strict';

    const AuthGuard = {
        getToken() { return ''; },
        getUser() { return { name: 'User', email: '' }; },
        isAuthenticated() { return true; },
        setAuth() {},
        clearAuth() {},
        logout() {
            window.location.href = '/';
        },
        syncUserElements() {}
    };

    window.AuthGuard = AuthGuard;
})();
