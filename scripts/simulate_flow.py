"""End-to-end simulation of the kakao-summary skill flow (offline).

Mirrors the real skill: register a room (with the example open-chat link),
run sync over a date range, label topics, fetch their originals, and search —
all without touching PC KakaoTalk (skip_extract) and without downloading the
2GB model (fake embedder). Proves the wiring works before the real UI run.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))  # so `tests` package (sample data) imports

try:  # Windows consoles default to cp949; force UTF-8 for Korean + emoji output
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

EXAMPLE_LINK = "https://open.kakao.com/o/EXAMPLE"
ROOM = "공부방"


def run(coro):
    return asyncio.run(coro)


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="kakao_sim_"))
    import os
    os.environ["KAKAO_SUMMARY_MCP_HOME"] = str(home)
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

    import kakao_summary_mcp.common as common
    import kakao_summary_mcp.indexer.chroma_store as cs
    import kakao_summary_mcp.server as server
    from tests.conftest import SAMPLE_TXT, fake_embed

    cs.embed = fake_embed  # no model download
    common.ensure_app_layout()

    def fn(tool):
        return getattr(tool, "fn", tool)

    ok = True

    # 1) Setup check
    setup = json.loads(run(fn(server.kakao_setup_check)(server.SetupCheckInput())))
    print("① setup_check:",
          {k: setup[k] for k in ("rooms_yaml_exists", "always_rooms", "missing_deps")})

    # 2) Register the example room (always) with its open-chat link
    reg = json.loads(run(fn(server.kakao_register_rooms)(server.RegisterRoomsInput(
        rooms=[ROOM], modes={ROOM: "always"}, links={ROOM: EXAMPLE_LINK}, replace=True,
    ))))
    print("② register_rooms:", reg)
    assert reg["always_rooms"] == [ROOM], "always 등록 실패"
    cfg = common.load_config()
    entry = next(r for r in common.room_entries(cfg) if r["name"] == ROOM)
    assert entry["link"] == EXAMPLE_LINK, "링크 저장 실패"

    # 3) Place an exported .txt as if the extractor produced it (skip_extract path).
    #    Anchor file name = end date of the range. Use today=2026-05-27 fixture data.
    end = dt.date(2026, 5, 27)
    raw = home / "data" / "raw" / common.safe_room_dir(ROOM) / f"{end.isoformat()}.txt"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(SAMPLE_TXT, encoding="utf-8-sig")

    # 4) Sync over an explicit 2-day range
    sync = json.loads(run(fn(server.kakao_sync_chats)(server.SyncChatsInput(
        range="2026-05-26~2026-05-27", rooms=[ROOM], skip_extract=True,
    ))))
    print(f"③ sync_chats: {sync['date_start']}~{sync['date_end']} "
          f"clamped={sync['clamped']} turns={sync['total_turns']} "
          f"succeeded={sync['rooms_succeeded']}")
    assert sync["rooms_succeeded"] == [ROOM], f"sync 실패: {sync.get('rooms_failed')}"
    assert sync["total_turns"] > 0
    dates = sorted({t["date"] for t in sync["turns"]})
    assert dates == ["2026-05-26", "2026-05-27"], f"범위 필터 오류: {dates}"

    # 5) Topic → turn_ids (LLM step, here we just take a couple of turns)
    topic_ids = [t["turn_id"] for t in sync["turns"][:3]]
    got = json.loads(run(fn(server.kakao_get_messages_by_ids)(
        server.GetMessagesByIdsInput(turn_ids=topic_ids))))
    print(f"④ get_messages_by_ids: count={got['count']}")
    assert got["count"] == len(topic_ids)
    epochs = [t["metadata"]["ts_epoch"] for t in got["turns"]]
    assert epochs == sorted(epochs), "원문이 시간순이 아님"

    # 6) Free-text semantic search
    sr = json.loads(run(fn(server.kakao_search_messages)(server.SearchMessagesInput(
        query="회의 일정", room=ROOM, date="2026-05-26", top_k=5))))
    print(f"⑤ search_messages: count={sr['count']} (room/date filter applied)")
    assert "error" not in sr, sr.get("error")
    assert isinstance(sr["turns"], list)

    # 7) Clamp behavior (>7 days)
    clamp = json.loads(run(fn(server.kakao_sync_chats)(server.SyncChatsInput(
        range="2026-05-01~2026-05-27", rooms=[ROOM], skip_extract=True))))
    print(f"⑥ clamp test: {clamp['date_start']}~{clamp['date_end']} "
          f"clamped={clamp['clamped']} notes={clamp['notes']}")
    assert clamp["clamped"] is True
    assert clamp["date_start"] == "2026-05-21" and clamp["date_end"] == "2026-05-27"

    print("\n✅ 시뮬레이션 통과 — 등록(링크)→범위 sync→원문→검색→클램프 전 경로 정상")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
