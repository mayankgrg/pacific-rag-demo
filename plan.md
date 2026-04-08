# Permission-Aware RAG System — Project Plan

## Overview

A web-hosted Retrieval-Augmented Generation (RAG) system where documents are tagged
with access roles, and an AI agent only retrieves and answers from context it is
**authorized to see**. Users can register with a role, log in, and chat with the
assistant — receiving answers only from documents their role permits.

Deployed entirely on Render.com (free tier). No local setup needed for reviewers —
just a URL.

This directly mirrors Pacific's Enterprise Context Management System (ECMS):
centralizing knowledge while enforcing fine-grained permissions at retrieval time,
with enterprise-grade security throughout.

---

## Problem Statement

Existing RAG pipelines treat context as a flat pool — every query has access to every
document. In real organizations, sensitive data (financials, HR records, legal docs)
must be siloed by role. Pacific's vision requires that AI agents respect data governance
boundaries so enterprises can trust what the AI sees and says.

---

## Deployment Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     RENDER.COM (free tier)                    │
│                                                              │
│   ┌──────────────────────────────────────────────────────┐  │
│   │                    FastAPI App                        │  │
│   │                                                       │  │
│   │   GET  /               → serves index.html           │  │
│   │   POST /login          → bcrypt verify, JWT cookie   │  │
│   │   POST /register       → new user, auto-login        │  │
│   │   POST /logout         → clears JWT cookie           │  │
│   │   POST /query          → permission-gated RAG        │  │
│   │   GET  /audit/report   → admin only                  │  │
│   │                                                       │  │
│   │   static/index.html    → chat UI                     │  │
│   └──────────────────────────────────────────────────────┘  │
│                        │                                     │
│          ┌─────────────┼──────────────┐                      │
│          ▼             ▼              ▼                      │
│   ┌────────────┐ ┌──────────┐ ┌───────────────┐             │
│   │ ChromaDB   │ │employees │ │  logs/        │             │
│   │ (db/ disk) │ │.json     │ │  audit.jsonl  │             │
│   └────────────┘ └──────────┘ └───────────────┘             │
│                                                              │
│   Environment Variables (Render dashboard):                  │
│     GROQ_API_KEY=gsk_...                                    │
│     JWT_SECRET=<32+ char random string>                      │
│     ALLOWED_ORIGIN=https://<app>.onrender.com                │
└──────────────────────────────────────────────────────────────┘
         ▲
         │  HTTPS only (Render provides TLS)
         │
    Browser (reviewer) — no install, no API keys, just a URL
