"""PC카카오톡 메인 창 활성화 및 채팅방 진입 (Windows 전용)."""
from __future__ import annotations

import time

import pyautogui
import pyperclip

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15

KAKAO_TITLE_RE = r"^카카오톡|^KakaoTalk"


def _import_pywinauto():
    try:
        from pywinauto import Application, findwindows  # noqa: F401
        return Application, findwindows
    except ImportError as e:
        raise RuntimeError("pywinauto가 필요합니다 (Windows 전용). pip install pywinauto") from e


def find_main_window():
    Application, findwindows = _import_pywinauto()
    handles = findwindows.find_windows(title_re=KAKAO_TITLE_RE)
    if not handles:
        raise RuntimeError("카카오톡 메인 창을 찾을 수 없습니다. PC카톡을 실행하세요.")
    for h in handles:
        try:
            app = Application(backend="uia").connect(handle=h)
            w = app.window(handle=h)
            rect = w.rectangle()
            if rect.width() < 200 or rect.height() < 300:
                continue
            return w
        except Exception:
            continue
    raise RuntimeError("카카오톡 메인 창을 식별하지 못했습니다.")


def focus_main_window() -> None:
    w = find_main_window()
    if w.is_minimized():
        w.restore()
    w.set_focus()
    time.sleep(0.4)


def remember_foreground() -> int | None:
    """현재 포그라운드 창 HWND를 기억(포그라운드-그랩 전에 호출)."""
    try:
        import win32gui  # type: ignore
        return win32gui.GetForegroundWindow()
    except Exception:
        return None


def restore_foreground(hwnd: int | None) -> None:
    """remember_foreground()로 저장한 창으로 포커스 복귀."""
    if not hwnd:
        return
    try:
        import win32gui  # type: ignore
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass


def search_and_open_room(room_name: str) -> None:
    """Ctrl+F로 통합 검색 열고 방 이름 입력 후 Enter."""
    focus_main_window()
    pyautogui.hotkey("ctrl", "f")
    time.sleep(0.6)
    pyperclip.copy(room_name)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.6)
    pyautogui.press("enter")
    time.sleep(1.0)
