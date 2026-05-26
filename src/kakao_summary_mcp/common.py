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


def enabled_rooms(cfg: dict, override: list[str] | None = None) -> list[str]:
    if override:
        return [r.strip() for r in override if r.strip()]
    return [r["name"] for r in cfg.get("rooms", []) if r.get("enabled")]


def safe_room_dir(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()
