"""True-background extraction via PrintWindow + posted scroll + OCR.

PC카톡(EVA 프레임워크)은 UIA 트리가 없고 포그라운드 강제 전환도 OS가 막는다.
하지만 다음 셋은 **포커스를 뺏지 않고**(가려진 창에서도) 동작함이 실측됨:

1. `PrintWindow(hwnd, PW_RENDERFULLCONTENT=2)` — 가려진 창 픽셀 캡처.
2. `PostMessage(list_hwnd, WM_MOUSEWHEEL, ...)` — 포커스 없이 대화 스크롤.
3. 업스케일 + 전처리 후 OCR — 요약 가능한 한국어 텍스트 확보.

이 모듈은 위 셋을 묶어, 대화창을 백그라운드로 스크롤하며 화면을 캡처·OCR하고
줄 단위로 중복 제거(stitch)해 하루치 텍스트를 만든다.

Win32/OCR 의존부는 함수로 격리하고, 순수 로직(stitch/날짜 파싱/줄 정리)은
인자만으로 동작해 단위테스트가 가능하다.
"""
from __future__ import annotations

import difflib
import re
import sys
import time
from dataclasses import dataclass, field

CHAT_WINDOW_CLASS = "EVA_Window_Dblclk"
LIST_CONTROL_CLASS = "EVA_VH_ListControl_Dblclk"
PW_RENDERFULLCONTENT = 2
WM_MOUSEWHEEL = 0x020A

DATE_SEP_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")
# OCR 잡음/UI 라벨로 흔히 잡히는 줄 (메시지 아님)
_NOISE_LINES = (
    "메시지 입력", "시지 입력", "전송", "전손", "Q 0 > =",
)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# 순수 로직 (단위테스트 대상) — Win32/OCR 미사용
# ---------------------------------------------------------------------------

def clean_lines(lines: list[str]) -> list[str]:
    """OCR 줄 목록에서 공백·UI 잡음 줄 제거, strip."""
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if any(noise in s for noise in _NOISE_LINES):
            continue
        out.append(s)
    return out


def _line_eq(a: str, b: str, fuzzy: float) -> bool:
    """fuzzy<=0이면 정확 일치, 아니면 유사도 비교.

    규칙:
    - 짧은 줄(<=3)은 정확 일치만.
    - 숫자는 유의미: 두 줄의 숫자 시퀀스가 다르면(예: 타임스탬프 11:05 vs 11:16)
      유사해도 다른 줄로 본다. → 시간·인원수 등 구분 보존.
    """
    if a == b:
        return True
    if fuzzy <= 0 or min(len(a), len(b)) <= 3:
        return False
    if re.sub(r"\D", "", a) != re.sub(r"\D", "", b):
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= fuzzy


def merge_overlapping(upper: list[str], lower: list[str],
                      min_overlap: int = 1, fuzzy: float = 0.0) -> list[str]:
    """위쪽(older) 화면 줄과 아래쪽(newer) 화면 줄을, 겹치는 구간을 한 번만 남기고 결합.

    upper의 접미부와 lower의 접두부가 가장 길게 (정확/유사) 일치하는 지점을 찾아 잇는다.
    OCR은 캡처마다 글자가 미세하게 달라지므로 fuzzy>0이면 유사도로 겹침을 판정한다.
    """
    if not upper:
        return list(lower)
    if not lower:
        return list(upper)
    max_k = min(len(upper), len(lower))
    best = 0
    for k in range(max_k, min_overlap - 1, -1):
        if all(_line_eq(upper[-k + i], lower[i], fuzzy) for i in range(k)):
            best = k
            break
    return list(upper) + list(lower[best:])


def dedupe_consecutive(lines: list[str], fuzzy: float = 0.85) -> list[str]:
    """인접한 (거의) 동일 줄을 한 번만 남김. OCR 잔여 중복 정리."""
    out: list[str] = []
    for ln in lines:
        if out and _line_eq(out[-1], ln, fuzzy):
            continue
        out.append(ln)
    return out


def stitch_scrolls(screens_top_to_bottom: list[list[str]],
                   fuzzy: float = 0.8) -> list[str]:
    """위로 스크롤하며 캡처한 화면들을 하나의 시간순(old→new) 줄 목록으로 결합.

    입력 순서: screens[0]가 가장 최근(스크롤 전, 화면 맨 아래),
    screens[-1]가 가장 오래된(가장 많이 위로 스크롤). 각 화면은 위→아래 줄.

    결과: old→new 순서의 (fuzzy) 중복 제거된 줄 목록.
    """
    # 오래된 화면부터(역순) 누적: 누적(older 윗부분) 아래에 newer 화면을 이어붙임.
    acc: list[str] = []
    for screen in reversed(screens_top_to_bottom):
        cleaned = clean_lines(screen)
        acc = merge_overlapping(acc, cleaned, fuzzy=fuzzy)
    return dedupe_consecutive(acc, fuzzy=max(fuzzy, 0.85))


