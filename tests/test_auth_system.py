"""
tests/test_auth_system.py — Comprehensive Auth & IDOR Security Test Suite
"""

import json
import pytest
from backend import create_app
from backend.config import TestingConfig
from backend.extensions import db
from backend.models.user import User
from backend.models.resume import Resume


@pytest.fixture
def client():
    app = create_app(TestingConfig)
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def test_auth_signup_success(client):
    res = client.post("/api/auth/signup", json={
        "name": "Akshay Rajput",
        "email": "akshay@example.com",
        "password": "Password123!",
        "confirm_password": "Password123!"
    })
    assert res.status_code == 201
    data = res.get_json()
    assert data["success"] is True
    assert "token" in data
    assert data["user"]["email"] == "akshay@example.com"
    assert data["user"]["name"] == "Akshay Rajput"


def test_auth_signup_validation_and_duplicate(client):
    # Invalid email
    res = client.post("/api/auth/signup", json={
        "name": "Akshay",
        "email": "invalid-email",
        "password": "Password123!",
        "confirm_password": "Password123!"
    })
    assert res.status_code == 422

    # Password mismatch
    res = client.post("/api/auth/signup", json={
        "name": "Akshay",
        "email": "akshay@example.com",
        "password": "Password123!",
        "confirm_password": "DifferentPassword!"
    })
    assert res.status_code == 422

    # Short password
    res = client.post("/api/auth/signup", json={
        "name": "Akshay",
        "email": "akshay@example.com",
        "password": "short",
        "confirm_password": "short"
    })
    assert res.status_code == 422

    # Initial valid signup
    res1 = client.post("/api/auth/signup", json={
        "name": "Akshay",
        "email": "akshay@example.com",
        "password": "Password123!",
        "confirm_password": "Password123!"
    })
    assert res1.status_code == 201

    # Duplicate email conflict
    res2 = client.post("/api/auth/signup", json={
        "name": "Another Name",
        "email": "akshay@example.com",
        "password": "Password123!",
        "confirm_password": "Password123!"
    })
    assert res2.status_code == 409
    assert res2.get_json()["success"] is False


def test_auth_login_flow(client):
    # Register user
    client.post("/api/auth/signup", json={
        "name": "User One",
        "email": "user1@example.com",
        "password": "SecurePassword123!",
        "confirm_password": "SecurePassword123!"
    })

    # Successful login
    res = client.post("/api/auth/login", json={
        "email": "user1@example.com",
        "password": "SecurePassword123!"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "token" in data

    # Bad password
    res_bad_pw = client.post("/api/auth/login", json={
        "email": "user1@example.com",
        "password": "WrongPassword!"
    })
    assert res_bad_pw.status_code == 401
    assert res_bad_pw.get_json()["error"] == "Invalid email or password."

    # Unknown user
    res_bad_user = client.post("/api/auth/login", json={
        "email": "unknown@example.com",
        "password": "Password123!"
    })
    assert res_bad_user.status_code == 401
    assert res_bad_user.get_json()["error"] == "Invalid email or password."


def test_protected_routes_without_token(client):
    # Resume routes
    assert client.get("/api/resumes").status_code == 401
    assert client.post("/generate", json={}).status_code == 401
    assert client.get("/resume/1").status_code == 401
    assert client.post("/resume/1/delete").status_code == 401

    # AI routes
    assert client.post("/api/generate-summary", json={}).status_code == 401
    assert client.post("/api/chat", json={}).status_code == 401
    assert client.post("/upload-photo").status_code == 401

    # Public routes still open
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/templates").status_code == 200


def test_idor_protection_and_user_isolation(client):
    # Register User A
    res_a = client.post("/api/auth/signup", json={
        "name": "User A",
        "email": "userA@example.com",
        "password": "Password123!",
        "confirm_password": "Password123!"
    })
    token_a = res_a.get_json()["token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Register User B
    res_b = client.post("/api/auth/signup", json={
        "name": "User B",
        "email": "userB@example.com",
        "password": "Password123!",
        "confirm_password": "Password123!"
    })
    token_b = res_b.get_json()["token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A creates a resume
    create_res = client.post("/generate", headers=headers_a, json={
        "name": "User A Resume",
        "title": "Software Engineer",
        "email": "userA@example.com",
        "template": "template1",
        "skills": ["Python", "Flask"],
        "languages": ["English"],
        "experience": [],
        "education": []
    })
    assert create_res.status_code == 200
    resume_a_id = create_res.get_json()["resume_id"]

    # User A can view their resume
    res = client.get(f"/api/resumes/{resume_a_id}", headers=headers_a)
    assert res.status_code == 200
    assert res.get_json()["data"]["name"] == "User A Resume"

    # User B CANNOT view User A's resume (IDOR Prevention -> 404)
    res_b_view = client.get(f"/api/resumes/{resume_a_id}", headers=headers_b)
    assert res_b_view.status_code == 404

    # User B list resumes is empty
    res_b_list = client.get("/api/resumes", headers=headers_b)
    assert res_b_list.status_code == 200
    assert len(res_b_list.get_json()["data"]) == 0

    # User B cannot delete User A's resume
    res_b_del = client.post(f"/resume/{resume_a_id}/delete", headers=headers_b)
    assert res_b_del.status_code == 404

    # User B cannot switch template of User A's resume
    res_b_switch = client.post(f"/resume/{resume_a_id}/switch-template", headers=headers_b, json={"template": "template2"})
    assert res_b_switch.status_code == 404
