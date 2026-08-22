import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend import create_app
from backend.config import TestingConfig
from backend.extensions import db
from backend.services.auth_token_service import generate_auth_token, verify_auth_token


class AuthSystemTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestingConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_auth_token_service_direct(self):
        # Test generation and verification
        token = generate_auth_token(user_id=42, email="test@example.com", name="Test User", expires_in_seconds=5)
        self.assertTrue(token)
        self.assertEqual(verify_auth_token(token), 42)
        self.assertEqual(verify_auth_token(f"Bearer {token}"), 42)

        # Invalid token
        self.assertIsNone(verify_auth_token("invalid.token.string"))
        self.assertIsNone(verify_auth_token(""))
        self.assertIsNone(verify_auth_token(None))

        # Expired token (itsdangerous uses integer second resolution)
        expired_token = generate_auth_token(user_id=42, email="test@example.com", name="Test User", expires_in_seconds=1)
        time.sleep(2.1)
        self.assertIsNone(verify_auth_token(expired_token, max_age=1))

    def test_auth_signup_success(self):
        res = self.client.post("/api/auth/signup", json={
            "name": "Akshay Rajput",
            "email": "akshay@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("token", data)
        self.assertEqual(data["user"]["email"], "akshay@example.com")
        self.assertEqual(data["user"]["name"], "Akshay Rajput")

    def test_auth_signup_validation_and_duplicate(self):
        # Invalid email
        res = self.client.post("/api/auth/signup", json={
            "name": "Akshay",
            "email": "invalid-email",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })
        self.assertEqual(res.status_code, 422)

        # Password mismatch
        res = self.client.post("/api/auth/signup", json={
            "name": "Akshay",
            "email": "akshay@example.com",
            "password": "Password123!",
            "confirm_password": "DifferentPassword!"
        })
        self.assertEqual(res.status_code, 422)

        # Short password
        res = self.client.post("/api/auth/signup", json={
            "name": "Akshay",
            "email": "akshay@example.com",
            "password": "short",
            "confirm_password": "short"
        })
        self.assertEqual(res.status_code, 422)

        # Initial valid signup
        res1 = self.client.post("/api/auth/signup", json={
            "name": "Akshay",
            "email": "akshay@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })
        self.assertEqual(res1.status_code, 201)

        # Duplicate email conflict
        res2 = self.client.post("/api/auth/signup", json={
            "name": "Another Name",
            "email": "akshay@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })
        self.assertEqual(res2.status_code, 409)
        self.assertFalse(res2.get_json()["success"])

    def test_auth_login_and_me_and_logout(self):
        # Register user
        self.client.post("/api/auth/signup", json={
            "name": "User One",
            "email": "user1@example.com",
            "password": "SecurePassword123!",
            "confirm_password": "SecurePassword123!"
        })

        # Successful login
        res = self.client.post("/api/auth/login", json={
            "email": "user1@example.com",
            "password": "SecurePassword123!"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        token = data["token"]

        # GET /api/auth/me with token
        res_me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_me.status_code, 200)
        self.assertEqual(res_me.get_json()["data"]["email"], "user1@example.com")

        # GET /api/me (legacy endpoint) with token
        res_api_me = self.client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_api_me.status_code, 200)
        self.assertEqual(res_api_me.get_json()["data"]["name"], "User One")

        # POST /api/auth/logout
        res_logout = self.client.post("/api/auth/logout")
        self.assertEqual(res_logout.status_code, 200)
        self.assertTrue(res_logout.get_json()["success"])

        # Bad password
        res_bad_pw = self.client.post("/api/auth/login", json={
            "email": "user1@example.com",
            "password": "WrongPassword!"
        })
        self.assertEqual(res_bad_pw.status_code, 401)
        self.assertEqual(res_bad_pw.get_json()["error"], "Invalid email or password.")

        # Unknown user
        res_bad_user = self.client.post("/api/auth/login", json={
            "email": "unknown@example.com",
            "password": "Password123!"
        })
        self.assertEqual(res_bad_user.status_code, 401)
        self.assertEqual(res_bad_user.get_json()["error"], "Invalid email or password.")

    def test_auth_update_profile(self):
        # Register user
        res_signup = self.client.post("/api/auth/signup", json={
            "name": "Original Name",
            "email": "orig@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })
        token = res_signup.get_json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Update profile name, email, and preferences
        res_update = self.client.put("/api/auth/profile", headers=headers, json={
            "name": "Updated Name",
            "email": "updated@example.com",
            "default_template": "template4",
            "theme_preference": "light",
            "email_notifications": False
        })
        self.assertEqual(res_update.status_code, 200)
        data = res_update.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["user"]["name"], "Updated Name")
        self.assertEqual(data["user"]["email"], "updated@example.com")
        self.assertEqual(data["user"]["settings"]["default_template"], "template4")
        self.assertEqual(data["user"]["settings"]["theme_preference"], "light")
        self.assertFalse(data["user"]["settings"]["email_notifications"])

        # Fetch /api/auth/me to verify persistence
        new_token = data["token"]
        res_me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        self.assertEqual(res_me.status_code, 200)
        self.assertEqual(res_me.get_json()["data"]["name"], "Updated Name")

    def test_auth_change_password(self):
        # Register user
        res_signup = self.client.post("/api/auth/signup", json={
            "name": "Password Tester",
            "email": "pw@example.com",
            "password": "OldPassword123!",
            "confirm_password": "OldPassword123!"
        })
        token = res_signup.get_json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Change password wrong current password
        res_fail = self.client.post("/api/auth/change-password", headers=headers, json={
            "current_password": "WrongPassword!",
            "new_password": "NewPassword123!",
            "confirm_password": "NewPassword123!"
        })
        self.assertEqual(res_fail.status_code, 401)

        # Change password mismatch
        res_mismatch = self.client.post("/api/auth/change-password", headers=headers, json={
            "current_password": "OldPassword123!",
            "new_password": "NewPassword123!",
            "confirm_password": "DifferentPassword!"
        })
        self.assertEqual(res_mismatch.status_code, 422)

        # Successful password change
        res_ok = self.client.post("/api/auth/change-password", headers=headers, json={
            "current_password": "OldPassword123!",
            "new_password": "NewPassword123!",
            "confirm_password": "NewPassword123!"
        })
        self.assertEqual(res_ok.status_code, 200)
        self.assertTrue(res_ok.get_json()["success"])

        # Verify old password fails
        res_login_old = self.client.post("/api/auth/login", json={
            "email": "pw@example.com",
            "password": "OldPassword123!"
        })
        self.assertEqual(res_login_old.status_code, 401)

        # Verify new password succeeds
        res_login_new = self.client.post("/api/auth/login", json={
            "email": "pw@example.com",
            "password": "NewPassword123!"
        })
        self.assertEqual(res_login_new.status_code, 200)

    def test_user_stats_and_history_attribution(self):
        from backend.models.export_history import ExportHistory
        from backend.models.ai_history import AIHistory

        # Register user
        res_signup = self.client.post("/api/auth/signup", json={
            "name": "Stats User",
            "email": "stats@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })
        token = res_signup.get_json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create 2 resumes
        r1 = self.client.post("/generate", headers=headers, json={
            "name": "Resume 1",
            "title": "Engineer",
            "email": "stats@example.com",
            "template": "template1",
            "skills": ["Python"],
            "languages": [],
            "experience": [],
            "education": []
        })
        r1_id = r1.get_json()["resume_id"]

        r2 = self.client.post("/generate", headers=headers, json={
            "name": "Resume 2",
            "title": "Architect",
            "email": "stats@example.com",
            "template": "template2",
            "skills": ["Go"],
            "languages": [],
            "experience": [],
            "education": []
        })

        # Download JSON and DOC
        dl_json = self.client.get(f"/resume/{r1_id}/download", headers=headers)
        self.assertEqual(dl_json.status_code, 200)

        dl_doc = self.client.get(f"/resume/{r1_id}/download-doc", headers=headers)
        self.assertEqual(dl_doc.status_code, 200)

        # Verify ExportHistory user_id attribution
        exports = ExportHistory.query.filter_by(resume_id=r1_id).all()
        self.assertEqual(len(exports), 2)
        for exp in exports:
            self.assertIsNotNone(exp.user_id)

        # Check /api/user/stats
        res_stats = self.client.get("/api/user/stats", headers=headers)
        self.assertEqual(res_stats.status_code, 200)
        stats_data = res_stats.get_json()["data"]
        self.assertEqual(stats_data["total_resumes"], 2)
        self.assertEqual(stats_data["total_exports"], 2)

    def test_protected_routes_without_token(self):
        # Resume routes
        self.assertEqual(self.client.get("/api/resumes").status_code, 401)
        self.assertEqual(self.client.post("/generate", json={}).status_code, 401)
        self.assertEqual(self.client.get("/resume/1").status_code, 401)
        self.assertEqual(self.client.post("/resume/1/delete").status_code, 401)

        # AI routes
        self.assertEqual(self.client.post("/api/generate-summary", json={}).status_code, 401)
        self.assertEqual(self.client.post("/api/chat", json={}).status_code, 401)
        self.assertEqual(self.client.post("/upload-photo").status_code, 401)

        # Public routes still open
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/api/templates").status_code, 200)

    def test_idor_protection_and_user_isolation(self):
        # Register User A
        res_a = self.client.post("/api/auth/signup", json={
            "name": "User A",
            "email": "userA@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })
        token_a = res_a.get_json()["token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        # Register User B
        res_b = self.client.post("/api/auth/signup", json={
            "name": "User B",
            "email": "userB@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })
        token_b = res_b.get_json()["token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # User A creates a resume
        create_res = self.client.post("/generate", headers=headers_a, json={
            "name": "User A Resume",
            "title": "Software Engineer",
            "email": "userA@example.com",
            "template": "template1",
            "skills": ["Python", "Flask"],
            "languages": ["English"],
            "experience": [{"title": "Senior Dev", "company": "Tech Corp", "duration": "2020-Present", "description": "Built scalable APIs"}],
            "education": [{"degree": "B.S. CS", "university": "State University", "year": "2020"}]
        })
        self.assertEqual(create_res.status_code, 200)
        resume_a_id = create_res.get_json()["resume_id"]

        # User A can view their resume
        res = self.client.get(f"/api/resumes/{resume_a_id}", headers=headers_a)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"]["name"], "User A Resume")

        # User A can update their resume
        update_res = self.client.post("/generate", headers=headers_a, json={
            "resume_id": resume_a_id,
            "name": "User A Updated Resume",
            "title": "Staff Engineer",
            "email": "userA@example.com",
            "template": "template2",
            "skills": ["Python", "Flask", "Docker"],
            "languages": ["English"],
            "experience": [],
            "education": []
        })
        self.assertEqual(update_res.status_code, 200)

        # User A version history
        ver_res = self.client.get(f"/resume/{resume_a_id}/versions", headers=headers_a)
        self.assertEqual(ver_res.status_code, 200)
        self.assertGreaterEqual(len(ver_res.get_json()["data"]), 1)

        # User B CANNOT view User A's resume (IDOR Prevention -> 404)
        res_b_view = self.client.get(f"/api/resumes/{resume_a_id}", headers=headers_b)
        self.assertEqual(res_b_view.status_code, 404)

        # User B CANNOT view User A's version history
        res_b_ver = self.client.get(f"/resume/{resume_a_id}/versions", headers=headers_b)
        self.assertEqual(res_b_ver.status_code, 404)

        # User B list resumes is empty
        res_b_list = self.client.get("/api/resumes", headers=headers_b)
        self.assertEqual(res_b_list.status_code, 200)
        self.assertEqual(len(res_b_list.get_json()["data"]), 0)

        # User B cannot delete User A's resume
        res_b_del = self.client.post(f"/resume/{resume_a_id}/delete", headers=headers_b)
        self.assertEqual(res_b_del.status_code, 404)

        # User B cannot switch template of User A's resume
        res_b_switch = self.client.post(f"/resume/{resume_a_id}/switch-template", headers=headers_b, json={"template": "template2"})
        self.assertEqual(res_b_switch.status_code, 404)

        # User B cannot duplicate User A's resume
        res_b_dup = self.client.post(f"/resume/{resume_a_id}/duplicate", headers=headers_b, json={"duplicate_template": "template3"})
        self.assertEqual(res_b_dup.status_code, 404)


if __name__ == "__main__":
    unittest.main()