@dataclass
class OcrDay:
    date: str  # YYYY-MM-DD
    lines: list[str] = field(default_factory=list)


def split_by_date(lines: list[str], default_date: str | None = None) -> list[OcrDay]:
    """줄 목록을 날짜 구분선("YYYY년 M월 D일") 기준으로 일자별로 분할."""
    days: list[OcrDay] = []
    cur: OcrDay | None = None
    if default_date:
        cur = OcrDay(default_date)
        days.append(cur)
    for ln in lines:
        m = DATE_SEP_RE.search(ln)
        if m and len(ln) <= 25:  # 날짜 구분선은 짧음 (메시지 본문 내 날짜 언급과 구분)
            iso = f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}"
            cur = OcrDay(iso)
            days.append(cur)
            continue
        if cur is None:
            cur = OcrDay(default_date or "unknown")
            days.append(cur)
        cur.lines.append(ln)
    if cur is not None and cur not in days:
        days.append(cur)
    # 같은 날짜가 여러 번(기본값 + 실제 구분선, OCR 중복 등) 나오면 한 버킷으로 병합
    merged: dict[str, OcrDay] = {}
    for d in days:
        if not d.lines:
            continue
        if d.date in merged:
            merged[d.date].lines.extend(d.lines)
        else:
            merged[d.date] = OcrDay(d.date, list(d.lines))
    return list(merged.values())


def filter_days_in_range(days: list[OcrDay], start_iso: str, end_iso: str) -> list[OcrDay]:
    return [d for d in days if start_iso <= d.date <= end_iso]


# OCR은 ':'를 '.'/';'로 자주 오인 → 구분자 관대하게
_TIME_RE = re.compile(r"^(오전|오후)?\s*(\d{1,2})[:.;](\d{2})\b")
_TIME_ONLY_RE = re.compile(r"^(오전|오후)?\s*\d{1,2}[:.;]\d{2}\.?$")


def _parse_time_token(line: str) -> str | None:
    """줄 앞부분의 '오전/오후 H:MM' 류 시각을 24h 'HH:MM'로. 없으면 None."""
    m = _TIME_RE.search(line)
    if not m:
        return None
    ampm, h, mnt = m.group(1), int(m.group(2)), int(m.group(3))
    if mnt > 59 or h > 23:
        return None
    if ampm == "오전":
        h = 0 if h == 12 else h
    elif ampm == "오후":
        h = h if h == 12 else h + 12
    return f"{h:02d}:{mnt:02d}"


def messages_from_ocr_lines(room: str, lines: list[str],
                            default_date: str):
    """OCR 줄 목록을 (베스트에포트) Message 객체 리스트로 변환.

    OCR은 발신자·정확 시각을 안정적으로 주지 못하므로:
    - 날짜는 구분선("YYYY년 M월 D일")으로 분할.
    - 시각: '오전/오후 H:MM'만 있는 줄은 시각 마커로 보고 이후 메시지에 적용.
    - 발신자: 식별 불가 → '(OCR)' 고정(요약·검색엔 본문이 핵심).
    각 콘텐츠 줄 1개 = Message 1개. seq는 일자별 0부터.
    """
    import datetime as _dt

    from ..parser.schema import Message

    msgs: list = []
    days = split_by_date(lines, default_date=default_date)
    for day in days:
        try:
            d = _dt.date.fromisoformat(day.date)
        except ValueError:
            continue
        cur_time = "00:00"
        seq = 0
        for ln in day.lines:
            t = _parse_time_token(ln)
            if t and _TIME_ONLY_RE.match(ln.strip()):
                cur_time = t  # 시각만 있는 줄 → 마커, 본문 아님
                continue
            if t:  # 본문 앞에 시각이 붙은 경우: 시각 갱신 + 본문은 시각 제거
                cur_time = t
                ln = _TIME_RE.sub("", ln, count=1).strip()
                if not ln:
                    continue
            hh, mm = int(cur_time[:2]), int(cur_time[3:])
            epoch = int(_dt.datetime.combine(d, _dt.time(hh, mm)).timestamp())
            msgs.append(Message(
                msg_id=f"{room}:{d:%Y%m%d}:{seq:05d}",
                room=room, date=day.date, ts=cur_time, ts_epoch=epoch,
                sender="(OCR)", text=ln, seq=seq,
            ))
            seq += 1
    return msgs


