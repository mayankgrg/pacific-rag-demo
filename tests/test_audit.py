"""
Unit tests for audit.py — log_query() and get_report()
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import audit
from audit import log_query, get_report


# ── Helpers ───────────────────────────────────────────────────────────────────

def _redirect_audit(tmp_path):
    """Context helper that redirects LOGS_DIR and AUDIT_FILE to a temp path."""
    logs_dir = tmp_path / "logs"
    audit_file = logs_dir / "audit.jsonl"
    return logs_dir, audit_file


# ── log_query() ───────────────────────────────────────────────────────────────

class TestLogQuery:
    def test_log_creates_file(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("alice", ["hr"], "What is the leave policy?", ["hr_policy"], 30, 150)
        assert audit_file.exists()

    def test_log_writes_valid_json(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("alice", ["hr"], "test query", ["hr_policy"], 5, 200)
        line = audit_file.read_text(encoding="utf-8").strip()
        entry = json.loads(line)   # should not raise
        assert isinstance(entry, dict)

    def test_log_entry_has_required_fields(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("bob", ["finance"], "Q4 revenue?", ["q4_financials"], 39, 294)
        entry = json.loads(audit_file.read_text(encoding="utf-8").strip())
        for field in ("timestamp", "username", "roles", "query", "sources_used",
                      "chunks_blocked", "latency_ms"):
            assert field in entry

    def test_log_records_correct_username(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("charlie", ["admin"], "anything", [], 0, 100)
        entry = json.loads(audit_file.read_text(encoding="utf-8").strip())
        assert entry["username"] == "charlie"

    def test_log_records_correct_roles(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("alice", ["hr", "intern"], "question", [], 10, 120)
        entry = json.loads(audit_file.read_text(encoding="utf-8").strip())
        assert entry["roles"] == ["hr", "intern"]

    def test_log_truncates_long_query(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        long_query = "x" * 300
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("alice", ["hr"], long_query, [], 0, 100)
        entry = json.loads(audit_file.read_text(encoding="utf-8").strip())
        assert len(entry["query"]) == 200

    def test_log_does_not_truncate_short_query(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("alice", ["hr"], "short query", [], 0, 100)
        entry = json.loads(audit_file.read_text(encoding="utf-8").strip())
        assert entry["query"] == "short query"

    def test_log_creates_logs_dir_if_missing(self, tmp_path):
        logs_dir = tmp_path / "new_logs"
        audit_file = logs_dir / "audit.jsonl"
        assert not logs_dir.exists()
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("alice", ["hr"], "query", [], 0, 100)
        assert logs_dir.exists()

    def test_multiple_entries_appended(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("alice", ["hr"], "first",  [], 0, 100)
            log_query("bob",   ["finance"], "second", [], 0, 200)
            log_query("eve",   ["intern"], "third",  [], 0, 300)
        lines = [l for l in audit_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 3

    def test_log_timestamp_is_utc_iso(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("alice", ["hr"], "query", [], 0, 100)
        entry = json.loads(audit_file.read_text(encoding="utf-8").strip())
        # ISO format with UTC offset: ends with +00:00 or Z
        ts = entry["timestamp"]
        assert "+00:00" in ts or ts.endswith("Z")

    def test_log_records_chunks_blocked(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("eve", ["intern"], "query", [], 39, 100)
        entry = json.loads(audit_file.read_text(encoding="utf-8").strip())
        assert entry["chunks_blocked"] == 39

    def test_log_records_sources(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("bob", ["finance"], "q", ["q4_financials", "company_faq"], 30, 100)
        entry = json.loads(audit_file.read_text(encoding="utf-8").strip())
        assert entry["sources_used"] == ["q4_financials", "company_faq"]


# ── get_report() ─────────────────────────────────────────────────────────────

class TestGetReport:
    def test_get_report_no_file_returns_empty(self, tmp_path):
        logs_dir = tmp_path / "logs"
        audit_file = logs_dir / "audit.jsonl"
        with patch.object(audit, "AUDIT_FILE", audit_file):
            report = get_report()
        assert report == {"total_queries": 0, "entries": []}

    def test_get_report_total_queries_matches_entries(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("alice", ["hr"], "q1", [], 0, 100)
            log_query("bob",   ["finance"], "q2", [], 0, 100)
            report = get_report()
        assert report["total_queries"] == 2
        assert len(report["entries"]) == 2

    def test_get_report_returns_last_50_entries(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            for i in range(60):
                log_query("alice", ["hr"], f"question {i}", [], 0, 100)
            report = get_report()
        assert report["total_queries"] == 60
        assert len(report["entries"]) == 50
        # Should be the LAST 50, so last one should be "question 59"
        assert report["entries"][-1]["query"] == "question 59"

    def test_get_report_entries_are_dicts(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        with patch.object(audit, "LOGS_DIR", logs_dir), \
             patch.object(audit, "AUDIT_FILE", audit_file):
            log_query("alice", ["hr"], "query", [], 0, 100)
            report = get_report()
        assert all(isinstance(e, dict) for e in report["entries"])

    def test_get_report_skips_blank_lines(self, tmp_path):
        logs_dir, audit_file = _redirect_audit(tmp_path)
        logs_dir.mkdir()
        entry = json.dumps({
            "timestamp": "2025-01-01T00:00:00+00:00",
            "username": "alice", "roles": ["hr"], "query": "q",
            "sources_used": [], "chunks_blocked": 0, "latency_ms": 100
        })
        # Write with blank lines interspersed
        audit_file.write_text(f"\n{entry}\n\n{entry}\n\n", encoding="utf-8")
        with patch.object(audit, "AUDIT_FILE", audit_file):
            report = get_report()
        assert report["total_queries"] == 2