```

---

## Full System Design

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          PACIFIC RAG SYSTEM                                  │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                          AUTH LAYER                                  │    │
│  │                                                                      │    │
│  │  POST /register → validate role → bcrypt hash → save employees.json │    │
│  │  POST /login    → bcrypt verify → sign JWT → httpOnly cookie        │    │
│  │                                                                      │    │
│  │  JWT payload: { sub, roles, department, exp }                        │    │
│  │  Cookie flags: httpOnly + Secure (prod only) + SameSite=Strict      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│                         JWT cookie sent on every request                     │
│                                    │                                         │
│  ┌──────────────┐     ┌───────────────────────────────────────────┐         │
│  │  Document    │     │              INGESTION PIPELINE            │         │
│  │  Sources     │────▶│  (auto-runs at startup if DB is empty)    │         │
│  │              │     │                                           │         │
│  │  company_faq │     │  1. Parse docs/*.txt                      │         │
│  │  hr_policy   │     │  2. Chunk into ~512-char segments         │         │
│  │  financials  │     │  3. Embed via sentence-transformers        │         │
│  │  eng_guide   │     │  4. Attach role permission metadata        │         │
│  │  onboarding  │     │  5. Persist to ChromaDB                   │         │
│  └──────────────┘     └───────────────────────────────────────────┘         │
│   + .meta.json                           │                                   │
│     per doc                              ▼                                   │
│                             ┌────────────────────────────┐                  │
│                             │       VECTOR STORE          │                  │
│                             │  (ChromaDB, local disk)     │                  │
│                             │                             │                  │
│                             │  chunk  │ embedding │ meta  │                  │
│                             │  ───────┼───────────┼────── │                  │
│                             │  c001   │ [0.12...] │ role_hr=True             │
│                             │  c002   │ [0.87...] │ role_intern=True         │
│                             │  c003   │ [0.44...] │ role_finance=True        │
│                             └────────────────────────────┘                  │
│                                          │                                   │
│  ┌──────────────┐     JWT verified       ▼                                   │
│  │  Browser     │────────────────▶ ┌───────────────────────────────┐        │
│  │  (chat UI)   │                  │   PERMISSION-GATED RETRIEVAL  │        │
│  │              │  { query,        │                               │        │
│  │  Send btn    │    history }     │  1. Decode + verify JWT       │        │
│  └──────────────┘                  │  2. Expand roles (hierarchy)  │        │
│                                    │  3. Sanitize + validate query │        │
│                                    │  4. Embed query               │        │
│                                    │  5. Filter ChromaDB by roles  │        │
│                                    │  6. Return top-k chunks       │        │
│                                    └───────────────────────────────┘        │
│                                                   │                          │
│                                                   ▼                          │
│                                    ┌──────────────────────────┐             │
│                                    │     CONTEXT ASSEMBLER     │             │
│                                    │  - Deduplicate chunks     │             │
│                                    │  - Rank by similarity     │             │
│                                    │  - Trim to 12k char budget│             │
│                                    │  - Wrap in XML tags       │             │
│                                    └──────────────────────────┘             │
│                                                   │                          │
│                                                   ▼                          │
│                                    ┌──────────────────────────┐             │
│                                    │    GROQ LLM               │             │
│                                    │    (llama-3.1-8b-instant) │             │
│                                    │                           │             │
│                                    │  messages:                │             │
│                                    │   [system_prompt,         │             │
│                                    │    ...chat_history,       │             │
│                                    │    user_message]          │             │
│                                    │                           │             │
│                                    │  Prompt injection defense:│             │
│                                    │  query wrapped in         │             │
│                                    │  <user_query> XML tags    │             │
│                                    └──────────────────────────┘             │
│                                                   │                          │
│                                                   ▼                          │
│                                    ┌──────────────────────────┐             │
│                                    │   RESPONSE + AUDIT LOG    │             │
│                                    │  answer (plain text only) │             │
│                                    │  sources: [filenames]     │             │
│                                    │  chunks_blocked: N        │             │
│                                    │  latency_ms               │             │
│                                    └──────────────────────────┘             │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Auth Layer Design

### Employee Store (`data/employees.json`)
Simulates an enterprise IdP (Okta / Active Directory). Roles are pre-assigned
for demo seed users, and new users can self-register via the UI.

```json
[
  { "username": "charlie", "password_hash": "...", "department": "IT",      "roles": ["admin"] },
  { "username": "alice",   "password_hash": "...", "department": "HR",      "roles": ["hr"] },
  { "username": "bob",     "password_hash": "...", "department": "Finance", "roles": ["finance"] },
  { "username": "diana",   "password_hash": "...", "department": "Eng",     "roles": ["engineer"] },
  { "username": "eve",     "password_hash": "...", "department": "Intern",  "roles": ["intern"] }
]
```

### JWT Token
```json
{ "sub": "alice", "roles": ["hr"], "department": "HR", "exp": 1712345678 }
```
- Signed `HS256` using `JWT_SECRET` from environment variable
- Delivered as `httpOnly; SameSite=Strict` cookie — JS cannot read it
- `Secure` flag enabled on production (Render), disabled on localhost HTTP
- Expiry: 1 hour

### Registration Rules
- Any user can self-register as: `hr`, `finance`, `engineer`, `intern`
- `admin` role is **blocked** from self-registration (pre-seeded only)
- Password: min 8 chars, must contain at least one letter and one digit
- Username: alphanumeric + underscore only, case-insensitive uniqueness check
- On success: JWT cookie issued immediately — user lands in chat without a second login

---

## Permission Model

### Role Hierarchy
```
admin       → sees ALL documents
  ├── hr          → hr_policy + public
  ├── finance     → q4_financials + public
  ├── engineer    → engineering_guide + public
  └── intern      → public only