# ---------------------------------------------------------------------------
# Win32 캡처/스크롤 (실 환경 전용) — import 시점에 pywin32 없으면 지연 에러
# ---------------------------------------------------------------------------

def find_chat_window(room_name: str) -> int | None:
    """제목이 room_name과 일치하는 카톡 채팅 창(top-level) HWND 반환."""
    import win32gui
    found: list[int] = []

    def cb(h, _):
        if win32gui.GetClassName(h) == CHAT_WINDOW_CLASS and \
                win32gui.GetWindowText(h) == room_name:
            found.append(h)
        return True

    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def foreground_chat_window() -> int | None:
    """현재 포그라운드가 카톡 채팅 창(EVA, 제목≠카카오톡)이면 그 HWND."""
    import win32gui
    h = win32gui.GetForegroundWindow()
    try:
        if win32gui.GetClassName(h) == CHAT_WINDOW_CLASS and \
                win32gui.GetWindowText(h) not in ("", "카카오톡"):
            return h
    except Exception:
        pass
    return None


def find_list_control(chat_hwnd: int) -> int | None:
    import win32gui
    kids: list[int] = []
    win32gui.EnumChildWindows(chat_hwnd, lambda h, _: kids.append(h) or True, None)
    for h in kids:
        if win32gui.GetClassName(h) == LIST_CONTROL_CLASS:
            return h
    return None


def capture_window(hwnd: int):
    """PrintWindow로 가려진 창도 캡처 → PIL.Image (RGB)."""
    import win32gui
    import win32ui
    from ctypes import windll
    from PIL import Image

    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w, h = r - l, b - t
    dc = win32gui.GetWindowDC(hwnd)
    mfc = win32ui.CreateDCFromHandle(dc)
    sdc = mfc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc, w, h)
    sdc.SelectObject(bmp)
    windll.user32.PrintWindow(hwnd, sdc.GetSafeHdc(), PW_RENDERFULLCONTENT)
    info = bmp.GetInfo()
    bits = bmp.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                           bits, "raw", "BGRX", 0, 1)
    win32gui.DeleteObject(bmp.GetHandle())
    sdc.DeleteDC()
    mfc.DeleteDC()
    win32gui.ReleaseDC(hwnd, dc)
    return img


def list_region_box(chat_hwnd: int, list_hwnd: int) -> tuple[int, int, int, int]:
    """채팅 창 캡처에서 메시지 리스트 영역만 잘라낼 crop box(창 기준 좌표)."""
    import win32gui
    wl, wt, wr, wb = win32gui.GetWindowRect(chat_hwnd)
    ll, lt, lr, lb = win32gui.GetWindowRect(list_hwnd)
    return (ll - wl, lt - wt, lr - wl, lb - wt)


def capture_messages(chat_hwnd: int, list_hwnd: int | None = None):
    """채팅 창을 캡처하되 메시지 리스트 영역만 crop → PIL.Image.

    상단 헤더(방 이름·인원·☰)와 하단 입력바를 제외해 OCR 잡음을 줄인다.
    list_hwnd 미지정 시 전체 창 반환.
    """
    img = capture_window(chat_hwnd)
    if list_hwnd:
        box = list_region_box(chat_hwnd, list_hwnd)
        # 음수/역전 방어
        l, t, r, b = box
        l, t = max(0, l), max(0, t)
        if r > l and b > t:
            img = img.crop((l, t, min(r, img.width), min(b, img.height)))
    return img


def scroll_list(list_hwnd: int, clicks: int) -> None:
    """포커스 없이 대화 리스트 스크롤. clicks>0=위(older), <0=아래(newer)."""
    import win32api
    import win32con
    import win32gui

    l, t, r, b = win32gui.GetWindowRect(list_hwnd)
    cx, cy = (l + r) // 2, (t + b) // 2
    lparam = win32api.MAKELONG(cx, cy)
    delta = 120 if clicks > 0 else -120
    for _ in range(abs(clicks)):
        win32gui.PostMessage(list_hwnd, win32con.WM_MOUSEWHEEL,
                             win32api.MAKELONG(0, delta & 0xFFFF), lparam)


