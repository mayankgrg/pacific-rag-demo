# Permission-Aware RAG — Acme Corp Internal Assistant

A web-based RAG chatbot where the AI answers questions **only from documents the
logged-in user is permitted to see**. Built as a Pacific internship project.

Live demo: *(add Render URL after deploy)*

---

## What it does

- Employees log in (or register) and get a **signed JWT** carrying their role
- Every query runs a **role-filtered semantic search** — restricted documents are
  excluded at the vector DB layer before the LLM ever sees them
- Same question, different roles → different answers (or "no access")
- **Full chat history** — the LLM remembers the last 5 exchanges per session
- Every query is **audit-logged**: who asked, which docs were used, how many
  chunks were blocked

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.9+ | 3.11 recommended |
| Groq API key | free | [console.groq.com](https://console.groq.com) → Create API key |

That's it. All other dependencies install locally via pip.

---

## Local Setup (5 steps)

### 1. Clone and create a virtual environment

```bash
git clone <repo-url>
cd pacific-project
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> First install downloads the `all-MiniLM-L6-v2` embedding model (~90 MB). Subsequent runs use the local cache.

### 3. Set environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in two values:

```
GROQ_API_KEY=gsk_...          # from console.groq.com (free)
JWT_SECRET=any-random-32-char-string-here
ALLOWED_ORIGIN=http://localhost:8000
```

> To generate a strong JWT secret:
> ```bash
> python3 -c "import secrets; print(secrets.token_hex(32))"
> ```

### 4. Build the vector database

```bash
python ingest.py
```

Expected output:
```
Loading documents...
  Found 5 documents.
Loading embedding model (all-MiniLM-L6-v2)...
  company_faq:       9 chunks  [public]
  onboarding:        9 chunks  [public]
  hr_policy:        10 chunks  [confidential]
  q4_financials:     6 chunks  [restricted]
  engineering_guide:11 chunks  [internal]

Done. 45 total chunks stored in ChromaDB.
```

> Only needed once. Re-run if you change documents.

### 5. Start the server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open **[http://localhost:8000](http://localhost:8000)**

---

## Demo Credentials

All passwords: `secret123`

| Username | Role     | Can access |
|----------|----------|------------|
| `charlie` | admin    | All documents |
| `alice`   | hr       | HR policy + public |
| `bob`     | finance  | Q4 financials + public |
| `diana`   | engineer | Engineering guide + public |
| `eve`     | intern   | Public documents only |

---

## Suggested Demo Flow

**1. Try the permission wall**
Log in as `eve` (intern), ask:
> *"What was Q4 revenue?"*

You'll get: *"I don't have access to information relevant to that question."*

**2. See what finance can see**
Log in as `bob` (finance), ask the same question:
> *"What was Q4 revenue?"*

You'll get exact numbers from the financial report — `$4.2M, up 18% YoY`.

**3. Test chat history**
As `bob`, ask a follow-up without repeating context:
> *"What about the monthly burn rate?"*

The LLM answers correctly using the previous turn.

**4. Try admin's full access**
Log in as `charlie` (admin), ask:
> *"What is the parental leave policy and what was our Q4 burn rate?"*

Gets answers from **both** `hr_policy.txt` and `q4_financials.txt` in one response.

**5. Register a new user**
Click **Create account**, choose any role (e.g. `finance`), and you're immediately
logged in and chatting — no second login needed.

---

## API Reference

All endpoints accept/return JSON. The JWT is handled via cookie automatically
in the browser. For curl testing, use a cookie jar (`-c` / `-b`).

---

### `POST /login`

Authenticate and receive a JWT cookie.

```bash
curl -c /tmp/cookies.txt -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"username": "bob", "password": "secret123"}'
```

**Response `200`**
```json
{
  "username": "bob",
  "department": "Finance",
  "roles": ["finance"]
}
```

**Response `401`**
```json
{ "error": "Invalid username or password." }
```

---

### `POST /register`

Create a new account. Auto-issues JWT cookie on success.
Allowed roles: `hr`, `finance`, `engineer`, `intern` (admin is blocked).

```bash
curl -c /tmp/cookies.txt -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{
    "username":   "maya",
    "password":   "mypassword1",
    "department": "Finance",
    "role":       "finance"
  }'
```

**Response `200`**
```json
{
  "username": "maya",
  "department": "Finance",
  "roles": ["finance"]
}
```

**Response `409`** — username taken
```json
{ "error": "Username already taken." }
```

**Response `400`** — invalid role or weak password
```json
{ "error": "Invalid role. Choose from: hr, finance, engineer, intern" }
```

---

### `POST /query`

Ask a question. Requires a valid JWT cookie (set by `/login` or `/register`).
Optionally include previous conversation turns in `history`.

```bash
# Turn 1 — no history
curl -b /tmp/cookies.txt -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What was Q4 revenue?", "history": []}'
```

**Response `200`**
```json
{
  "answer": "Q4 revenue was $4.2M. Subscription revenue made up $3.6M (86%)...",
  "sources": ["q4_financials", "company_faq"],
  "chunks_blocked": 39,
  "latency_ms": 294
}
```

```bash
# Turn 2 — with history
curl -b /tmp/cookies.txt -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What about the monthly burn rate?",
    "history": [
      {"role": "user",      "content": "What was Q4 revenue?"},
      {"role": "assistant", "content": "Q4 revenue was $4.2M..."}
    ]
  }'
