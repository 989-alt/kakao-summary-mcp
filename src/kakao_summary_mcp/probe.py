"""kakao-summary-mcp-probe — PC카톡 자동화 진단 CLI.

사용 시점:
  - 첫 셋업 후 자동 추출이 안 될 때 어떤 단계가 문제인지 파악
  - UIA로 카톡 컨트롤이 노출되는지 확인
  - 환경(카톡 실행 여부, 창 식별) 검사

사용법:
  kakao-summary-mcp-probe              # 빠른 진단
  kakao-summary-mcp-probe --dump-uia   # UIA 트리 전체 dump
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import common


def cmd_check() -> int:
    print("=" * 60)
    print("kakao-summary-mcp 진단")
    print("=" * 60)

    # 1) 앱 디렉터리
    paths = common.ensure_app_layout()
    print(f"\n[1] 설정·데이터 디렉터리: {paths['home']}")
    cfg_path = common.config_path()
    print(f"    rooms.yaml: {'있음' if cfg_path.exists() else '없음'}")
    if cfg_path.exists():
        cfg = common.load_config()
        rooms = common.enabled_rooms(cfg)
        print(f"    enabled 방: {rooms if rooms else '(없음 — rooms.yaml 편집 필요)'}")

    # 2) 카톡 창
    print("\n[2] 카카오톡 창 탐지")
    try:
        from pywinauto import findwindows
        handles = findwindows.find_windows(title_re=r"^카카오톡|^KakaoTalk")
        if handles:
            print(f"    창 {len(handles)}개 발견: {handles}")
        else:
            print("    카카오톡 창 없음. PC카톡을 실행하고 로그인하세요.")
            return 1
    except ImportError:
        print("    pywinauto 미설치. `pip install pywinauto` 필요.")
        return 1
    except Exception as e:
        print(f"    탐지 실패: {e}")
        return 1

    # 3) UIA 연결
    print("\n[3] UIA 백엔드 연결")
    try:
        from .extractor.uia_capture import _connect_kakao
        win = _connect_kakao()
        rect = win.rectangle()
        print(f"    OK — {rect.width()}x{rect.height()}")
    except Exception as e:
        print(f"    실패: {e}")
        return 1

    # 4) 의존성
    print("\n[4] 핵심 의존성")
    for pkg in ("pyautogui", "pyperclip", "yaml", "chromadb",
                "sentence_transformers", "mcp"):
        try:
            __import__(pkg)
            print(f"    {pkg}: OK")
        except ImportError:
            print(f"    {pkg}: 미설치")

    print("\n" + "=" * 60)
    print("모든 검사 통과. 'kakao_sync_chats' 호출 준비 완료.")
    return 0


def cmd_dump_uia(out_dir: Path | None) -> int:
    from .extractor.uia_capture import dump_kakao_tree
    paths = common.ensure_app_layout()
    target = out_dir or paths["logs"]
    try:
        path = dump_kakao_tree(target)
        print(f"UIA 트리 dump 저장됨: {path}")
        return 0
    except Exception as e:
        print(f"실패: {e}", file=sys.stderr)
        return 1


def main() -> None:
    ap = argparse.ArgumentParser(prog="kakao-summary-mcp-probe")
    ap.add_argument("--dump-uia", action="store_true",
                    help="현재 카카오톡 창의 UIA 트리를 텍스트로 dump")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="dump 저장 디렉터리 (기본: logs/)")
    args = ap.parse_args()

    if args.dump_uia:
        sys.exit(cmd_dump_uia(args.out_dir))
    else:
        sys.exit(cmd_check())


if __name__ == "__main__":
    main()