def _windows_ocr_lines(pil_img, lang: str = "ko") -> list[str] | None:
    """Windows 내장 OCR(Windows.Media.Ocr)로 줄 목록 반환. 사용 불가 시 None.

    한국어 정확도가 easyocr보다 높고 빠르며 모델 다운로드가 없다(OCR 언어팩 필요).
    winrt 비동기 API는 서버의 실행 중 이벤트 루프와 충돌하지 않도록 별도 스레드의
    새 루프에서 돌린다.
    """
    import concurrent.futures
    import io

    def _run() -> list[str] | None:
        import asyncio

        async def _go():
            from winrt.windows.globalization import Language
            from winrt.windows.graphics.imaging import BitmapDecoder
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.storage.streams import (
                DataWriter,
                InMemoryRandomAccessStream,
            )

            buf = io.BytesIO()
            pil_img.save(buf, "PNG")
            stream = InMemoryRandomAccessStream()
            writer = DataWriter(stream)
            writer.write_bytes(buf.getvalue())
            await writer.store_async()
            stream.seek(0)
            decoder = await BitmapDecoder.create_async(stream)
            bmp = await decoder.get_software_bitmap_async()
            eng = OcrEngine.try_create_from_language(Language(lang)) or \
                OcrEngine.try_create_from_user_profile_languages()
            if eng is None:
                return None
            result = await eng.recognize_async(bmp)
            return [ln.text for ln in result.lines]

        return asyncio.run(_go())

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_run).result()
    except Exception as e:  # winrt 미설치/언어팩 없음/실패 → easyocr로 폴백
        _log(f"[ocr] Windows OCR 불가({e.__class__.__name__}: {e}), easyocr 폴백")
        return None


def _easyocr_lines(pil_img, reader, upscale: int) -> list[str]:
    from PIL import ImageFilter, ImageOps

    g = pil_img.convert("L")
    big = g.resize((g.width * upscale, g.height * upscale))
    big = ImageOps.autocontrast(big, cutoff=1)
    big = big.filter(ImageFilter.UnsharpMask(radius=1.2, percent=120))
    if reader is None:
        import easyocr
        reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
    import numpy as np
    results = reader.readtext(np.array(big), detail=1, paragraph=False,
                              text_threshold=0.6, low_text=0.3, contrast_ths=0.05)
    results.sort(key=lambda r: min(p[1] for p in r[0]))
    return [r[1] for r in results]


def ocr_image(img, reader=None, upscale: int = 3, engine: str = "auto") -> list[str]:
    """업스케일 후 OCR → 줄 목록(위→아래).

    engine: 'auto'(Windows OCR 우선, 실패 시 easyocr) | 'windows' | 'easyocr'.
    Windows OCR이 한국어 정확도·속도 모두 우수해 기본 1순위.
    """
    from PIL import Image

    if engine in ("auto", "windows"):
        big = img.resize((img.width * upscale, img.height * upscale), Image.LANCZOS)
        lines = _windows_ocr_lines(big)
        if lines is not None:
            return lines
        if engine == "windows":
            return []
    return _easyocr_lines(img, reader, upscale)


def extract_conversation(room_name: str, max_screens: int = 8,
                         reader=None, settle: float = 0.8,
                         scroll_clicks: int = 3,
                         open_key: str | None = None) -> list[str]:
    """대화창을 백그라운드로 위로 스크롤하며 캡처·OCR해 시간순 줄 목록 반환.

    캡처·스크롤은 포커스를 뺏지 않는다(PrintWindow + posted WM_MOUSEWHEEL).
    대상 창이 안 열려 있으면 open_key(링크 우선)로 통합검색해 한 번 연다(이때만 포커스).
    캡처는 메시지 리스트 영역만 crop해 헤더/입력바 잡음을 줄인다. 끝나면 스크롤 원위치.

    Raises: RuntimeError (창을 끝내 못 찾으면).
    """
    hwnd = find_chat_window(room_name)
    if not hwnd and open_key:
        # 안 열려 있으면 링크/이름으로 검색해 연다(여는 동안만 포커스 사용).
        try:
            from . import window as _w
            _w.search_and_open_room(open_key)
            time.sleep(1.0)
        except Exception as e:
            _log(f"[ocr] 방 열기 실패: {e}")
        hwnd = find_chat_window(room_name) or foreground_chat_window()
    if not hwnd:
        raise RuntimeError(
            f"'{room_name}' 채팅 창을 찾지 못했습니다. 그 방을 PC카톡에서 "
            "별도 창으로 열어두거나(가려져도 OK, 트레이 ❌), 방의 오픈채팅 "
            "링크를 등록/지정해 주세요(이름만으론 검색 진입이 안 될 수 있음)."
        )
    lst = find_list_control(hwnd)
    screens: list[list[str]] = []
    for i in range(max_screens):
        img = capture_messages(hwnd, lst)
        screens.append(ocr_image(img, reader=reader))
        if i < max_screens - 1 and lst:
            scroll_list(lst, scroll_clicks)
            time.sleep(settle)
    if lst:  # 스크롤 원위치(아래로 충분히)
        scroll_list(lst, -(max_screens * scroll_clicks + 4))
    return stitch_scrolls(screens)
