#!/usr/bin/env python3
"""kakao_summary_mcp — MCP server for KakaoTalk OpenChat summarization & search.

Tools:
  - kakao_sync_chats: PC카톡에서 지정 방의 하루치 대화를 추출·파싱·인덱싱하고
                      LLM이 요약·토픽 추출에 쓸 turn 데이터를 반환.
  - kakao_get_messages_by_ids: turn_id 리스트에 해당하는 원문 메시지를 시간순 반환.
                               (LLM이 토픽 추출 결과를 그대로 들고 와서 후속 호출)
  - kakao_search_messages: 자유 자연어 질의로 시맨틱 검색 → 관련 turn 반환.

Transport: stdio (로컬 실행).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from . import common
from .indexer import chroma_store
from .indexer.chunker import messages_to_turns
from .parser.regex_parser import parse_file, write_jsonl
from .retriever.search import save_session, semantic_query, turns_by_ids

mcp = FastMCP("kakao_summary_mcp")

MAX_TURNS_INLINE = 800  # 응답에 직접 포함하는 turn 상한 (초과 시 잘림 경고)


def _log(msg: str) -> None:
    """stdio MCP는 stdout이 프로토콜 채널이므로 stderr로만 로그."""
    print(msg, file=sys.stderr, flush=True)


class SyncChatsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    date: Optional[str] = Field(
        default=None,
        description=(
            "단일 날짜. 'today', 'yesterday'/'어제', 또는 'YYYY-MM-DD'. "
            "range가 주어지면 무시됨. date·range 둘 다 없으면 기본 '전일(어제)'."
        ),
    )
    range: Optional[str] = Field(
        default=None,
        description=(
            "기간 스펙. 'yesterday', 'YYYY-MM-DD~YYYY-MM-DD', '지난 3일', "
            "'last 5 days' 등. 최대 7일이며 초과 시 가장 최근 7일로 클램프된다. "
            "date보다 우선."
        ),
    )
    rooms: Optional[list[str]] = Field(
        default=None,
        description=(
            "대상 오픈채팅방 이름 리스트 (PC카톡 표시명 그대로). "
            "생략 시 mode=always 인 방(enabled)을 사용. 복수 지정 가능."
        ),
        max_length=20,
    )
    method: str = Field(
        default="ocr",
        description=(
            "추출 방식. 'ocr'(기본, 진짜 백그라운드: PrintWindow+스크롤+OCR, 포커스 "
            "안 뺏음, 단 OCR 손실) | 'export'(네이티브 .txt 내보내기, 무손실이나 "
            "포커스 필요). 대상 방의 PC카톡 대화창이 열려 있어야 함(트레이 ❌)."
        ),
    )
    skip_extract: bool = Field(
        default=False,
        description=(
            "PC카톡 UI 자동화를 건너뛰고 이미 추출된 raw .txt를 재사용. "
            "디버깅·재인덱싱 시 true."
        ),
    )


class GetMessagesByIdsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    turn_ids: list[str] = Field(
        ...,
        description=(
            "kakao_sync_chats가 반환한 turn 객체의 turn_id 값들. "
            "예: ['공부방:20260526:t0003','공부방:20260526:t0007']. "
            "토픽에 속한다고 판단한 turn들을 그대로 넘기면 시간순 원문이 돌아옴."
        ),
        min_length=1,
        max_length=500,
    )


class SearchMessagesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(
        ...,
        description="자연어 질의 (예: '전세 사기', '모의고사 일정'). 한국어 가능.",
        min_length=1,
        max_length=500,
    )
    room: Optional[str] = Field(
        default=None,
        description="특정 방으로 검색 범위 한정. 생략 시 모든 인덱싱된 방 검색.",
    )
    date: Optional[str] = Field(
        default=None,
        description="특정 날짜로 한정 (YYYY-MM-DD). 생략 시 모든 날짜.",
    )
    top_k: int = Field(
        default=15,
        description="반환할 turn 개수 (1-50).",
        ge=1, le=50,
    )


def _extract_room(room: str, raw_path, templates_dir, logs_dir) -> None:
    from .extractor.capture import export_current_room_chat

    # 방 열기 + 내보내기는 capture 오케스트레이터가 tier별로 처리.
    # (백그라운드 tier는 포커스를 뺏지 않고, 포그라운드-그랩 tier만 잠깐 앞으로)
    _log(f"[{room}] open room & export chat → {raw_path}")
    export_current_room_chat(room, raw_path, templates_dir, logs_dir)


def _extract_room_ocr(room: str, start_date, end_date):
    """진짜 백그라운드 OCR 추출 → 범위 내 Message 리스트.

    PrintWindow+스크롤+OCR(포커스 미탈취). 대상 방 대화창이 열려 있어야 함.
    """
    from .extractor import ocr_capture as oc

    # 범위 일수에 비례해 스크롤 화면 수 산정(하루≈8화면, 상한 40)
    span_days = (end_date - start_date).days + 1
    max_screens = min(40, max(6, span_days * 8))
    lines = oc.extract_conversation(room, max_screens=max_screens)
    msgs = oc.messages_from_ocr_lines(room, lines, default_date=end_date.isoformat())
    s_iso, e_iso = start_date.isoformat(), end_date.isoformat()
    return [m for m in msgs if s_iso <= m.date <= e_iso]


@mcp.tool(
    name="kakao_sync_chats",
    annotations={
        "title": "Sync KakaoTalk OpenChat (extract → parse → index)",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def kakao_sync_chats(params: SyncChatsInput) -> str:
    """대상 오픈채팅방의 하루치 대화를 PC카톡에서 추출·파싱·인덱싱하고
    LLM이 요약·토픽 추출에 사용할 turn 데이터를 반환합니다.

    동작:
        1. params.rooms (또는 rooms.yaml enabled 방)을 순회.
        2. 각 방에 대해 PC카톡 UI 자동화로 '대화 내용 내보내기' 실행 → .txt 확보.
           (skip_extract=true면 기존 raw 재사용)
        3. .txt를 파싱해 메시지 단위 jsonl 저장.
        4. 연속 발신자 발화를 turn으로 묶고 bge-m3로 임베딩 → ChromaDB upsert.
        5. 그 날 모든 방의 turn 배열을 응답에 포함.

    LLM 사용 패턴:
        - 이 tool 결과의 turns 배열을 보고 화제 단위 토픽 T1, T2, … 라벨링.
        - 각 토픽에 속하는 turn_id들을 모아 사용자에게 요약 출력.
        - 사용자가 "T1 원문" 또는 "전세 관련 대화" 요청 시:
            * 토픽 라벨이면 그 토픽의 turn_ids로 kakao_get_messages_by_ids 호출.
            * 자유 질의면 kakao_search_messages 호출.

    Args:
        params (SyncChatsInput):
            - date (str): 'today' | 'yesterday' | 'YYYY-MM-DD'
            - rooms (list[str] | None): 방 이름 리스트. 생략 시 rooms.yaml.
            - skip_extract (bool): UI 자동화 건너뛰기

    Returns:
        str: JSON 문자열. 스키마:
        {
          "session_id": "sess_YYYYMMDD_HHMMSS",
          "date": "YYYY-MM-DD",
          "rooms_attempted": ["공부방", ...],
          "rooms_succeeded": ["공부방"],
          "rooms_failed": [{"room": "부동산방", "error": "..."}],
          "total_turns": 142,
          "truncated": false,           # MAX_TURNS_INLINE 초과 시 true
          "turns": [
            {
              "turn_id": "공부방:20260526:t0003",
              "room": "공부방",
              "date": "2026-05-26",
              "ts": "09:15",
              "sender": "홍길동",
              "text": "...",
              "msg_ids": ["공부방:20260526:00012", ...]
            }, ...
          ]
        }
        실패 시 동일 스키마에서 rooms_failed에 사유 기록.
        템플릿 이미지 누락·카톡창 미발견은 setup 에러로 rooms_failed.error에 표시.
    """
    cfg = common.load_config()
    paths = common.data_paths(cfg)
    try:
        start_date, end_date, clamped = common.resolve_range(
            params.range or params.date
        )
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    if params.rooms:
        rooms = [r.strip() for r in params.rooms if r.strip()]
    else:
        rooms = common.always_rooms(cfg)
    if not rooms:
        return json.dumps({
            "error": (
                "대상 방이 없습니다. ~/.kakao-summary-mcp/rooms.yaml 에서 "
                "mode=always 로 등록하거나 'rooms' 파라미터로 지정하세요."
            ),
        }, ensure_ascii=False)

    session_id = f"sess_{dt.datetime.now():%Y%m%d_%H%M%S}"
    model_name = cfg.get("embedding", {}).get("model", "BAAI/bge-m3")
    device = cfg.get("embedding", {}).get("device", "cpu")

    succeeded: list[str] = []
    failed: list[dict] = []
    all_turns: list[dict] = []

    range_tag = (
        end_date.isoformat() if start_date == end_date
        else f"{start_date.isoformat()}_{end_date.isoformat()}"
    )
    for room in rooms:
        room_dir = common.safe_room_dir(room)
        # raw 내보내기는 대화 전체이므로 anchor(end_date)로 캐싱.
        raw_path = paths["raw"] / room_dir / f"{end_date.isoformat()}.txt"
        parsed_path = paths["parsed"] / room_dir / f"{range_tag}.jsonl"

        try:
            if params.method == "ocr":
                msgs = _extract_room_ocr(room, start_date, end_date)
            else:
                if not params.skip_extract:
                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    _extract_room(room, raw_path, paths["templates"], paths["logs"])
                elif not raw_path.exists():
                    raise FileNotFoundError(
                        f"skip_extract=true인데 raw 파일이 없습니다: {raw_path}"
                    )
                msgs = parse_file(raw_path, room,
                                  start_date=start_date, end_date=end_date)
            if not msgs:
                _log(f"[{room}] 해당 날짜에 메시지 없음")
                succeeded.append(room)
                continue
            write_jsonl(msgs, parsed_path)
            _log(f"[{room}] {len(msgs)} messages parsed")

            turns = messages_to_turns(msgs)
            n = chroma_store.upsert_turns(
                paths["chroma"], turns, model_name=model_name, device=device,
            )
            _log(f"[{room}] {n} turns indexed")

            for t in turns:
                all_turns.append({
                    "turn_id": t.turn_id,
                    "room": t.room,
                    "date": t.date,
                    "ts": t.ts_start,
                    "sender": t.sender,
                    "text": t.text,
                    "msg_ids": t.msg_ids,
                })
            succeeded.append(room)
        except Exception as e:
            _log(f"[{room}] ERROR: {e}")
            failed.append({"room": room, "error": str(e)})

    all_turns.sort(key=lambda x: (x["room"], x["ts"]))
    total = len(all_turns)
    truncated = total > MAX_TURNS_INLINE
    inline_turns = all_turns[:MAX_TURNS_INLINE]

    session = {
        "session_id": session_id,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "date_start": start_date.isoformat(),
        "date_end": end_date.isoformat(),
        "rooms": succeeded,
        "topics": {},
        "total_turns": total,
    }
    save_session(paths["sessions"] / f"{session_id}.json", session)

    notes = []
    if clamped:
        notes.append(
            f"요청 기간이 7일을 초과해 가장 최근 7일({start_date.isoformat()}"
            f"~{end_date.isoformat()})로 제한했습니다."
        )

    return json.dumps({
        "session_id": session_id,
        "date_start": start_date.isoformat(),
        "date_end": end_date.isoformat(),
        "clamped": clamped,
        "rooms_attempted": rooms,
        "rooms_succeeded": succeeded,
        "rooms_failed": failed,
        "total_turns": total,
        "truncated": truncated,
        "notes": notes,
        "turns": inline_turns,
    }, ensure_ascii=False)


@mcp.tool(
    name="kakao_get_messages_by_ids",
    annotations={
        "title": "Get KakaoTalk messages by turn_ids",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def kakao_get_messages_by_ids(params: GetMessagesByIdsInput) -> str:
    """주어진 turn_id 리스트에 해당하는 원문 turn을 시간순으로 반환합니다.

    사용 시점:
        kakao_sync_chats 결과에서 LLM이 토픽(예: T1)에 속한다고 판단한
        turn_id 리스트를 모았을 때, 그 토픽의 '전문'을 사용자에게 보여주려고 호출.

    Args:
        params.turn_ids (list[str]): kakao_sync_chats 응답의 turn_id 값들.

    Returns:
        str: JSON 문자열. 스키마:
        {
          "count": 12,
          "turns": [
            {
              "turn_id": "...",
              "text": "...",
              "metadata": {
                "room": "공부방", "date": "2026-05-26",
                "sender": "홍길동", "ts_start": "09:15",
                "ts_epoch": 1779754500,
                "msg_ids": "공부방:20260526:00012,..."
              }
            }, ...
          ]
        }
        매칭되지 않은 turn_id는 결과에서 빠짐. 모두 없으면 count=0.
    """
    cfg = common.load_config()
    paths = common.data_paths(cfg)
    turns = turns_by_ids(paths["chroma"], params.turn_ids)
    return json.dumps({"count": len(turns), "turns": turns}, ensure_ascii=False)


@mcp.tool(
    name="kakao_search_messages",
    annotations={
        "title": "Semantic search across indexed KakaoTalk turns",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def kakao_search_messages(params: SearchMessagesInput) -> str:
    """자연어 질의로 인덱싱된 모든 turn에 시맨틱 검색을 실행합니다.

    bge-m3 임베딩 코사인 유사도 기준 top_k 결과를 반환합니다.
    한국어·다국어 모두 가능.

    사용 시점:
        - 사용자가 토픽 라벨이 아니라 "전세 사기 관련 대화 보여줘" 같이
          자유 질의로 원문을 요청할 때.

    Args:
        params.query (str): 자연어 질의 (예: '전세 사기', '모의고사')
        params.room (str|None): 방 필터
        params.date (str|None): 날짜 필터 YYYY-MM-DD
        params.top_k (int): 1-50

    Returns:
        str: JSON. 스키마:
        {
          "query": "...",
          "filters": {"room": "...", "date": "..."},
          "count": 7,
          "turns": [
            {
              "turn_id": "...",
              "text": "...",
              "distance": 0.18,
              "metadata": {...}
            }, ...
          ]
        }
        인덱스가 비어있으면 count=0.
    """
    cfg = common.load_config()
    paths = common.data_paths(cfg)
    model_name = cfg.get("embedding", {}).get("model", "BAAI/bge-m3")
    device = cfg.get("embedding", {}).get("device", "cpu")
    try:
        turns = semantic_query(
            paths["chroma"], params.query,
            room=params.room, date=params.date, top_k=params.top_k,
            model_name=model_name, device=device,
        )
    except Exception as e:
        return json.dumps({
            "error": f"검색 실패: {e}. 먼저 kakao_sync_chats로 인덱싱이 되어 있는지 확인하세요.",
        }, ensure_ascii=False)

    return json.dumps({
        "query": params.query,
        "filters": {"room": params.room, "date": params.date},
        "count": len(turns),
        "turns": turns,
    }, ensure_ascii=False)


class SetupCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRoomsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    rooms: list[str] = Field(
        ...,
        description=(
            "사용자가 모니터링하고 싶은 PC카톡 오픈채팅방 이름 리스트 "
            "(PC카톡 표시명 그대로). 기존 enabled 방에 합쳐짐."
        ),
        min_length=1, max_length=20,
    )
    replace: bool = Field(
        default=False,
        description="true면 기존 enabled 방을 모두 비활성화 후 새 리스트만 등록.",
    )
    modes: Optional[dict[str, str]] = Field(
        default=None,
        description=(
            "방 이름 → 'always'|'optional' 매핑. 'always'면 사용자가 '요약'이라고만 "
            "해도 자동 포함, 'optional'이면 지목할 때만. 생략된 방은 'always' 기본."
        ),
    )
    links: Optional[dict[str, str]] = Field(
        default=None,
        description=(
            "방 이름 → 오픈채팅 링크(예: https://open.kakao.com/o/...) 매핑. "
            "식별·메모용이며 추출에는 사용하지 않음."
        ),
    )


@mcp.tool(
    name="kakao_setup_check",
    annotations={
        "title": "Diagnose kakao-summary-mcp environment",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def kakao_setup_check(params: SetupCheckInput) -> str:
    """현재 환경이 카톡 자동 추출을 할 준비가 되었는지 진단합니다.

    검사 항목:
        - 설정 디렉터리 / rooms.yaml 존재 및 enabled 방
        - PC카톡 실행 여부
        - UIA 백엔드 연결 가능 여부
        - 핵심 Python 의존성

    Returns:
        str: JSON 스키마:
        {
          "ready": bool,                # 모든 핵심 체크 통과 여부
          "app_home": "...",
          "rooms_yaml_exists": bool,
          "enabled_rooms": ["..."],
          "kakao_running": bool,
          "uia_connectable": bool,
          "missing_deps": ["..."],
          "next_steps": ["사용자에게 안내할 다음 단계 문장들"]
        }
    """
    import json as _json

    paths = common.ensure_app_layout()
    cfg_path = common.config_path()
    rooms_yaml_exists = cfg_path.exists()
    enabled = []
    always = []
    optional = []
    if rooms_yaml_exists:
        try:
            cfg = common.load_config()
            enabled = common.enabled_rooms(cfg)
            always = common.always_rooms(cfg)
            optional = [r["name"] for r in common.room_entries(cfg)
                        if r["enabled"] and r["mode"] == "optional"]
        except Exception:
            enabled = []

    kakao_running = False
    kakao_window_minimized = False
    try:
        from pywinauto import findwindows
        handles = findwindows.find_windows(title_re=r"^카카오톡|^KakaoTalk")
        kakao_running = bool(handles)
        if kakao_running:
            try:
                import win32gui  # type: ignore
                kakao_window_minimized = any(
                    win32gui.IsIconic(h) for h in handles
                )
            except Exception:
                kakao_window_minimized = False
    except Exception:
        pass

    uia_ok = False
    if kakao_running:
        try:
            from .extractor.uia_capture import _connect_kakao
            _connect_kakao()
            uia_ok = True
        except Exception:
            uia_ok = False

    missing = []
    for pkg in ("pyautogui", "pyperclip", "yaml", "chromadb",
                "sentence_transformers", "mcp"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    next_steps = []
    if missing:
        next_steps.append(
            f"누락된 의존성 설치: pip install {' '.join(missing)}"
        )
    if not enabled:
        next_steps.append(
            "모니터링할 채팅방 등록 필요 — 사용자에게 PC카톡 표시명을 물어 "
            "kakao_register_rooms 호출."
        )
    if not kakao_running:
        next_steps.append("PC카톡을 실행하고 로그인하세요.")
    elif kakao_window_minimized:
        next_steps.append(
            "준백그라운드 추출은 카톡 창이 열려 있어야 합니다(트레이/최소화 ❌). "
            "카톡 창을 띄워두세요. 다른 창에 가려져 있어도 됩니다."
        )

    ready = (not missing) and bool(enabled) and kakao_running

    return _json.dumps({
        "ready": ready,
        "app_home": str(paths["home"]),
        "rooms_yaml_exists": rooms_yaml_exists,
        "enabled_rooms": enabled,
        "always_rooms": always,
        "optional_rooms": optional,
        "kakao_running": kakao_running,
        "kakao_window_minimized": kakao_window_minimized,
        "uia_connectable": uia_ok,
        "missing_deps": missing,
        "next_steps": next_steps,
    }, ensure_ascii=False)


@mcp.tool(
    name="kakao_register_rooms",
    annotations={
        "title": "Register KakaoTalk rooms to monitor",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def kakao_register_rooms(params: RegisterRoomsInput) -> str:
    """rooms.yaml에 모니터링할 채팅방을 자동 등록합니다.

    첫 사용자가 별도 파일 편집 없이 자연어 대화만으로 셋업을 마칠 수 있게 합니다.
    LLM이 사용자에게 "어떤 방을 볼까요?" 물어 받은 응답을 그대로 넘기면 됩니다.

    Args:
        params.rooms (list[str]): PC카톡 표시명 그대로 방 이름들
        params.replace (bool): true면 기존 enabled 항목을 비활성화 후 새 리스트로
        params.modes (dict|None): 방 이름 → 'always'|'optional'
        params.links (dict|None): 방 이름 → 오픈채팅 링크(식별·메모용)

    Returns:
        str: JSON {"enabled_rooms": [...], "always_rooms": [...],
                   "optional_rooms": [...], "config_path": "..."}
    """
    import json as _json
    import yaml as _yaml

    common.ensure_app_layout()
    cfg_path = common.config_path()
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = _yaml.safe_load(f) or {}

    existing = cfg.get("rooms", []) or []
    by_name = {r["name"]: r for r in existing if isinstance(r, dict) and "name" in r}

    modes = params.modes or {}
    links = params.links or {}

    def _norm_mode(value: str | None, fallback: str = "always") -> str:
        return value if value in common.VALID_MODES else fallback

    if params.replace:
        for r in by_name.values():
            r["enabled"] = False

    for name in params.rooms:
        entry = by_name.get(name, {"name": name})
        entry["enabled"] = True
        # mode: 명시값 우선 → 기존값 유지 → 'always' 기본
        entry["mode"] = _norm_mode(modes.get(name), _norm_mode(entry.get("mode")))
        if name in links:
            entry["link"] = links[name]
        elif "link" not in entry:
            entry["link"] = ""
        by_name[name] = entry

    cfg["rooms"] = list(by_name.values())
    with open(cfg_path, "w", encoding="utf-8") as f:
        _yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)

    enabled = [r["name"] for r in cfg["rooms"] if r.get("enabled")]
    always = common.always_rooms(cfg)
    optional = [r["name"] for r in common.room_entries(cfg)
                if r["enabled"] and r["mode"] == "optional"]
    return _json.dumps({
        "enabled_rooms": enabled,
        "always_rooms": always,
        "optional_rooms": optional,
        "config_path": str(cfg_path),
    }, ensure_ascii=False)


def main() -> None:
    common.ensure_app_layout()
    mcp.run()


if __name__ == "__main__":
    main()
