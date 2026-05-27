"""Server-tool tests: room registration (mode/link) and sync range wiring.

Runs fully offline:
  - app home is redirected to a tmp dir via KAKAO_SUMMARY_MCP_HOME
  - the embedder is stubbed (no 2GB model download)
  - extraction is skipped (skip_extract=True) with a pre-placed sample .txt
"""
from __future__ import annotations

import asyncio
import json

import pytest

import kakao_summary_mcp.common as common
import kakao_summary_mcp.server as server
from tests.conftest import SAMPLE_TXT, fake_embed


def _call(coro):
    return asyncio.run(coro)


def _maybe_fn(tool):
    """FastMCP may wrap the tool; fall back to the underlying .fn if needed."""
    return getattr(tool, "fn", tool)


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("KAKAO_SUMMARY_MCP_HOME", str(tmp_path / "home"))
    common.ensure_app_layout()
    return tmp_path / "home"


@pytest.fixture(autouse=True)
def stub_embedder(monkeypatch):
    import kakao_summary_mcp.indexer.chroma_store as cs
    monkeypatch.setattr(cs, "embed", fake_embed)


# ---------------------------------------------------------------------------
# register_rooms: mode + link
# ---------------------------------------------------------------------------

class TestRegisterRooms:
    def test_registers_with_mode_and_link(self):
        fn = _maybe_fn(server.kakao_register_rooms)
        out = json.loads(_call(fn(server.RegisterRoomsInput(
            rooms=["공부방", "부동산방"],
            modes={"공부방": "always", "부동산방": "optional"},
            links={"공부방": "https://open.kakao.com/o/EXAMPLE"},
            replace=True,
        ))))
        assert out["always_rooms"] == ["공부방"]
        assert out["optional_rooms"] == ["부동산방"]
        assert set(out["enabled_rooms"]) == {"공부방", "부동산방"}

    def test_link_persisted_in_yaml(self):
        fn = _maybe_fn(server.kakao_register_rooms)
        _call(fn(server.RegisterRoomsInput(
            rooms=["공부방"],
            links={"공부방": "https://open.kakao.com/o/EXAMPLE"},
        )))
        cfg = common.load_config()
        entry = next(r for r in common.room_entries(cfg) if r["name"] == "공부방")
        assert entry["link"] == "https://open.kakao.com/o/EXAMPLE"
        assert entry["mode"] == "always"  # default

    def test_default_mode_is_always(self):
        fn = _maybe_fn(server.kakao_register_rooms)
        out = json.loads(_call(fn(server.RegisterRoomsInput(
            rooms=["방없음모드"], replace=True,
        ))))
        assert out["always_rooms"] == ["방없음모드"]

    def test_mode_update_preserved_when_not_respecified(self):
        fn = _maybe_fn(server.kakao_register_rooms)
        # First set optional
        _call(fn(server.RegisterRoomsInput(
            rooms=["방X"], modes={"방X": "optional"}, replace=True,
        )))
        # Re-register without modes — should keep optional
        out = json.loads(_call(fn(server.RegisterRoomsInput(rooms=["방X"]))))
        assert out["optional_rooms"] == ["방X"]
        assert out["always_rooms"] == []


# ---------------------------------------------------------------------------
# sync_chats: range wiring + skip_extract simulation
# ---------------------------------------------------------------------------

def _place_sample(home, room: str, end_iso: str):
    room_dir = common.safe_room_dir(room)
    raw = home / "data" / "raw" / room_dir / f"{end_iso}.txt"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(SAMPLE_TXT, encoding="utf-8-sig")
    return raw


class TestSyncChatsRange:
    def test_range_two_days_returns_all_turns(self, tmp_home):
        room = "공부방"
        _place_sample(tmp_home, room, "2026-05-27")
        fn = _maybe_fn(server.kakao_sync_chats)
        out = json.loads(_call(fn(server.SyncChatsInput(
            range="2026-05-26~2026-05-27", rooms=[room], skip_extract=True,
        ))))
        assert out["date_start"] == "2026-05-26"
        assert out["date_end"] == "2026-05-27"
        assert out["clamped"] is False
        assert room in out["rooms_succeeded"]
        dates = {t["date"] for t in out["turns"]}
        assert dates == {"2026-05-26", "2026-05-27"}
        assert out["total_turns"] > 0

    def test_single_day_filters(self, tmp_home):
        room = "공부방"
        _place_sample(tmp_home, room, "2026-05-27")
        fn = _maybe_fn(server.kakao_sync_chats)
        out = json.loads(_call(fn(server.SyncChatsInput(
            date="2026-05-27", rooms=[room], skip_extract=True,
        ))))
        assert out["date_start"] == out["date_end"] == "2026-05-27"
        assert {t["date"] for t in out["turns"]} == {"2026-05-27"}

    def test_over_seven_days_clamped(self, tmp_home):
        room = "공부방"
        _place_sample(tmp_home, room, "2026-05-27")
        fn = _maybe_fn(server.kakao_sync_chats)
        out = json.loads(_call(fn(server.SyncChatsInput(
            range="2026-05-01~2026-05-27", rooms=[room], skip_extract=True,
        ))))
        assert out["clamped"] is True
        assert out["date_end"] == "2026-05-27"
        assert out["date_start"] == "2026-05-21"  # most-recent 7 days
        assert out["notes"]  # user-facing note present

    def test_default_uses_always_rooms(self, tmp_home):
        # Register one always + one optional; default sync should target only always.
        reg = _maybe_fn(server.kakao_register_rooms)
        _call(reg(server.RegisterRoomsInput(
            rooms=["공부방", "부동산방"],
            modes={"공부방": "always", "부동산방": "optional"},
            replace=True,
        )))
        _place_sample(tmp_home, "공부방", "2026-05-27")
        fn = _maybe_fn(server.kakao_sync_chats)
        out = json.loads(_call(fn(server.SyncChatsInput(
            range="2026-05-26~2026-05-27", skip_extract=True,
        ))))
        assert out["rooms_attempted"] == ["공부방"]  # optional excluded

    def test_skip_extract_missing_raw_is_reported(self, tmp_home):
        fn = _maybe_fn(server.kakao_sync_chats)
        out = json.loads(_call(fn(server.SyncChatsInput(
            range="2026-05-27", rooms=["없는방"], skip_extract=True,
        ))))
        assert out["rooms_failed"]
        assert "없는방" == out["rooms_failed"][0]["room"]

    def test_no_target_rooms_errors(self, tmp_home):
        # Replace registry with only an optional room, then default sync → no always.
        reg = _maybe_fn(server.kakao_register_rooms)
        _call(reg(server.RegisterRoomsInput(
            rooms=["옵션방"], modes={"옵션방": "optional"}, replace=True,
        )))
        fn = _maybe_fn(server.kakao_sync_chats)
        out = json.loads(_call(fn(server.SyncChatsInput(skip_extract=True))))
        assert "error" in out
