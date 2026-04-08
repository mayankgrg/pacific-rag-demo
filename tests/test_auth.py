"""
Unit tests for auth.py — verify_login, issue_token, decode_token, register_user
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import bcrypt
import jwt
import pytest

# Set JWT_SECRET before importing auth so _jwt_secret() doesn't raise
os.environ.setdefault("JWT_SECRET", "test-secret-key-that-is-long-enough-32chars")

import auth
from auth import (
    verify_login,
    issue_token,
    decode_token,
    register_user,
    ALGORITHM,
    TOKEN_EXPIRY_HOURS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

TEST_SECRET = "test-secret-key-that-is-long-enough-32chars"

def _hashed(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(4)).decode()  # cost 4 for speed


SEED_EMPLOYEES = [
    {
        "username": "alice",
        "department": "HR",
        "roles": ["hr"],
        "password_hash": _hashed("secret123"),
    },
    {
        "username": "bob",
        "department": "Finance",
        "roles": ["finance"],
        "password_hash": _hashed("secret123"),
    },
]


# ── verify_login() ────────────────────────────────────────────────────────────

class TestVerifyLogin:
    def test_correct_credentials_returns_employee(self):
        with patch("auth._load_employees", return_value=SEED_EMPLOYEES), \
             patch.dict(os.environ, {"JWT_SECRET": TEST_SECRET}):
            result = verify_login("alice", "secret123")
            assert result is not None
            assert result["username"] == "alice"

    def test_wrong_password_returns_none(self):
        with patch("auth._load_employees", return_value=SEED_EMPLOYEES):
            result = verify_login("alice", "wrongpassword")
            assert result is None

    def test_nonexistent_user_returns_none(self):
        with patch("auth._load_employees", return_value=SEED_EMPLOYEES):
            result = verify_login("ghost", "secret123")
            assert result is None

    def test_wrong_user_wrong_password_returns_none(self):
        with patch("auth._load_employees", return_value=SEED_EMPLOYEES):
            result = verify_login("ghost", "wrongpassword")
            assert result is None

    def test_correct_credentials_returns_full_record(self):
        with patch("auth._load_employees", return_value=SEED_EMPLOYEES):
            result = verify_login("bob", "secret123")
            assert result["department"] == "Finance"
            assert result["roles"] == ["finance"]

    def test_case_sensitive_username(self):
        """Username matching is exact (case-sensitive)."""
        with patch("auth._load_employees", return_value=SEED_EMPLOYEES):
            result = verify_login("Alice", "secret123")
            assert result is None

    def test_empty_password_returns_none(self):
        with patch("auth._load_employees", return_value=SEED_EMPLOYEES):
            result = verify_login("alice", "")
            assert result is None

    def test_empty_employees_list_returns_none(self):
        with patch("auth._load_employees", return_value=[]):
            result = verify_login("alice", "secret123")
            assert result is None


# ── issue_token() + decode_token() ───────────────────────────────────────────

class TestIssueAndDecodeToken:
    def test_issue_token_returns_string(self):
        with patch.dict(os.environ, {"JWT_SECRET": TEST_SECRET}):
            token = issue_token(SEED_EMPLOYEES[0])
            assert isinstance(token, str)

    def test_token_contains_username_as_sub(self):
        with patch.dict(os.environ, {"JWT_SECRET": TEST_SECRET}):
            token = issue_token(SEED_EMPLOYEES[0])
            payload = decode_token(token)
            assert payload["sub"] == "alice"

    def test_token_contains_roles(self):
        with patch.dict(os.environ, {"JWT_SECRET": TEST_SECRET}):
            token = issue_token(SEED_EMPLOYEES[0])
            payload = decode_token(token)
            assert payload["roles"] == ["hr"]

    def test_token_contains_department(self):
        with patch.dict(os.environ, {"JWT_SECRET": TEST_SECRET}):
            token = issue_token(SEED_EMPLOYEES[0])
            payload = decode_token(token)
            assert payload["department"] == "HR"

    def test_token_has_exp_field(self):
        with patch.dict(os.environ, {"JWT_SECRET": TEST_SECRET}):
            token = issue_token(SEED_EMPLOYEES[0])
            payload = decode_token(token)
            assert "exp" in payload

    def test_token_expires_in_approximately_one_hour(self):
        with patch.dict(os.environ, {"JWT_SECRET": TEST_SECRET}):
            before = datetime.now(tz=timezone.utc)
            token = issue_token(SEED_EMPLOYEES[0])
            payload = decode_token(token)
            exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            delta = exp - before
            # Should be ~1 hour, allow 5s tolerance
            assert timedelta(hours=1) - timedelta(seconds=5) < delta <= timedelta(hours=1, seconds=5)

    def test_decode_invalid_token_raises(self):
        with patch.dict(os.environ, {"JWT_SECRET": TEST_SECRET}):
            with pytest.raises(jwt.InvalidTokenError):
                decode_token("this.is.not.a.valid.token")

    def test_decode_token_wrong_secret_raises(self):
        with patch.dict(os.environ, {"JWT_SECRET": TEST_SECRET}):
            token = issue_token(SEED_EMPLOYEES[0])
        with patch.dict(os.environ, {"JWT_SECRET": "completely-different-secret-xyz"}):
            with pytest.raises(jwt.InvalidTokenError):
                decode_token(token)

    def test_decode_expired_token_raises(self):
        with patch.dict(os.environ, {"JWT_SECRET": TEST_SECRET}):
            payload = {
                "sub": "alice",
                "roles": ["hr"],
                "department": "HR",
                "exp": datetime.now(tz=timezone.utc) - timedelta(seconds=1),
            }
            expired_token = jwt.encode(payload, TEST_SECRET, algorithm=ALGORITHM)
            with pytest.raises(jwt.ExpiredSignatureError):
                decode_token(expired_token)

    def test_jwt_secret_missing_raises_runtime_error(self):
        env = {k: v for k, v in os.environ.items() if k != "JWT_SECRET"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="JWT_SECRET"):
                auth._jwt_secret()


# ── register_user() ───────────────────────────────────────────────────────────

class TestRegisterUser:
    def test_register_new_user_returns_record(self, tmp_path):
        emp_file = tmp_path / "employees.json"
        emp_file.write_text(json.dumps(SEED_EMPLOYEES), encoding="utf-8")
        with patch.object(auth, "EMPLOYEES_FILE", emp_file):
            result = register_user("newguy", "pass1234", "Engineering", "engineer")
            assert result is not None
            assert result["username"] == "newguy"
            assert result["roles"] == ["engineer"]

    def test_register_persists_to_file(self, tmp_path):
        emp_file = tmp_path / "employees.json"
        emp_file.write_text(json.dumps(SEED_EMPLOYEES), encoding="utf-8")
        with patch.object(auth, "EMPLOYEES_FILE", emp_file):
            register_user("newguy", "pass1234", "Engineering", "engineer")
            saved = json.loads(emp_file.read_text(encoding="utf-8"))
            usernames = [e["username"] for e in saved]
            assert "newguy" in usernames

    def test_register_duplicate_username_returns_none(self, tmp_path):
        emp_file = tmp_path / "employees.json"
        emp_file.write_text(json.dumps(SEED_EMPLOYEES), encoding="utf-8")
        with patch.object(auth, "EMPLOYEES_FILE", emp_file):
            result = register_user("alice", "newpass1", "HR", "hr")
            assert result is None

    def test_register_duplicate_case_insensitive(self, tmp_path):
        emp_file = tmp_path / "employees.json"
        emp_file.write_text(json.dumps(SEED_EMPLOYEES), encoding="utf-8")
        with patch.object(auth, "EMPLOYEES_FILE", emp_file):
            result = register_user("ALICE", "newpass1", "HR", "hr")
            assert result is None

    def test_register_password_is_hashed(self, tmp_path):
        emp_file = tmp_path / "employees.json"
        emp_file.write_text(json.dumps(SEED_EMPLOYEES), encoding="utf-8")
        with patch.object(auth, "EMPLOYEES_FILE", emp_file):
            result = register_user("newguy", "pass1234", "Engineering", "engineer")
            assert result["password_hash"] != "pass1234"
            assert bcrypt.checkpw(b"pass1234", result["password_hash"].encode())

    def test_register_new_user_can_then_login(self, tmp_path):
        emp_file = tmp_path / "employees.json"
        emp_file.write_text(json.dumps(SEED_EMPLOYEES), encoding="utf-8")
        with patch.object(auth, "EMPLOYEES_FILE", emp_file):
            register_user("newguy", "pass1234", "Engineering", "engineer")
            login_result = verify_login("newguy", "pass1234")
            assert login_result is not None
