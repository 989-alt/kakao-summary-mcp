"""공통 유틸: 설정 로딩, 경로 헬퍼, 날짜 정규화.

설정 파일과 데이터는 모두 사용자 홈 하위 `~/.kakao-summary-mcp/` 에 둠.
환경변수 `KAKAO_SUMMARY_MCP_HOME` 으로 override 가능.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
from pathlib import Path

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
EXAMPLE_CONFIG = PACKAGE_DIR / "config" / "rooms.example.yaml"


def app_home() -> Path:
    override = os.environ.get("KAKAO_SUMMARY_MCP_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".kakao-summary-mcp"


def config_path() -> Path:
    return app_home() / "rooms.yaml"


def ensure_app_layout() -> dict[str, Path]:
    home = app_home()
    paths = {
        "home": home,
        "raw": home / "data" / "raw",
        "parsed": home / "data" / "parsed",
        "chroma": home / "data" / "chroma",
        "sessions": home / "data" / "sessions",
        "templates": home / "templates",
        "logs": home / "logs",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    cfg_path = config_path()
    if not cfg_path.exists():
        shutil.copy(EXAMPLE_CONFIG, cfg_path)
    return paths


def load_config() -> dict:
    paths = ensure_app_layout()
    with open(config_path(), "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg["_paths"] = paths
    return cfg


def data_paths(cfg: dict) -> dict[str, Path]:
    return cfg["_paths"]


def resolve_date(s: str | None) -> dt.date:
    if not s or s in ("today", "오늘"):
        return dt.date.today()
    if s in ("yesterday", "어제"):
        return dt.date.today() - dt.timedelta(days=1)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    raise ValueError(f"날짜를 해석할 수 없습니다: {s!r}")


MAX_RANGE_DAYS = 7

_RANGE_SEP_RE = re.compile(r"\s*(?:~|–|—|\.\.\.?|\bto\b)\s*")
_LAST_N_RE = re.compile(r"^(?:지난|최근|last)\s*(\d+)\s*(?:일|days?)?$", re.IGNORECASE)


def resolve_range(
    spec: str | tuple[str | None, str | None] | None,
    *,
    today: dt.date | None = None,
    max_days: int = MAX_RANGE_DAYS,
) -> tuple[dt.date, dt.date, bool]:
    """범위 스펙을 (start, end, clamped)로 정규화.

    - None/""/"yesterday"/"어제" → 전일(어제) 단일.
    - "today"/"오늘" → 오늘 단일.
    - "YYYY-MM-DD" → 단일일.
    - "YYYY-MM-DD~YYYY-MM-DD" (또는 ..,–,—,to 구분) → 범위.
    - "지난 N일"/"최근 N일"/"last N days" → (오늘-(N-1), 오늘).
    - (start, end) 튜플 → 각 항목을 resolve_date로 해석(None은 today=어제 규칙 미적용,
      start None이면 end와 동일, end None이면 start와 동일).

    start>end면 swap. 일수가 max_days 초과면 end 기준 최근 max_days로 클램프하고
    clamped=True 반환.
    """
    base = today or dt.date.today()
    yesterday = base - dt.timedelta(days=1)

    if isinstance(spec, tuple):
        s_raw, e_raw = spec
        if s_raw is None and e_raw is None:
            start = end = yesterday
        else:
            start = resolve_date(s_raw) if s_raw else None
            end = resolve_date(e_raw) if e_raw else None
            if start is None:
                start = end
            if end is None:
                end = start
    elif spec is None or (isinstance(spec, str) and not spec.strip()):
        start = end = yesterday
    else:
        text = spec.strip()
        mlast = _LAST_N_RE.match(text)
        if text in ("yesterday", "어제"):
            start = end = yesterday
        elif text in ("today", "오늘"):
            start = end = base
        elif mlast:
            n = max(1, int(mlast.group(1)))
            end = base
            start = base - dt.timedelta(days=n - 1)
        else:
            parts = _RANGE_SEP_RE.split(text, maxsplit=1)
            if len(parts) == 2:
                start = resolve_date(parts[0])
                end = resolve_date(parts[1])
            else:
                start = end = resolve_date(text)

    if start > end:
        start, end = end, start

    clamped = False
    span = (end - start).days + 1
    if span > max_days:
        start = end - dt.timedelta(days=max_days - 1)
        clamped = True

    return start, end, clamped


VALID_MODES = ("always", "optional")


def room_entries(cfg: dict) -> list[dict]:
    """rooms.yaml 항목을 정규화된 dict 리스트로.

    각 dict: {name, mode(always|optional), link(str), enabled(bool)}.
    mode 누락·비정상 값은 'always'로 간주(하위호환).
    """
    out: list[dict] = []
    for r in cfg.get("rooms", []) or []:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        mode = r.get("mode")
        if mode not in VALID_MODES:
            mode = "always"
        out.append({
            "name": r["name"],
            "mode": mode,
            "link": r.get("link", "") or "",
            "enabled": bool(r.get("enabled")),
        })
    return out


def enabled_rooms(cfg: dict, override: list[str] | None = None) -> list[str]:
    if override:
        return [r.strip() for r in override if r.strip()]
    return [r["name"] for r in room_entries(cfg) if r["enabled"]]


def always_rooms(cfg: dict) -> list[str]:
    """enabled 且 mode==always 인 방 이름. "요약"이라고만 했을 때의 기본 대상."""
    return [r["name"] for r in room_entries(cfg)
            if r["enabled"] and r["mode"] == "always"]


def room_link_map(cfg: dict) -> dict[str, str]:
    """방 이름 → 오픈채팅 링크. 링크가 비어있지 않은 방만."""
    return {r["name"]: r["link"] for r in room_entries(cfg) if r["link"]}


def open_key_for(room: str, link_map: dict[str, str]) -> str:
    """카톡 통합검색(Ctrl+F)에 붙여넣어 방을 열 '키'를 고른다.

    실측: 오픈채팅 '링크'를 검색에 넣으면 그 방이 정확히 열리지만, '방 이름'은
    동명/부분일치로 진입 실패가 잦다. → 링크가 있으면 링크를 1순위로 쓴다.
    - room 자체가 URL이면 그대로(사용자가 링크를 직접 지정).
    - 아니면 등록된 링크가 있으면 링크, 없으면 이름.
    """
    if room.startswith("http://") or room.startswith("https://"):
        return room
    return link_map.get(room) or room


def safe_room_dir(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()
