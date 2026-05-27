"""PC카톡 채팅 .txt 추출 orchestrator (준백그라운드 하이브리드).

Tier 1: UIA invoke (백그라운드) — 포커스/마우스/픽셀 불필요. 카톡 대화창이
        가려져 있어도 열려만 있으면 동작. 트레이 최소화 시엔 실패.
Tier 2: 포그라운드-그랩 폴백 — 현재 포커스 창을 기억 → 카톡을 앞으로 →
        Ctrl+S(단축키)/click_input UIA로 추출 → 끝나면 이전 창으로 포커스 복귀.
Tier 3: 사용자 템플릿 이미지(`menu_btn.png`, `export_menu.png`) — 화면이 보일 때만.

각 tier는 방 열기 + 내보내기를 한 묶음으로 시도한다. 실패 시 다음 tier로 전이.
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

import pyautogui
import pyperclip

from .shortcut_capture import export_via_shortcut
from .uia_capture import (
    export_via_uia,
    export_via_uia_background,
    open_room_via_uia,
)

pyautogui.FAILSAFE = True


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _save_screenshot(logs_dir: Path, tag: str) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = logs_dir / f"template_{tag}_{ts}.png"
    pyautogui.screenshot(str(out))
    return out


def _click_template(template: Path, logs_dir: Path,
                    confidence: float = 0.85, timeout: float = 6.0,
                    tag: str = "template") -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            loc = pyautogui.locateCenterOnScreen(str(template), confidence=confidence)
        except Exception:
            loc = None
        if loc is not None:
            pyautogui.click(loc.x, loc.y)
            return
        time.sleep(0.3)
    shot = _save_screenshot(logs_dir, tag)
    raise RuntimeError(
        f"화면에서 '{template.name}'를 찾지 못했습니다 (conf>={confidence}). "
        f"실패 스크린샷: {shot}"
    )


def _export_via_template(out_path: Path, templates_dir: Path,
                         logs_dir: Path, save_wait: float = 30.0) -> Path:
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    menu_btn = templates_dir / "menu_btn.png"
    export_menu = templates_dir / "export_menu.png"
    for t in (menu_btn, export_menu):
        if not t.exists():
            raise RuntimeError(
                f"템플릿 이미지가 없습니다: {t}. "
                "Tier 3(템플릿) 사용 시 두 PNG 파일이 필요합니다."
            )

    _click_template(menu_btn, logs_dir, tag="menu_btn")
    time.sleep(0.5)
    _click_template(export_menu, logs_dir, tag="export_menu")
    time.sleep(1.2)

    pyperclip.copy(str(out_path))
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)
    pyautogui.press("enter")

    deadline = time.time() + save_wait
    while time.time() < deadline:
        if out_path.exists() and out_path.stat().st_size > 0:
            time.sleep(0.5)
            return out_path
        time.sleep(0.4)
    shot = _save_screenshot(logs_dir, "save_timeout")
    raise RuntimeError(f"저장 대기 시간 초과: {out_path}, 스크린샷: {shot}")


# ---------------------------------------------------------------------------
# Tier implementations (방 열기 + 내보내기 한 묶음)
# ---------------------------------------------------------------------------

def _tier_background(room: str, out_path: Path, logs_dir: Path,
                     save_wait: float) -> Path:
    """Tier 1: UIA invoke만으로 방 열고 내보내기 (포커스 안 뺏음)."""
    open_room_via_uia(room)  # best-effort; 이미 열려 있으면 무해
    time.sleep(0.5)
    return export_via_uia_background(out_path, logs_dir, save_wait=save_wait)


def _tier_foreground_grab(room: str, out_path: Path, logs_dir: Path,
                          save_wait: float) -> Path:
    """Tier 2: 포커스를 잠깐 카톡으로 가져와 추출하고 원래 창으로 복귀."""
    from .window import (
        focus_main_window,
        remember_foreground,
        restore_foreground,
        search_and_open_room,
    )

    prev = remember_foreground()
    try:
        focus_main_window()
        time.sleep(0.3)
        search_and_open_room(room)
        time.sleep(0.8)
        try:
            return export_via_shortcut(out_path, logs_dir, save_wait=save_wait)
        except Exception as e1:
            _log(f"[capture] 포그라운드 단축키 실패, click_input UIA 시도: {e1}")
            return export_via_uia(out_path, logs_dir, save_wait=save_wait)
    finally:
        restore_foreground(prev)


def _tier_template(room: str, out_path: Path, logs_dir: Path,
                   save_wait: float, templates_dir: Path) -> Path:
    """Tier 3: 화면 템플릿 매칭(최후 수단)."""
    return _export_via_template(out_path, templates_dir, logs_dir,
                                save_wait=save_wait)


def export_current_room_chat(room: str, out_path: Path, templates_dir: Path,
                             logs_dir: Path, save_wait: float = 30.0,
                             *, tiers=None) -> Path:
    """하이브리드 3단계로 방을 열고 .txt를 추출.

    Args:
        room: PC카톡 표시 방 이름
        tiers: 테스트용 주입. [(label, callable_returning_path), ...].
               생략 시 기본(백그라운드→포그라운드-그랩→템플릿).

    Returns: 저장된 .txt 경로
    Raises: RuntimeError (모든 tier 실패 시, 각 tier 오류 메시지 합쳐서)
    """
    if tiers is None:
        tiers = [
            ("UIA(백그라운드)",
             lambda: _tier_background(room, out_path, logs_dir, save_wait)),
            ("포그라운드-그랩",
             lambda: _tier_foreground_grab(room, out_path, logs_dir, save_wait)),
            ("템플릿",
             lambda: _tier_template(room, out_path, logs_dir, save_wait,
                                    templates_dir)),
        ]

    errors: list[str] = []
    for label, fn in tiers:
        try:
            _log(f"[capture] Tier '{label}' 시도")
            path = fn()
            _log(f"[capture] Tier '{label}' 성공")
            return path
        except Exception as e:
            _log(f"[capture] Tier '{label}' 실패: {e}")
            errors.append(f"{label}: {e}")

    raise RuntimeError(
        "모든 추출 방법 실패. 단계별 사유:\n  - " + "\n  - ".join(errors)
        + f"\n로그 디렉터리({logs_dir})의 스크린샷을 확인하세요."
    )
