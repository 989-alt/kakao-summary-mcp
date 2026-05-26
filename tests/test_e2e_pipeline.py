"""End-to-end pipeline test with stubbed embedder.

Proves the full data path (parse → chunk → upsert → search → get_by_ids)
works without any network access or model downloads.

The embedder is monkeypatched BEFORE any import that would trigger the real
sentence-transformers model. We patch `kakao_summary_mcp.indexer.chroma_store.embed`
because chroma_store does `from .embedder import embed` at import time, so
the name `embed` inside that module is what we must replace.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from tests.conftest import fake_embed


@pytest.fixture
def chroma_tmp(tmp_path) -> Path:
    return tmp_path / "chroma"


@pytest.fixture(autouse=True)
def stub_embedder(monkeypatch):
    """Patch the embed function inside chroma_store before any ChromaDB calls."""
    import kakao_summary_mcp.indexer.chroma_store as cs
    monkeypatch.setattr(cs, "embed", fake_embed)


class TestE2EPipeline:
    def test_full_pipeline_no_error(self, sample_txt, chroma_tmp):
        """Smoke test: entire pipeline runs without raising."""
        from kakao_summary_mcp.indexer.chroma_store import upsert_turns
        from kakao_summary_mcp.indexer.chunker import messages_to_turns
        from kakao_summary_mcp.parser.regex_parser import parse_file
        from kakao_summary_mcp.retriever.search import semantic_query, turns_by_ids

        msgs = parse_file(sample_txt, room="e2e_room")
        assert len(msgs) > 0

        turns = messages_to_turns(msgs)
        assert len(turns) > 0

        n = upsert_turns(chroma_tmp, turns)
        assert n == len(turns)

        # Search with BOTH room and date — this was the buggy scenario.
        results = semantic_query(
            chroma_tmp,
            query="회의",
            room="e2e_room",
            date="2026-05-26",
        )
        # Should not raise; results is a list (may be empty if chroma returns nothing)
        assert isinstance(results, list)

    def test_search_with_both_filters_no_raise(self, sample_txt, chroma_tmp):
        """Specific regression: using both room= and date= must NOT raise ValueError."""
        from kakao_summary_mcp.indexer.chroma_store import upsert_turns
        from kakao_summary_mcp.indexer.chunker import messages_to_turns
        from kakao_summary_mcp.parser.regex_parser import parse_file
        from kakao_summary_mcp.retriever.search import semantic_query

        msgs = parse_file(sample_txt, room="bugtest")
        turns = messages_to_turns(msgs)
        upsert_turns(chroma_tmp, turns)

        # Must NOT raise ValueError
        results = semantic_query(
            chroma_tmp,
            query="안녕",
            room="bugtest",
            date="2026-05-26",
        )
        assert isinstance(results, list)

    def test_upserted_turns_retrievable_by_ids(self, sample_txt, chroma_tmp):
        """turns_by_ids returns stored turns in time order."""
        from kakao_summary_mcp.indexer.chroma_store import upsert_turns
        from kakao_summary_mcp.indexer.chunker import messages_to_turns
        from kakao_summary_mcp.parser.regex_parser import parse_file
        from kakao_summary_mcp.retriever.search import turns_by_ids

        msgs = parse_file(sample_txt, room="idtest")
        turns = messages_to_turns(msgs)
        upsert_turns(chroma_tmp, turns)

        all_ids = [t.turn_id for t in turns]
        retrieved = turns_by_ids(chroma_tmp, all_ids)

        assert len(retrieved) == len(turns)
        # Must be sorted by ts_epoch
        epochs = [r["metadata"]["ts_epoch"] for r in retrieved]
        assert epochs == sorted(epochs)

    def test_turns_by_ids_empty(self, chroma_tmp):
        """turns_by_ids with empty list returns empty list (no crash)."""
        from kakao_summary_mcp.retriever.search import turns_by_ids

        result = turns_by_ids(chroma_tmp, [])
        assert result == []

    def test_metadata_fields_stored(self, sample_txt, chroma_tmp):
        """Upserted turns must have required metadata fields."""
        from kakao_summary_mcp.indexer.chroma_store import upsert_turns
        from kakao_summary_mcp.indexer.chunker import messages_to_turns
        from kakao_summary_mcp.parser.regex_parser import parse_file
        from kakao_summary_mcp.retriever.search import turns_by_ids

        msgs = parse_file(sample_txt, room="metaroom")
        turns = messages_to_turns(msgs)
        upsert_turns(chroma_tmp, turns)

        ids = [t.turn_id for t in turns]
        retrieved = turns_by_ids(chroma_tmp, ids)
        for r in retrieved:
            meta = r["metadata"]
            assert "room" in meta
            assert "date" in meta
            assert "sender" in meta
            assert "ts_start" in meta
            assert "ts_epoch" in meta
            assert "msg_ids" in meta

    def test_room_metadata_matches(self, sample_txt, chroma_tmp):
        """All stored turns must belong to the correct room."""
        from kakao_summary_mcp.indexer.chroma_store import upsert_turns
        from kakao_summary_mcp.indexer.chunker import messages_to_turns
        from kakao_summary_mcp.parser.regex_parser import parse_file
        from kakao_summary_mcp.retriever.search import turns_by_ids

        msgs = parse_file(sample_txt, room="roomcheck")
        turns = messages_to_turns(msgs)
        upsert_turns(chroma_tmp, turns)

        ids = [t.turn_id for t in turns]
        retrieved = turns_by_ids(chroma_tmp, ids)
        for r in retrieved:
            assert r["metadata"]["room"] == "roomcheck"