```

### Role Expansion at Retrieval Time
```python
ROLE_HIERARCHY = {
    "admin":    ["admin", "hr", "finance", "engineer", "intern"],
    "hr":       ["hr", "intern"],
    "finance":  ["finance", "intern"],
    "engineer": ["engineer", "intern"],
    "intern":   ["intern"],
}
```
`admin` expands to all roles → passes every ChromaDB filter automatically.

### Document Classification
| File                    | Classification | Allowed Roles                             |
|-------------------------|----------------|-------------------------------------------|
| `company_faq.txt`       | public         | intern, engineer, hr, finance, admin      |
| `onboarding.txt`        | public         | intern, engineer, hr, finance, admin      |
| `hr_policy.txt`         | confidential   | hr, admin                                 |
| `q4_financials.txt`     | restricted     | finance, admin                            |
| `engineering_guide.txt` | internal       | engineer, admin                           |

---

## Chat History Design

Each query carries the last N conversation turns from the client:

```
POST /query
{
  "query": "What about the monthly burn rate?",
  "history": [
    { "role": "user",      "content": "What was Q4 revenue?" },
    { "role": "assistant", "content": "Q4 revenue was $4.2M..." }
  ]
}
```

- **Retrieval** uses only the current query — best for focused semantic search
- **LLM call** receives: `[system_prompt, ...history[-10:], current_user_message]`
- History is stored client-side in JS — resets on sign-out or "Clear" button
- Capped at 10 messages server-side before sending to Groq (token budget)

---

## Security Design

### 1. CORS
Restricted to `ALLOWED_ORIGIN` env var — no wildcard `*`.
`allow_credentials=True` required for httpOnly cookie to be sent cross-origin.

### 2. JWT in httpOnly Cookie (XSS Protection)
- `httpOnly=True` — JS cannot read or steal the token
- `secure=IS_PROD` — `True` on Render (HTTPS), `False` on localhost (HTTP)
- `samesite="strict"` — blocks CSRF by not sending cookie on cross-site requests

### 3. Prompt Injection Defense
User query wrapped in XML tags, isolated from system instructions:
```
<documents>
  [retrieved context]
</documents>
<user_query>
  [sanitized user input]
</user_query>
```
System prompt instructs the LLM: treat `<user_query>` as data only.

### 4. Input Validation (Pydantic)
```python
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)

