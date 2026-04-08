"""
Unit tests for rag.py — sanitize_query(), assemble_context(), query()
"""

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("JWT_SECRET", "test-secret-key-that-is-long-enough-32chars")

from rag import sanitize_query, assemble_context, query, MAX_CONTEXT_CHARS, MAX_HISTORY_TURNS, RAGResponse
from retriever import RetrievalResult


# ── sanitize_query() ──────────────────────────────────────────────────────────

class TestSanitizeQuery:
    def test_strips_leading_whitespace(self):
        assert sanitize_query("   hello") == "hello"

    def test_strips_trailing_whitespace(self):
        assert sanitize_query("hello   ") == "hello"

    def test_strips_both_ends(self):
        assert sanitize_query("  hello world  ") == "hello world"

    def test_caps_at_500_chars(self):
        long_input = "a" * 600
        result = sanitize_query(long_input)
        assert len(result) == 500

    def test_exactly_500_chars_unchanged(self):
        exact = "a" * 500
        assert sanitize_query(exact) == exact

    def test_short_query_unchanged(self):
        assert sanitize_query("What is the policy?") == "What is the policy?"

    def test_empty_string_returns_empty(self):
        assert sanitize_query("") == ""

    def test_only_whitespace_returns_empty(self):
        assert sanitize_query("   \t\n  ") == ""

    def test_strips_then_caps(self):
        """Whitespace is stripped BEFORE the 500-char cap is applied."""
        padded = "  " + "x" * 500 + "  "
        result = sanitize_query(padded)
        assert len(result) == 500
        assert result == "x" * 500

    def test_newlines_stripped_from_ends(self):
        assert sanitize_query("\nhello\n") == "hello"


# ── assemble_context() ────────────────────────────────────────────────────────

class TestAssembleContext:
    def test_basic_assembly_includes_source(self):
        result = assemble_context(["Some text here."], ["hr_policy"])
        assert "hr_policy" in result
        assert "Some text here." in result

    def test_format_includes_chunk_number(self):
        result = assemble_context(["Text."], ["src"])
        assert "[1]" in result

    def test_multiple_chunks_numbered_sequentially(self):
        chunks  = ["First chunk.", "Second chunk."]
        sources = ["doc_a", "doc_b"]
        result  = assemble_context(chunks, sources)
        assert "[1]" in result
        assert "[2]" in result

    def test_chunks_joined_by_double_newline(self):
        chunks  = ["Chunk one.", "Chunk two."]
        sources = ["a", "b"]
        result  = assemble_context(chunks, sources)
        assert "\n\n" in result

    def test_empty_chunks_returns_empty_string(self):
        assert assemble_context([], []) == ""

    def test_respects_max_context_chars(self):
        big_chunk = "x" * (MAX_CONTEXT_CHARS + 100)
        result = assemble_context([big_chunk], ["src"])
        # The single chunk exceeds the budget, so nothing should be appended
        assert result == ""

    def test_stops_adding_when_budget_exceeded(self):
        """First chunk fits; second would exceed budget."""
        half = MAX_CONTEXT_CHARS // 2
        chunks  = ["a" * half, "b" * half, "c" * half]
        sources = ["s1", "s2", "s3"]
        result  = assemble_context(chunks, sources)
        # At least the first chunk is present
        assert "s1" in result
        # Third chunk definitely should not fit
        assert "s3" not in result

    def test_single_chunk_with_long_source_name(self):
        result = assemble_context(["data"], ["very_long_source_name_here"])
        assert "very_long_source_name_here" in result

    def test_source_and_text_both_present(self):
        result = assemble_context(["policy text"], ["hr_policy"])
        assert "policy text" in result
        assert "hr_policy" in result


# ── query() ───────────────────────────────────────────────────────────────────

