"""
Audit logger.

Appends a structured JSON line for every query to logs/audit.jsonl.
Each entry records: timestamp, user, roles, query, sources used,
chunks blocked, and latency. No answer text is stored (PII-safe).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

LOGS_DIR = Path(__file__).parent / "logs"
AUDIT_FILE = LOGS_DIR / "audit.jsonl"


def log_query(
    username: str,
    roles: list[str],
    query: str,
    sources: list[str],
    chunks_blocked: int,
    latency_ms: int,
) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    entry = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "username": username,
        "roles": roles,
        "query": query[:200],   # truncate for log safety
        "sources_used": sources,
        "chunks_blocked": chunks_blocked,
        "latency_ms": latency_ms,
    }
    with AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def get_report() -> dict:
    """Return a summary of all logged queries."""
    if not AUDIT_FILE.exists():
        return {"total_queries": 0, "entries": []}

    entries = []
    with AUDIT_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    return {
        "total_queries": len(entries),
        "entries": entries[-50:],  # return last 50 only
    }
