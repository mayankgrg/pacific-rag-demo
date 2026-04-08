"""
FastAPI application entry point.

Serves the web UI (static/index.html) and all API routes.
Middleware stack (outermost → innermost):
  1. Security headers
  2. CORS (restrict to own origin)
  3. Rate limiting (slowapi)
  4. Route handlers
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import jwt as pyjwt
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import audit
from auth import decode_token, issue_token, verify_login, register_user
from ingest import ingest
from rag import query as rag_query

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

DB_DIR = Path(__file__).parent / "db"
STATIC_DIR = Path(__file__).parent / "static"

# Secure cookie flag only applies on HTTPS (production).
# On localhost (HTTP) it must be False or the browser silently drops the cookie.
IS_PROD = os.environ.get("RENDER", "") != ""


# ── Startup: auto-ingest if DB is empty ──────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DB_DIR.exists() or not any(DB_DIR.iterdir()):
        print("DB empty — running ingestion pipeline...")
        ingest()
    yield


# ── App + rate limiter ────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Security headers middleware ───────────────────────────────────────────────

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline';"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


# ── CORS ──────────────────────────────────────────────────────────────────────

ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "http://localhost:8000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# ── Request / Response models ─────────────────────────────────────────────────

ALLOWED_REGISTER_ROLES = ["hr", "finance", "engineer", "intern"]  # admin excluded

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username:   str = Field(..., min_length=2, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password:   str = Field(..., min_length=8, max_length=128)
    department: str = Field(..., min_length=1, max_length=64)
    role:       str


class ChatMessage(BaseModel):
    role: str   # "user" or "assistant"
    content: str = Field(..., max_length=2000)


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _get_current_user(access_token: Optional[str]) -> Optional[dict]:
    """Decode JWT from cookie. Returns payload dict or None."""
    if not access_token:
        return None
    try:
        return decode_token(access_token)
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
        return None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.post("/login")
async def login(body: LoginRequest, response: Response):
    employee = verify_login(body.username, body.password)
    if not employee:
        return JSONResponse(status_code=401, content={"error": "Invalid username or password."})

    token = issue_token(employee)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=IS_PROD,          # True on Render (HTTPS), False on localhost (HTTP)
        samesite="strict",
        max_age=3600,
        path="/",
    )
    return {
        "username": employee["username"],
        "department": employee["department"],
        "roles": employee["roles"],
    }


@app.post("/register")
async def register(body: RegisterRequest, response: Response):
    # Validate role
    if body.role not in ALLOWED_REGISTER_ROLES:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid role. Choose from: {', '.join(ALLOWED_REGISTER_ROLES)}"}
        )
    # Password strength: must have at least one letter and one digit
    has_letter = any(c.isalpha()  for c in body.password)
    has_digit  = any(c.isdigit()  for c in body.password)
    if not (has_letter and has_digit):
        return JSONResponse(
            status_code=400,
            content={"error": "Password must contain at least one letter and one number."}
        )

    employee = register_user(body.username, body.password, body.department, body.role)
    if employee is None:
        return JSONResponse(status_code=409, content={"error": "Username already taken."})

    # Auto-login: issue token and set cookie immediately after registration
    token = issue_token(employee)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=IS_PROD,
        samesite="strict",
        max_age=3600,
        path="/",
    )
    return {
        "username": employee["username"],
        "department": employee["department"],
        "roles": employee["roles"],
    }


@app.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="access_token", path="/")
    return {"message": "Logged out."}


@app.post("/query")
@limiter.limit("20/minute")
async def query_endpoint(
    request: Request,
    body: QueryRequest,
    access_token: Optional[str] = Cookie(default=None),
):
    user = _get_current_user(access_token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated."})

    history = [{"role": m.role, "content": m.content} for m in body.history]
    result = rag_query(body.query, user["roles"], history)

    audit.log_query(
        username=user["sub"],
        roles=user["roles"],
        query=body.query,
        sources=result.sources,
        chunks_blocked=result.chunks_blocked,
        latency_ms=result.latency_ms,
    )

    return {
        "answer": result.answer,
        "sources": result.sources,
        "chunks_blocked": result.chunks_blocked,
        "latency_ms": result.latency_ms,
    }


@app.get("/audit/report")
async def audit_report(access_token: Optional[str] = Cookie(default=None)):
    user = _get_current_user(access_token)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated."})
    if "admin" not in user.get("roles", []):
        return JSONResponse(status_code=403, content={"error": "Admin access required."})
    return audit.get_report()


# ── Static files (fallback) ───────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
