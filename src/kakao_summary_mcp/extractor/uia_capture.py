"""Tier 2: UIA(Windows UI Automation) 기반 메뉴 자동 클릭.

단축키가 작동하지 않는 환경(카톡 버전 차이, 포커스 이슈)에서 fallback.
pywinauto UIA 백엔드로 ☰ 버튼과 '대화 내보내기' 메뉴를 컨트롤 이름/타입으로 탐색.

PC카톡의 정확한 컨트롤 이름은 버전에 따라 다를 수 있어 다중 후보를 시도하고,
모두 실패하면 UIA 트리를 dump해 사용자에게 진단 정보 제공.
"""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import pyautogui
import pyperclip


# 후보 컨트롤 이름들 (카톡 버전·언어 차이 대응)
MENU_BUTTON_NAMES = ("메뉴", "더보기", "Menu", "More")
EXPORT_MENU_NAMES = (
    "대화 내용 내보내기", "대화 내보내기", "텍스트 파일로 저장",
    "Save chat to text file", "Export chat",
)
SUBMENU_NAMES = ("대화 내용", "Chat history")


def _save_screenshot(logs_dir: Path, tag: str) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = logs_dir / f"uia_{tag}_{ts}.png"
    pyautogui.screenshot(str(out))
    return out


def _connect_kakao():
    try:
        from pywinauto import Desktop, findwindows
    except ImportError as e:
        raise RuntimeError("pywinauto가 필요합니다.") from e
    handles = findwindows.find_windows(title_re=r"^카카오톡|^KakaoTalk")
    if not handles:
        raise RuntimeError("카카오톡 창을 찾을 수 없습니다.")
    for h in handles:
        try:
            w = Desktop(backend="uia").window(handle=h)
            if w.exists():
                return w
        except Exception:
            continue
    raise RuntimeError("카카오톡 창에 UIA로 연결하지 못했습니다.")


def _click_first_match(window, names: tuple[str, ...],
                       control_type: str = "Button") -> bool:
    for name in names:
        try:
            ctrl = window.child_window(title=name, control_type=control_type)
            if ctrl.exists(timeout=1.0):
                ctrl.click_input()
                return True
        except Exception:
            continue
    return False


def _click_descendant(window, names: tuple[str, ...],
                      control_types: tuple[str, ...] = ("MenuItem", "Button")) -> bool:
    """children/descendants 어디에 있든 매칭되면 클릭."""
    for ctype in control_types:
        for name in names:
            try:
                for d in window.descendants(control_type=ctype):
                    try:
                        if d.window_text() == name and d.is_enabled():
                            d.click_input()
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
    return False


def export_via_uia(out_path: Path, logs_dir: Path,
                   save_wait: float = 30.0) -> Path:
    """UIA로 메뉴 탐색 후 대화 내보내기."""
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    window = _connect_kakao()

    # 1) ☰ 버튼 클릭 (이름 매칭 우선, 실패 시 우측 상단 영역 휴리스틱)
    if not _click_first_match(window, MENU_BUTTON_NAMES):
        if not _click_descendant(window, MENU_BUTTON_NAMES, ("Button",)):
            dump = _dump_tree(window, logs_dir, "menu_btn_not_found")
            raise RuntimeError(
                f"☰ 메뉴 버튼을 UIA로 찾지 못했습니다. UIA 트리 dump: {dump}"
            )
    time.sleep(0.4)

    # 2) (선택) 하위 메뉴 '대화 내용' 열기 — 카톡 버전에 따라 있을 수도 없을 수도
    _click_descendant(window, SUBMENU_NAMES, ("MenuItem",))
    time.sleep(0.3)

    # 3) '대화 내보내기' 클릭
    if not _click_descendant(window, EXPORT_MENU_NAMES,
                              ("MenuItem", "Button", "Text")):
        dump = _dump_tree(window, logs_dir, "export_not_found")
        raise RuntimeError(
            f"'대화 내보내기' 메뉴를 찾지 못했습니다. UIA 트리 dump: {dump}"
        )
    time.sleep(1.0)

    # 4) 저장 다이얼로그에 경로 입력
    pyperclip.copy(str(out_path))
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)
    pyautogui.press("enter")
    time.sleep(0.4)
    # 덮어쓰기 확인 다이얼로그
    pyautogui.press("enter")

    # 5) 파일 대기
    deadline = time.time() + save_wait
    while time.time() < deadline:
        if out_path.exists() and out_path.stat().st_size > 0:
            time.sleep(0.4)
            return out_path
        time.sleep(0.3)

    shot = _save_screenshot(logs_dir, "save_timeout")
    raise RuntimeError(f"저장 대기 시간 초과: {out_path}, 스크린샷: {shot}")


def _dump_tree(window, logs_dir: Path, tag: str) -> Path:
    """UIA 트리 텍스트 dump (디버깅용)."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = logs_dir / f"uia_tree_{tag}_{ts}.txt"
    try:
        lines = []
        for d in window.descendants():
            try:
                lines.append(
                    f"{d.control_type():<15} | {d.window_text()!r:<40} | "
                    f"enabled={d.is_enabled()}"
                )
            except Exception:
                continue
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        out.write_text(f"dump failed: {e}", encoding="utf-8")
    return out


def dump_kakao_tree(logs_dir: Path) -> Path:
    """진단용: 현재 카톡 창의 UIA 트리를 dump."""
    window = _connect_kakao()
    return _dump_tree(window, logs_dir, "manual_dump")