class TestRagQuery:
    def _make_retrieval_result(self, chunks=None, sources=None, blocked=0):
        return RetrievalResult(
            chunks=chunks or ["Here is some relevant content."],
            sources=sources or ["hr_policy"],
            scores=[0.9],
            chunks_blocked=blocked,
        )

    def test_no_chunks_returns_no_access_message(self):
        empty_result = RetrievalResult(chunks=[], sources=[], scores=[], chunks_blocked=10)
        with patch("rag.retrieve", return_value=empty_result):
            response = query("What is Q4 revenue?", ["intern"])
        assert "don't have access" in response.answer
        assert response.sources == []
        assert response.chunks_blocked == 10

    def test_no_chunks_latency_is_positive(self):
        empty_result = RetrievalResult(chunks=[], sources=[], scores=[], chunks_blocked=5)
        with patch("rag.retrieve", return_value=empty_result):
            response = query("anything", ["intern"])
        assert response.latency_ms >= 0

    def test_successful_query_returns_answer(self):
        retrieval = self._make_retrieval_result()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value.choices[0].message.content = "The policy is 12 weeks."
        with patch("rag.retrieve", return_value=retrieval), \
             patch("rag.groq_lib.Groq", return_value=mock_client):
            response = query("What is the parental leave policy?", ["hr"])
        assert response.answer == "The policy is 12 weeks."

    def test_sources_are_deduplicated(self):
        retrieval = RetrievalResult(
            chunks=["chunk1", "chunk2"],
            sources=["hr_policy", "hr_policy"],
            scores=[0.9, 0.8],
            chunks_blocked=0,
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value.choices[0].message.content = "Answer."
        with patch("rag.retrieve", return_value=retrieval), \
             patch("rag.groq_lib.Groq", return_value=mock_client):
            response = query("question?", ["hr"])
        assert response.sources.count("hr_policy") == 1

    def test_chunks_blocked_passed_through(self):
        retrieval = self._make_retrieval_result(blocked=39)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value.choices[0].message.content = "Answer."
        with patch("rag.retrieve", return_value=retrieval), \
             patch("rag.groq_lib.Groq", return_value=mock_client):
            response = query("question?", ["finance"])
        assert response.chunks_blocked == 39

    def test_authentication_error_returns_error_message(self):
        import groq as groq_lib_real
        retrieval = self._make_retrieval_result()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = groq_lib_real.AuthenticationError(
            message="invalid key", response=MagicMock(status_code=401), body={}
        )
        with patch("rag.retrieve", return_value=retrieval), \
             patch("rag.groq_lib.Groq", return_value=mock_client):
            response = query("question?", ["hr"])
        assert "invalid API key" in response.answer.lower() or "LLM error" in response.answer

    def test_rate_limit_error_returns_error_message(self):
        import groq as groq_lib_real
        retrieval = self._make_retrieval_result()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = groq_lib_real.RateLimitError(
            message="rate limited", response=MagicMock(status_code=429), body={}
        )
        with patch("rag.retrieve", return_value=retrieval), \
             patch("rag.groq_lib.Groq", return_value=mock_client):
            response = query("question?", ["hr"])
        assert "rate limit" in response.answer.lower() or "LLM error" in response.answer

    def test_history_none_defaults_to_empty(self):
        retrieval = self._make_retrieval_result()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value.choices[0].message.content = "OK."
        with patch("rag.retrieve", return_value=retrieval), \
             patch("rag.groq_lib.Groq", return_value=mock_client):
            response = query("question?", ["hr"], history=None)
        assert response.answer == "OK."

    def test_history_trimmed_to_max_turns(self):
        """History longer than MAX_HISTORY_TURNS is trimmed from the front."""
        retrieval = self._make_retrieval_result()
        captured = {}
        def fake_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            mock_resp = MagicMock()
            mock_resp.choices[0].message.content = "Done."
            return mock_resp

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = fake_create

        long_history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(MAX_HISTORY_TURNS + 4)
        ]
        with patch("rag.retrieve", return_value=retrieval), \
             patch("rag.groq_lib.Groq", return_value=mock_client):
            query("new question", ["hr"], history=long_history)

        # messages = [system] + trimmed_history + [current user msg]
        # trimmed_history should be at most MAX_HISTORY_TURNS entries
        history_in_call = captured["messages"][1:-1]  # strip system + last user turn
        assert len(history_in_call) <= MAX_HISTORY_TURNS

    def test_response_is_rag_response_instance(self):
        empty_result = RetrievalResult(chunks=[], sources=[], scores=[], chunks_blocked=0)
        with patch("rag.retrieve", return_value=empty_result):
            response = query("q", ["intern"])
        assert isinstance(response, RAGResponse)

    def test_sanitize_called_on_query(self):
        """Leading/trailing whitespace in the query is stripped before retrieval."""
        retrieval = self._make_retrieval_result()
        captured = {}
        def fake_retrieve(q, roles):
            captured["query"] = q
            return retrieval

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value.choices[0].message.content = "OK."
        with patch("rag.retrieve", side_effect=fake_retrieve), \
             patch("rag.groq_lib.Groq", return_value=mock_client):
            query("  padded query  ", ["hr"])
        assert captured["query"] == "padded query"
