"""
Unit tests for retriever.py — filter building logic and RetrievalResult dataclass.

Retrieval tests mock ChromaDB and the embedding model to keep tests fast
and dependency-free (no GPU / no persistent DB required).
"""

import os
from dataclasses import fields
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-key-that-is-long-enough-32chars")

from retriever import RetrievalResult, retrieve, TOP_K
from roles import expand_roles


# ── RetrievalResult dataclass ─────────────────────────────────────────────────

class TestRetrievalResultDataclass:
    def test_can_instantiate(self):
        r = RetrievalResult(chunks=["a"], sources=["s"], scores=[0.9], chunks_blocked=0)
        assert r.chunks == ["a"]

    def test_all_four_fields_present(self):
        field_names = {f.name for f in fields(RetrievalResult)}
        assert field_names == {"chunks", "sources", "scores", "chunks_blocked"}

    def test_chunks_blocked_is_int(self):
        r = RetrievalResult(chunks=[], sources=[], scores=[], chunks_blocked=5)
        assert isinstance(r.chunks_blocked, int)

    def test_scores_is_list(self):
        r = RetrievalResult(chunks=["c"], sources=["s"], scores=[0.7], chunks_blocked=0)
        assert isinstance(r.scores, list)

    def test_empty_result_allowed(self):
        r = RetrievalResult(chunks=[], sources=[], scores=[], chunks_blocked=42)
        assert r.chunks_blocked == 42


# ── Permission filter construction ───────────────────────────────────────────
# These tests exercise the logic that builds the ChromaDB $or filter
# by patching the DB/model and inspecting the call arguments.

class TestPermissionFilter:
    def _make_mocks(self, total_in_db=45, n_chunks=3):
        """Return (mock_collection, mock_model) pre-wired with plausible return values."""
        mock_collection = MagicMock()
        mock_collection.count.return_value = total_in_db
        mock_collection.query.return_value = {
            "documents": [["chunk"] * n_chunks],
            "metadatas": [[{"source": f"doc{i}"} for i in range(n_chunks)]],
            "distances": [[0.1 * i for i in range(n_chunks)]],
        }
        mock_model = MagicMock()
        # encode() returns an object whose .tolist() returns the embedding list
        mock_model.encode.return_value.tolist.return_value = [[0.0] * 384]
        return mock_collection, mock_model

    def test_single_role_uses_plain_filter(self):
        """Single role → no $or wrapper, direct condition."""
        mock_col, mock_mod = self._make_mocks()
        with patch("retriever._get_collection", return_value=mock_col), \
             patch("retriever._get_model", return_value=mock_mod):
            retrieve("query", ["intern"])
        call_kwargs = mock_col.query.call_args.kwargs
        where = call_kwargs["where"]
        # Single role "intern" expands to {"intern"} → single condition, no $or
        assert "$or" not in where
        assert "role_intern" in where

    def test_multi_role_uses_or_filter(self):
        """Multiple expanded roles → $or filter."""
        mock_col, mock_mod = self._make_mocks()
        with patch("retriever._get_collection", return_value=mock_col), \
             patch("retriever._get_model", return_value=mock_mod):
            retrieve("query", ["hr"])  # hr expands to hr + intern → 2 roles → $or
        call_kwargs = mock_col.query.call_args.kwargs
        where = call_kwargs["where"]
        assert "$or" in where

    def test_admin_filter_contains_all_roles(self):
        """Admin expands to all 5 roles → $or with 5 conditions."""
        mock_col, mock_mod = self._make_mocks()
        with patch("retriever._get_collection", return_value=mock_col), \
             patch("retriever._get_model", return_value=mock_mod):
            retrieve("query", ["admin"])
        where = mock_col.query.call_args.kwargs["where"]
        conditions = where["$or"]
        role_keys = {list(c.keys())[0] for c in conditions}
        expected = {"role_admin", "role_hr", "role_finance", "role_engineer", "role_intern"}
        assert role_keys == expected

    def test_filter_conditions_use_eq_true(self):
        """Each condition must use $eq: True (not False or other values)."""
        mock_col, mock_mod = self._make_mocks()
        with patch("retriever._get_collection", return_value=mock_col), \
             patch("retriever._get_model", return_value=mock_mod):
            retrieve("query", ["admin"])
        where = mock_col.query.call_args.kwargs["where"]
        for condition in where["$or"]:
            key = list(condition.keys())[0]
            assert condition[key] == {"$eq": True}

    def test_top_k_passed_to_query(self):
        mock_col, mock_mod = self._make_mocks(n_chunks=TOP_K)
        with patch("retriever._get_collection", return_value=mock_col), \
             patch("retriever._get_model", return_value=mock_mod):
            retrieve("query", ["intern"])
        assert mock_col.query.call_args.kwargs["n_results"] == TOP_K

    def test_embedding_queried_with_user_text(self):
        mock_col, mock_mod = self._make_mocks()
        with patch("retriever._get_collection", return_value=mock_col), \
             patch("retriever._get_model", return_value=mock_mod):
            retrieve("What is the leave policy?", ["hr"])
        mock_mod.encode.assert_called_once_with(["What is the leave policy?"])


# ── RetrievalResult output from retrieve() ───────────────────────────────────

class TestRetrieveOutput:
    def _run_retrieve(self, roles, total=45, n_chunks=3):
        mock_col = MagicMock()
        mock_col.count.return_value = total
        mock_col.query.return_value = {
            "documents": [["chunk"] * n_chunks],
            "metadatas": [[{"source": f"doc{i}"} for i in range(n_chunks)]],
            "distances": [[0.1 * i for i in range(n_chunks)]],
        }
        mock_mod = MagicMock()
        mock_mod.encode.return_value.tolist.return_value = [[0.0] * 384]
        with patch("retriever._get_collection", return_value=mock_col), \
             patch("retriever._get_model", return_value=mock_mod):
            return retrieve("query", roles)

    def test_returns_retrieval_result_instance(self):
        result = self._run_retrieve(["intern"])
        assert isinstance(result, RetrievalResult)

    def test_chunks_blocked_equals_total_minus_returned(self):
        result = self._run_retrieve(["intern"], total=45, n_chunks=3)
        assert result.chunks_blocked == 42

    def test_chunks_blocked_never_negative(self):
        """If DB returns more chunks than total (shouldn't happen), clamp to 0."""
        result = self._run_retrieve(["admin"], total=2, n_chunks=6)
        assert result.chunks_blocked >= 0

    def test_scores_converted_from_distances(self):
        result = self._run_retrieve(["intern"], n_chunks=3)
        # distances were [0.0, 0.1, 0.2], scores = 1 - distance
        assert result.scores[0] == pytest.approx(1.0, abs=0.001)
        assert result.scores[1] == pytest.approx(0.9, abs=0.001)

    def test_sources_extracted_from_metadata(self):
        result = self._run_retrieve(["intern"], n_chunks=3)
        assert result.sources == ["doc0", "doc1", "doc2"]

    def test_result_chunks_match_returned_documents(self):
        result = self._run_retrieve(["intern"], n_chunks=3)
        assert result.chunks == ["chunk", "chunk", "chunk"]