class RegisterRequest(BaseModel):
    username:   str = Field(..., min_length=2, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password:   str = Field(..., min_length=8, max_length=128)
    department: str = Field(..., min_length=1, max_length=64)
    role:       str
```

### 5. Rate Limiting
`slowapi`: 20 requests/minute per IP on `/query`. Protects the Groq API key.

### 6. Security Headers (Middleware)
Applied to every response:
```
X-Content-Type-Options:  nosniff
X-Frame-Options:         DENY
Strict-Transport-Security: max-age=31536000; includeSubDomains
Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'
Referrer-Policy:         no-referrer
```

### 7. Output Safety
- LLM responses rendered as `textContent` — never `innerHTML` — in the browser
- No chunk IDs, `allowed_roles` lists, or internal metadata returned to client
- Generic error messages — no stack traces, no file paths

### 8. Password Security
- `bcrypt` cost factor 12 for both registration and login hashing
- Constant-time comparison in `verify_login` to prevent timing attacks
- Passwords never logged, never returned in any response

### 9. Admin Role Protection
- `admin` excluded from `ALLOWED_REGISTER_ROLES`
- `/audit/report` endpoint gated by `admin` role check after JWT verification

### 10. Secrets Management
- `.env` in `.gitignore` — never committed
- `.env.example` (empty values) committed for reference
- Secrets set in Render dashboard environment variables only

---

## Dataset — Acme Corp (Fictional Company)

Five realistic documents that make permission boundaries immediately visible in the demo:

| File                    | Content highlights                                        | Why useful for demo                              |
|-------------------------|-----------------------------------------------------------|--------------------------------------------------|
| `company_faq.txt`       | Mission, product, offices, headcount                     | Everyone answers → baseline test                 |
| `onboarding.txt`        | Tools, benefits enrollment, expense policy               | Everyone answers → baseline test                 |
| `hr_policy.txt`         | Comp bands (L1–L5), parental leave (16 wks), PIP process | Numbers leak instantly if permissions break      |
| `q4_financials.txt`     | Revenue $4.2M, burn $1.27M/mo, ARR $15.2M, Series B     | Specific numbers make leakage unmistakable       |
| `engineering_guide.txt` | AWS/EKS architecture, ArgoCD deploys, on-call process    | Tech details obvious to an engineer reviewer     |

---

## API Endpoints

| Method | Path             | Auth              | Description                                      |
|--------|------------------|-------------------|--------------------------------------------------|
| GET    | `/`              | none              | Serves the web chat UI                           |
| POST   | `/login`         | none              | Verifies creds, sets httpOnly JWT cookie         |
| POST   | `/register`      | none              | Creates account, validates role, auto-login      |
| POST   | `/logout`        | none              | Clears JWT cookie                                |
| POST   | `/query`         | JWT required      | Permission-gated RAG with chat history           |
| GET    | `/audit/report`  | JWT + admin role  | Returns last 50 query audit entries              |

---

## Web UI

Single-page HTML/JS served by FastAPI — no build step, no framework:

```
┌─────────────────────────────────────────────────────┐
│  Acme Corp Internal Assistant                       │
├─────────────────────────────────────────────────────┤
│  [ Sign in ]  [ Create account ]   ← tabs           │
│                                                     │
│  Login tab:         Register tab:                   │
│  Username           Username  | Department          │
│  Password           Password  | Confirm             │
│  [Sign in]          Role dropdown                   │
│                     [Create account]                │
├─────────────────────────────────────────────────────┤
│  bob · Finance · Acme Corp  [finance]  [Clear] [Sign out]│
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │  bob                                         │  │
│  │                       What was Q4 revenue? ▶ │  │
│  │  Assistant                                   │  │
│  │  ◀ Q4 revenue was $4.2M, up 18% YoY...       │  │
│  │    [q4_financials.txt] [39 chunks blocked]   │  │
│  │    [294ms]                                   │  │
│  │                                              │  │
│  │  bob                                         │  │
│  │                  What about burn rate? ▶     │  │
│  │  Assistant                                   │  │
│  │  ◀ Monthly burn rate was $1.27M (Q4 avg)...  │  │
│  └──────────────────────────────────────────────┘  │
│  [Ask a question…                      ] [▶]        │
└─────────────────────────────────────────────────────┘
```

---

## Component Breakdown

| File                    | Responsibility                                                  |
|-------------------------|-----------------------------------------------------------------|
| `main.py`               | FastAPI app, all middleware, all routes                         |
| `auth.py`               | `verify_login`, `register_user`, `issue_token`, `decode_token` |
| `roles.py`              | `ROLE_HIERARCHY` dict + `expand_roles()`                        |
| `ingest.py`             | Chunk → embed → store in ChromaDB with role metadata           |
| `retriever.py`          | Permission-filtered vector search, returns chunks + blocked count|
| `rag.py`                | Context assembly + chat history threading + Groq LLM call      |
| `audit.py`              | Append-only `audit.jsonl` logger + report reader               |
| `eval.py`               | 25-case offline eval: permission safety + answer quality        |
| `static/index.html`     | Full chat UI — login/register tabs, bubbles, chips             |
| `data/employees.json`   | User/role store (simulated IdP, mutable by /register)          |
| `docs/*.txt`            | 5 Acme Corp documents with varied classifications              |
| `docs/*.meta.json`      | `{ allowed_roles, classification }` per document               |

---

## Project Structure

```
pacific-project/
├── main.py
├── auth.py
├── roles.py
├── ingest.py
├── retriever.py
├── rag.py
├── audit.py
├── eval.py
├── data/
│   └── employees.json
├── docs/
│   ├── company_faq.txt         + .meta.json   (public)
│   ├── onboarding.txt          + .meta.json   (public)
│   ├── hr_policy.txt           + .meta.json   (confidential)
│   ├── q4_financials.txt       + .meta.json   (restricted)
│   └── engineering_guide.txt   + .meta.json   (internal)
├── static/
│   └── index.html
├── db/                         ← ChromaDB (gitignored)
├── logs/
│   └── audit.jsonl             ← query log (gitignored)
├── requirements.txt
├── .env.example
├── .gitignore
├── plan.md
└── README.md
```

---

## Tech Stack

| Component        | Library / Tool                     | Notes                                          |
|------------------|------------------------------------|------------------------------------------------|
| Web framework    | `fastapi` + `uvicorn`              | Async, Pydantic validation built-in            |
| Embeddings       | `sentence-transformers`            | `all-MiniLM-L6-v2`, runs fully locally         |
| Vector store     | `chromadb`                         | Persistent local DB, metadata-filtered search  |
| LLM              | `groq` (`llama-3.1-8b-instant`)    | Free tier, ultra-low TTFT via Groq LPU         |
| JWT              | `pyjwt`                            | HS256 signing                                  |
| Password hashing | `bcrypt`                           | Cost factor 12                                 |
| Rate limiting    | `slowapi`                          | Per-IP, 20 req/min on /query                   |
| Input validation | `pydantic`                         | Built into FastAPI                             |
| Audit logging    | `jsonlines`                        | Append-only JSONL                              |
| Eval output      | `tabulate`                         | CLI table formatting                           |
| Config           | `python-dotenv`                    | Explicit path loading for reliability          |

---

## Implementation Steps (Completed)

- [x] **Step 1**: Scaffold structure, `requirements.txt`, `.env.example`, `.gitignore`
- [x] **Step 2**: `roles.py` — hierarchy + `expand_roles()`
- [x] **Step 3**: `data/employees.json` — 5 seed users, bcrypt-hashed passwords
- [x] **Step 4**: 5 docs + `.meta.json` files in `docs/`
- [x] **Step 5**: `ingest.py` — chunk, embed, store with role metadata
- [x] **Step 6**: `retriever.py` — permission-filtered vector search
- [x] **Step 7**: `rag.py` — context assembly + chat history + Groq call
- [x] **Step 8**: `auth.py` — login, register, JWT issue/verify
- [x] **Step 9**: `main.py` — FastAPI, CORS, rate limit, security headers, all routes
- [x] **Step 10**: `static/index.html` — tabbed auth + full chat bubble UI
- [x] **Step 11**: `audit.py` — JSONL logger + report endpoint
- [x] **Step 12**: `eval.py` — 25-case permission + quality eval harness
- [x] **Step 13**: `README.md` — recruiter-facing setup + API guide
- [ ] **Step 14**: Deploy to Render, set env vars, verify end-to-end
- [ ] **Step 15**: Run `eval.py`, confirm zero permission leakage

---

## Key Demo Scenario

```
1. Open the app URL

2. Log in as eve / secret123  (intern)
   Ask: "What was Q4 revenue?"
   → "I don't have access to information relevant to that question."
   Chips: [company_faq.txt] [39 chunks blocked] [310ms]

3. Log in as bob / secret123  (finance)
   Ask: "What was Q4 revenue?"
   → "Q4 revenue was $4.2M, subscription $3.6M (86%)..."
   Chips: [q4_financials.txt] [0 chunks blocked] [294ms]

   Follow-up: "What about the monthly burn rate?"
   → "Monthly burn rate was $1.27M (Q4 average)."
   ← LLM used prior turn as context — no need to repeat the question

4. Register a brand new account
   Username: testuser | Dept: Marketing | Role: finance | PW: pass1234
   → Lands directly in chat, immediately queries financial data

5. Log in as charlie / secret123  (admin)
   Ask: "What is the parental leave policy and what was our Q4 burn rate?"
   → Answers both questions from hr_policy + q4_financials
   Chips: [hr_policy.txt] [q4_financials.txt] [0 chunks blocked]
```

---

## What This Demonstrates for Pacific

| Pacific Priority   | How This Project Addresses It                                         |
|--------------------|-----------------------------------------------------------------------|
| Context Management | Only permitted, relevant context reaches the LLM; token budget enforced |
| Permissions        | JWT roles + hierarchy expansion + ChromaDB metadata filter at DB layer |
| Search             | Semantic similarity search (cosine) over 45 document chunks           |
| TTFT               | Groq LPU hardware — sub-300ms responses on permitted queries          |
| Agentic Workflows  | Register → Auth → Retrieve → Assemble → LLM → Audit pipeline         |
| Evals              | 25-case harness: permission safety (no leakage) + answer quality      |
| Audit / Governance | Every query logged: user, roles, sources used, chunks blocked, latency |
| Security           | httpOnly cookie, prompt injection defense, rate limiting, CSP headers |
