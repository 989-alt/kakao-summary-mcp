"""Tier 1: PC카톡 `Ctrl+S` 단축키로 채팅 .txt 추출.

채팅창이 활성화된 상태에서 Ctrl+S → 저장 다이얼로그 → 경로 자동 입력 → Enter.
다수 사용자 가이드에 따르면 PC카톡은 채팅 화면에서 Ctrl+S를 누르면 즉시
'대화 내용 텍스트 파일로 저장' 다이얼로그가 뜬다.
참고: https://cs.kakao.com/helps_html/1073182634
"""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import pyautogui
import pyperclip

pyautogui.FAILSAFE = True


def _save_screenshot(logs_dir: Path, tag: str) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = logs_dir / f"shortcut_{tag}_{ts}.png"
    pyautogui.screenshot(str(out))
    return out


def _wait_save_dialog(timeout: float = 4.0):
    """저장 다이얼로그 등장 대기. 발견 시 dialog 컨트롤 반환, 실패 시 None."""
    try:
        from pywinauto import Desktop
    except ImportError:
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            dlg = Desktop(backend="uia").window(title_re=r"다른 이름으로 저장|Save As|저장")
            if dlg.exists():
                return dlg
        except Exception:
            pass
        time.sleep(0.2)
    return None


def export_via_shortcut(out_path: Path, logs_dir: Path,
                        save_wait: float = 30.0) -> Path:
    """현재 활성화된 PC카톡 채팅창에서 Ctrl+S로 대화 내보내기.

    Returns: 저장된 .txt 절대 경로
    Raises: RuntimeError (단축키가 다이얼로그를 띄우지 않거나 저장 실패 시)
    """
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    # 1) 채팅 영역에 포커스가 가도록 ESC로 떠 있는 팝업 닫기
    pyautogui.press("escape")
    time.sleep(0.2)

    # 2) Ctrl+S
    pyautogui.hotkey("ctrl", "s")
    time.sleep(0.4)

    # 3) 저장 다이얼로그 등장 확인
    dlg = _wait_save_dialog(timeout=4.0)
    if dlg is None:
        shot = _save_screenshot(logs_dir, "no_dialog")
        raise RuntimeError(
            "Ctrl+S 후 저장 다이얼로그가 뜨지 않았습니다. "
            "채팅창이 활성화되어 있는지 확인하거나 UIA fallback이 필요합니다. "
            f"진단 스크린샷: {shot}"
        )

    # 4) 경로 입력 (다이얼로그의 파일명 필드에 전체 경로 붙여넣기)
    pyperclip.copy(str(out_path))
    time.sleep(0.15)
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.25)
    pyautogui.press("enter")

    # 5) '이미 있는 파일' 경고가 뜨면 덮어쓰기 (위에서 unlink 했지만 보호용)
    time.sleep(0.4)
    try:
        from pywinauto import Desktop
        overwrite = Desktop(backend="uia").window(
            title_re=r"다른 이름으로 저장|Confirm Save As"
        )
        if overwrite.exists():
            pyautogui.press("enter")
    except Exception:
        pass

    # 6) 파일 생성 대기
    deadline = time.time() + save_wait
    while time.time() < deadline:
        if out_path.exists() and out_path.stat().st_size > 0:
            time.sleep(0.4)
            return out_path
        time.sleep(0.3)

    shot = _save_screenshot(logs_dir, "save_timeout")
    raise RuntimeError(
        f"저장 파일 대기 시간 초과({save_wait}s): {out_path}\n진단 스크린샷: {shot}"
    )