```

**Response `200`**
```json
{
  "answer": "The monthly burn rate was $1.27M (Q4 average).",
  "sources": ["q4_financials"],
  "chunks_blocked": 39,
  "latency_ms": 312
}
```

**Response `401`** — no cookie / expired token
```json
{ "error": "Not authenticated." }
```

**Response `429`** — rate limit (20 req/min per IP)
```json
{ "error": "Rate limit exceeded: 20 per 1 minute" }
```

---

### `POST /logout`

Clears the JWT cookie.

```bash
curl -b /tmp/cookies.txt -c /tmp/cookies.txt \
  -X POST http://localhost:8000/logout
```

**Response `200`**
```json
{ "message": "Logged out." }
```

---

### `GET /audit/report`

Returns the last 50 query audit entries. **Admin role required.**

```bash
# Log in as charlie (admin) first
curl -c /tmp/admin_cookies.txt -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"username": "charlie", "password": "secret123"}'

curl -b /tmp/admin_cookies.txt http://localhost:8000/audit/report
```

**Response `200`**
```json
{
  "total_queries": 12,
  "entries": [
    {
      "timestamp": "2025-04-08T03:12:44+00:00",
      "username": "bob",
      "roles": ["finance"],
      "query": "What was Q4 revenue?",
      "sources_used": ["q4_financials", "company_faq"],
      "chunks_blocked": 39,
      "latency_ms": 294
    }
  ]
}
```

**Response `403`** — not admin
```json
{ "error": "Admin access required." }
```

---

## Running the Eval Harness

Runs 25 test cases across all roles. Checks permission safety (no data leakage)
and answer quality. Requires the server to **not** be running (uses the pipeline directly).

```bash
python eval.py
```

Expected output:
```
╭──────────────┬──────────────────────────────────┬───────────────┬──────────┬────────────┬─────────┬────────╮
│ Role         │ Query                            │ Should answer │ Answered │ Perm safe  │ Latency │ Result │
├──────────────┼──────────────────────────────────┼───────────────┼──────────┼────────────┼─────────┼────────┤
│ intern       │ What was Q4 revenue?             │ no            │ no       │ SAFE       │ 310ms   │ PASS   │
│ finance      │ What was Q4 revenue?             │ yes           │ yes      │ SAFE       │ 294ms   │ PASS   │
│ hr           │ What is the parental leave…      │ yes           │ yes      │ SAFE       │ 420ms   │ PASS   │
│ engineer     │ What is the parental leave…      │ no            │ no       │ SAFE       │ 290ms   │ PASS   │
│ ...          │ ...                              │ ...           │ ...      │ ...        │ ...     │ ...    │
╰──────────────┴──────────────────────────────────┴───────────────┴──────────┴────────────┴─────────┴────────╯

25/25 tests passed. All permission checks clean.
```

---

## Deploying to Render

1. Push repo to GitHub (ensure `db/`, `logs/`, `.env` are in `.gitignore`)
2. Create a **Web Service** on [render.com](https://render.com), connect your repo
3. Set:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables in Render dashboard:
   - `GROQ_API_KEY` = your key from console.groq.com
   - `JWT_SECRET` = 32+ char random string
   - `ALLOWED_ORIGIN` = `https://<your-app>.onrender.com`
5. Deploy — the app auto-ingests documents on first startup

---

## Security Highlights

| Concern | What we do |
|---|---|
| **XSS** | JWT in `httpOnly` cookie — JS can never read it |
| **XSS output** | LLM responses rendered as `textContent`, never `innerHTML` |
| **CSRF** | `SameSite=Strict` cookie — not sent on cross-site requests |
| **Prompt injection** | Query wrapped in `<user_query>` XML, system prompt hardened |
| **Abuse** | Rate limiting: 20 queries/minute per IP via `slowapi` |
| **Input** | Pydantic validation on all request bodies; max 500-char query |
| **Headers** | CSP, X-Frame-Options, HSTS, X-Content-Type-Options on all responses |
| **Passwords** | `bcrypt` cost factor 12; constant-time comparison |
| **Secrets** | Loaded from env vars only; `.env` gitignored |
| **Admin** | Self-registration as `admin` is blocked at the API level |

---

## Project Structure

```
pacific-project/
├── main.py          FastAPI app, middleware, all routes
├── auth.py          Login, register, JWT issue/verify
├── roles.py         Role hierarchy + expand_roles()
├── ingest.py        Chunk → embed → ChromaDB
├── retriever.py     Permission-filtered vector search
├── rag.py           Context assembly + Groq LLM call
├── audit.py         Query audit logger + report
├── eval.py          Offline permission + quality evals
├── static/
│   └── index.html   Chat UI (login/register tabs, bubbles)
├── data/
│   └── employees.json
├── docs/            5 Acme Corp documents + .meta.json files
├── requirements.txt
├── .env.example
└── plan.md          Full architecture and design notes
```
