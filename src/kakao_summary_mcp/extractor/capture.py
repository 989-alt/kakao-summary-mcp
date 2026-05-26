"""PC카톡 채팅 .txt 추출 orchestrator (3-tier fallback).

Tier 1: 키보드 단축키 `Ctrl+S` (가장 가벼움, 사용자 셋업 0개)
Tier 2: UIA(Windows UI Automation)로 ☰ 메뉴 자동 탐색
Tier 3: 사용자가 직접 캡처한 템플릿 이미지(`menu_btn.png`, `export_menu.png`)

각 tier는 실패 시 다음으로 자동 전이. 어떤 tier로 성공했는지 stderr에 기록.
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

import pyautogui
import pyperclip

from .shortcut_capture import export_via_shortcut
from .uia_capture import export_via_uia

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


def export_current_room_chat(out_path: Path, templates_dir: Path,
                             logs_dir: Path, save_wait: float = 30.0) -> Path:
    """3-tier fallback으로 현재 채팅방 .txt 추출.

    Returns: 저장된 .txt 경로
    Raises: RuntimeError (모든 tier 실패 시, 각 tier 오류 메시지 합쳐서)
    """
    errors: list[str] = []

    # Tier 1: 단축키
    try:
        _log("[capture] Tier 1: Ctrl+S 단축키 시도")
        path = export_via_shortcut(out_path, logs_dir, save_wait=save_wait)
        _log("[capture] Tier 1 성공")
        return path
    except Exception as e:
        _log(f"[capture] Tier 1 실패: {e}")
        errors.append(f"단축키: {e}")

    # Tier 2: UIA
    try:
        _log("[capture] Tier 2: UIA 메뉴 탐색 시도")
        path = export_via_uia(out_path, logs_dir, save_wait=save_wait)
        _log("[capture] Tier 2 성공")
        return path
    except Exception as e:
        _log(f"[capture] Tier 2 실패: {e}")
        errors.append(f"UIA: {e}")

    # Tier 3: 사용자 템플릿
    try:
        _log("[capture] Tier 3: 사용자 템플릿 이미지 시도")
        path = _export_via_template(out_path, templates_dir, logs_dir,
                                     save_wait=save_wait)
        _log("[capture] Tier 3 성공")
        return path
    except Exception as e:
        _log(f"[capture] Tier 3 실패: {e}")
        errors.append(f"템플릿: {e}")

    raise RuntimeError(
        "모든 추출 방법 실패. 단계별 사유:\n  - " + "\n  - ".join(errors)
        + f"\n로그 디렉터리({logs_dir})의 스크린샷을 확인하세요."
    )
