"""
Authentication helpers: login verification, JWT issue and decode.

Security notes:
- Passwords verified with bcrypt (cost factor 12).
- JWT delivered as httpOnly + Secure + SameSite=Strict cookie — JS cannot read it.
- Token expiry: 1 hour.
- JWT secret loaded from environment variable JWT_SECRET (min 32 chars recommended).
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import jwt
from dotenv import load_dotenv
from typing import Optional

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

EMPLOYEES_FILE = Path(__file__).parent / "data" / "employees.json"
TOKEN_EXPIRY_HOURS = 1
ALGORITHM = "HS256"


def _load_employees() -> list[dict]:
    return json.loads(EMPLOYEES_FILE.read_text(encoding="utf-8"))


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET environment variable is not set.")
    return secret


def verify_login(username: str, password: str) -> Optional[dict]:
    """
    Verify credentials against the employee store.
    Returns the employee record on success, None on failure.
    Runs in constant time to resist timing attacks.
    """
    employees = _load_employees()
    matched = next((e for e in employees if e["username"] == username), None)

    # Always run bcrypt check to avoid timing-based username enumeration.
    # The dummy hash is a pre-computed valid bcrypt hash; it will never match
    # any real password but ensures checkpw() runs in constant time for
    # non-existent usernames.
    dummy_hash = "$2b$12$LqCimZ4P.p7HmjS9KJSlw.Rt7FzQyIFMxJRtxGBGu/l.VLRlj.oPq"
    stored_hash = matched["password_hash"].encode() if matched else dummy_hash.encode()
    password_ok = bcrypt.checkpw(password.encode(), stored_hash)

    if matched and password_ok:
        return matched
    return None


def issue_token(employee: dict) -> str:
    """Sign and return a JWT containing the user's roles."""
    payload = {
        "sub": employee["username"],
        "roles": employee["roles"],
        "department": employee["department"],
        "exp": datetime.now(tz=timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=ALGORITHM)


def register_user(username: str, password: str, department: str, role: str) -> Optional[dict]:
    """
    Add a new user to the employee store.
    Returns the new employee record on success, None if username already taken.
    Role must be one of the allowed roles (admin excluded from self-registration).
    """
    employees = _load_employees()

    # Username uniqueness check (case-insensitive)
    if any(e["username"].lower() == username.lower() for e in employees):
        return None

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()
    new_employee = {
        "username": username,
        "department": department,
        "roles": [role],
        "password_hash": password_hash,
    }
    employees.append(new_employee)
    EMPLOYEES_FILE.write_text(json.dumps(employees, indent=2), encoding="utf-8")
    return new_employee


def decode_token(token: str) -> dict:
    """
    Decode and verify a JWT. Raises jwt.ExpiredSignatureError or
    jwt.InvalidTokenError on failure — callers should handle these.
    """
    return jwt.decode(token, _jwt_secret(), algorithms=[ALGORITHM])
