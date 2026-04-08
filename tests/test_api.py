"""
Integration tests for main.py FastAPI routes.

Uses FastAPI's TestClient (synchronous). All external dependencies
(employees file, rag pipeline, audit logger) are mocked or redirected
to temp files so tests are fast and hermetic.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import bcrypt
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-key-that-is-long-enough-32chars")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("ALLOWED_ORIGIN", "http://localhost:8000")

# Patch ingest so the lifespan doesn't try to build ChromaDB on startup
with patch("ingest.ingest"):
    from main import app

def fresh_client() -> TestClient:
    """Return a brand-new TestClient with a clean cookie jar."""
    return TestClient(app, raise_server_exceptions=True)

client = fresh_client()


# ── Shared fixture data ───────────────────────────────────────────────────────

def _hashed(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(4)).decode()


EMPLOYEES = [
    {"username": "charlie", "department": "IT",      "roles": ["admin"],    "password_hash": _hashed("secret123")},
    {"username": "alice",   "department": "HR",      "roles": ["hr"],       "password_hash": _hashed("secret123")},
    {"username": "bob",     "department": "Finance",  "roles": ["finance"],  "password_hash": _hashed("secret123")},
    {"username": "eve",     "department": "Intern",   "roles": ["intern"],   "password_hash": _hashed("secret123")},
]


def _patch_employees():
    return patch("auth._load_employees", return_value=EMPLOYEES)


# ── POST /login ───────────────────────────────────────────────────────────────

class TestLogin:
    def test_valid_credentials_returns_200(self):
        with _patch_employees():
            r = client.post("/login", json={"username": "alice", "password": "secret123"})
        assert r.status_code == 200

    def test_valid_login_returns_username(self):
        with _patch_employees():
            r = client.post("/login", json={"username": "alice", "password": "secret123"})
        assert r.json()["username"] == "alice"

    def test_valid_login_returns_roles(self):
        with _patch_employees():
            r = client.post("/login", json={"username": "alice", "password": "secret123"})
        assert r.json()["roles"] == ["hr"]

    def test_valid_login_sets_cookie(self):
        with _patch_employees():
            r = client.post("/login", json={"username": "alice", "password": "secret123"})
        assert "access_token" in r.cookies

    def test_wrong_password_returns_401(self):
        with _patch_employees():
            r = client.post("/login", json={"username": "alice", "password": "wrong"})
        assert r.status_code == 401

    def test_wrong_password_error_message(self):
        with _patch_employees():
            r = client.post("/login", json={"username": "alice", "password": "wrong"})
        assert "error" in r.json()

    def test_nonexistent_user_returns_401(self):
        with _patch_employees():
            r = client.post("/login", json={"username": "nobody", "password": "secret123"})
        assert r.status_code == 401

    def test_missing_password_field_returns_422(self):
        r = client.post("/login", json={"username": "alice"})
        assert r.status_code == 422

    def test_missing_username_field_returns_422(self):
        r = client.post("/login", json={"password": "secret123"})
        assert r.status_code == 422


# ── POST /logout ──────────────────────────────────────────────────────────────

class TestLogout:
    def test_logout_returns_200(self):
        r = client.post("/logout")
        assert r.status_code == 200

    def test_logout_returns_message(self):
        r = client.post("/logout")
        assert r.json().get("message") == "Logged out."


# ── POST /register ────────────────────────────────────────────────────────────

class TestRegister:
    def test_valid_registration_returns_200(self, tmp_path):
        emp_file = tmp_path / "employees.json"
        emp_file.write_text(json.dumps(EMPLOYEES), encoding="utf-8")
        with patch("auth.EMPLOYEES_FILE", emp_file):
            r = client.post("/register", json={
                "username": "newuser", "password": "pass1234",
                "department": "Finance", "role": "finance"
            })
        assert r.status_code == 200

    def test_valid_registration_returns_username(self, tmp_path):
        emp_file = tmp_path / "employees.json"
        emp_file.write_text(json.dumps(EMPLOYEES), encoding="utf-8")
        with patch("auth.EMPLOYEES_FILE", emp_file):
            r = client.post("/register", json={
                "username": "newuser", "password": "pass1234",
                "department": "Finance", "role": "finance"
            })
        assert r.json()["username"] == "newuser"

    def test_registration_sets_cookie(self, tmp_path):
        emp_file = tmp_path / "employees.json"
        emp_file.write_text(json.dumps(EMPLOYEES), encoding="utf-8")
        with patch("auth.EMPLOYEES_FILE", emp_file):
            r = client.post("/register", json={
                "username": "newuser", "password": "pass1234",
                "department": "Finance", "role": "finance"
            })
        assert "access_token" in r.cookies

    def test_duplicate_username_returns_409(self, tmp_path):
        emp_file = tmp_path / "employees.json"
        emp_file.write_text(json.dumps(EMPLOYEES), encoding="utf-8")
        with patch("auth.EMPLOYEES_FILE", emp_file):
            r = client.post("/register", json={
                "username": "alice", "password": "pass1234",
                "department": "HR", "role": "hr"
            })
        assert r.status_code == 409

    def test_invalid_role_returns_400(self):
        r = client.post("/register", json={
            "username": "newuser", "password": "pass1234",
            "department": "IT", "role": "admin"
        })
        assert r.status_code == 400

    def test_admin_role_blocked_from_self_registration(self):
        r = client.post("/register", json={
            "username": "hacker", "password": "pass1234",
            "department": "IT", "role": "admin"
        })
        assert r.status_code == 400
        assert "admin" not in r.json().get("error", "").lower() or "Invalid role" in r.json().get("error", "")

    def test_weak_password_no_digit_returns_400(self):
        r = client.post("/register", json={
            "username": "newuser", "password": "onlyletters",
            "department": "HR", "role": "hr"
        })
        assert r.status_code == 400

    def test_weak_password_no_letter_returns_400(self):
        r = client.post("/register", json={
            "username": "newuser", "password": "12345678",
            "department": "HR", "role": "hr"
        })
        assert r.status_code == 400

    def test_short_username_rejected(self):
        r = client.post("/register", json={
            "username": "x", "password": "pass1234",
            "department": "HR", "role": "hr"
        })
        assert r.status_code == 422

    def test_special_chars_in_username_rejected(self):
        r = client.post("/register", json={
            "username": "bad user!", "password": "pass1234",
            "department": "HR", "role": "hr"
        })
        assert r.status_code == 422


# ── POST /query ───────────────────────────────────────────────────────────────

class TestQueryEndpoint:
    def _login_cookie(self, username="alice"):
        c = fresh_client()
        with _patch_employees():
            r = c.post("/login", json={"username": username, "password": "secret123"})
        return r.cookies.get("access_token")

    def test_query_without_auth_returns_401(self):
        c = fresh_client()  # no prior login on this client
        r = c.post("/query", json={"query": "What is the policy?", "history": []})
        assert r.status_code == 401

    def _authed_client(self, username="alice"):
        token = self._login_cookie(username)
        c = fresh_client()
        c.cookies.set("access_token", token)
        return c

    def test_query_with_valid_auth_returns_200(self):
        mock_result = MagicMock()
        mock_result.answer = "The policy is X."
        mock_result.sources = ["hr_policy"]
        mock_result.chunks_blocked = 30
        mock_result.latency_ms = 100
        c = self._authed_client("alice")
        with patch("main.rag_query", return_value=mock_result), \
             patch("audit.log_query"):
            r = c.post("/query", json={"query": "What is leave policy?", "history": []})
        assert r.status_code == 200

    def test_query_response_has_answer_field(self):
        mock_result = MagicMock()
        mock_result.answer = "Here is the answer."
        mock_result.sources = ["hr_policy"]
        mock_result.chunks_blocked = 5
        mock_result.latency_ms = 120
        c = self._authed_client("alice")
        with patch("main.rag_query", return_value=mock_result), \
             patch("audit.log_query"):
            r = c.post("/query", json={"query": "Question?", "history": []})
        assert "answer" in r.json()

    def test_query_response_has_sources_field(self):
        mock_result = MagicMock()
        mock_result.answer = "Answer."
        mock_result.sources = ["hr_policy"]
        mock_result.chunks_blocked = 5
        mock_result.latency_ms = 120
        c = self._authed_client("alice")
        with patch("main.rag_query", return_value=mock_result), \
             patch("audit.log_query"):
            r = c.post("/query", json={"query": "Question?", "history": []})
        assert "sources" in r.json()

    def test_query_too_long_returns_422(self):
        c = self._authed_client("alice")
        r = c.post("/query", json={"query": "x" * 501, "history": []})
        assert r.status_code == 422

    def test_query_empty_returns_422(self):
        c = self._authed_client("alice")
        r = c.post("/query", json={"query": "", "history": []})
        assert r.status_code == 422


# ── GET /audit/report ─────────────────────────────────────────────────────────

class TestAuditReport:
    def _admin_cookie(self):
        c = fresh_client()
        with _patch_employees():
            r = c.post("/login", json={"username": "charlie", "password": "secret123"})
        return r.cookies.get("access_token")

    def _non_admin_cookie(self):
        c = fresh_client()
        with _patch_employees():
            r = c.post("/login", json={"username": "alice", "password": "secret123"})
        return r.cookies.get("access_token")

    def test_no_auth_returns_401(self):
        c = fresh_client()  # no prior login on this client
        r = c.get("/audit/report")
        assert r.status_code == 401

    def test_non_admin_returns_403(self):
        token = self._non_admin_cookie()
        c = fresh_client()
        c.cookies.set("access_token", token)
        r = c.get("/audit/report")
        assert r.status_code == 403

    def test_admin_returns_200(self):
        token = self._admin_cookie()
        c = fresh_client()
        c.cookies.set("access_token", token)
        with patch("audit.get_report", return_value={"total_queries": 0, "entries": []}):
            r = c.get("/audit/report")
        assert r.status_code == 200

    def test_admin_response_has_total_queries(self):
        token = self._admin_cookie()
        c = fresh_client()
        c.cookies.set("access_token", token)
        with patch("audit.get_report", return_value={"total_queries": 7, "entries": []}):
            r = c.get("/audit/report")
        assert r.json()["total_queries"] == 7

    def test_admin_response_has_entries(self):
        token = self._admin_cookie()
        c = fresh_client()
        c.cookies.set("access_token", token)
        with patch("audit.get_report", return_value={"total_queries": 0, "entries": []}):
            r = c.get("/audit/report")
        assert "entries" in r.json()


# ── Security headers ──────────────────────────────────────────────────────────

class TestSecurityHeaders:
    def test_x_content_type_options_present(self):
        r = client.get("/")
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options_deny(self):
        r = client.get("/")
        assert r.headers.get("x-frame-options") == "DENY"

    def test_content_security_policy_present(self):
        r = client.get("/")
        assert "content-security-policy" in r.headers

    def test_referrer_policy_present(self):
        r = client.get("/")
        assert r.headers.get("referrer-policy") == "no-referrer"
