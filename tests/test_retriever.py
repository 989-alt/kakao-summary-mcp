"""Tests for retriever.search.semantic_query where-clause building.

These tests monkeypatch chroma_store.search so no real ChromaDB or embedding
model is invoked — they purely verify the shape of the `where` argument
that semantic_query passes down.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import kakao_summary_mcp.indexer.chroma_store as chroma_store_mod
from kakao_summary_mcp.retriever.search import semantic_query


FAKE_PATH = Path("/tmp/fake_chroma")


def _capture_where(chroma_path, query, where=None, top_k=15,
                   model_name="BAAI/bge-m3", device="cpu"):
    """Replacement for chroma_store.search that just returns the where arg."""
    return [{"_where": where}]


@pytest.fixture(autouse=True)
def patch_search(monkeypatch):
    """Monkeypatch chroma_store.search for all tests in this module."""
    monkeypatch.setattr(chroma_store_mod, "search", _capture_where)


class TestSemanticQueryWhereBuilder:
    def _get_where(self, **kwargs) -> dict | None:
        results = semantic_query(FAKE_PATH, "test query", **kwargs)
        return results[0]["_where"]

    def test_no_filters_gives_none(self):
        where = self._get_where()
        assert where is None

    def test_room_only_gives_single_clause(self):
        where = self._get_where(room="채팅방1")
        assert where == {"room": {"$eq": "채팅방1"}}

    def test_date_only_gives_single_clause(self):
        where = self._get_where(date="2026-05-26")
        assert where == {"date": {"$eq": "2026-05-26"}}

    def test_both_room_and_date_gives_and_wrapped(self):
        """Regression test: multi-key dict caused ChromaDB ValueError."""
        where = self._get_where(room="채팅방1", date="2026-05-26")
        assert where is not None
        assert "$and" in where, (
            f"Expected $and wrapper for multi-filter, got: {where!r}"
        )
        clauses = where["$and"]
        assert isinstance(clauses, list)
        assert len(clauses) == 2
        # Both individual clauses must be present
        assert {"room": {"$eq": "채팅방1"}} in clauses
        assert {"date": {"$eq": "2026-05-26"}} in clauses

    def test_and_clauses_not_multi_key_dict(self):
        """The old buggy code would produce {"room": ..., "date": ...}.
        Verify the new code does NOT produce a multi-key top-level dict."""
        where = self._get_where(room="room", date="2026-05-26")
        # Must not be a plain 2-key dict
        assert not (
            isinstance(where, dict)
            and "room" in where
            and "date" in where
            and "$and" not in where
        ), "Old buggy multi-key dict shape detected"
