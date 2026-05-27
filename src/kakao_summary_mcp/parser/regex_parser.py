"""PC카톡 '대화 내용 내보내기' .txt 파일 파서."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .schema import Message

MSG_RE = re.compile(
    r"^\[(?P<sender>.+?)\] \[(?P<ampm>오전|오후) (?P<h>\d{1,2}):(?P<m>\d{2})\] (?P<text>.*)$"
)
DATE_RE = re.compile(
    r"^-+\s*(?P<y>\d{4})년\s*(?P<mo>\d{1,2})월\s*(?P<d>\d{1,2})일.*-+$"
)


def _to_24h(ampm: str, h: int, m: int) -> tuple[int, int]:
    if ampm == "오전":
        return (0 if h == 12 else h, m)
    return (h if h == 12 else h + 12, m)


def parse_file(
    path: Path,
    room: str,
    target_date: dt.date | None = None,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> list[Message]:
    """PC카톡 내보내기 .txt를 파싱.

    날짜 필터:
        - start_date/end_date가 주어지면 [start, end] (양끝 포함) 범위로 필터.
        - 하위호환: target_date만 주어지면 그 날짜 단일로 필터(start=end=target).
        - 셋 다 None이면 전체 반환.
    """
    if start_date is None and end_date is None and target_date is not None:
        start_date = end_date = target_date
    if start_date is not None and end_date is not None and start_date > end_date:
        start_date, end_date = end_date, start_date

    msgs: list[Message] = []
    cur_date: dt.date | None = None
    last_msg: Message | None = None
    seq_by_date: dict[dt.date, int] = {}

    with open(path, "r", encoding="utf-8-sig") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n").rstrip("\r")

            dm = DATE_RE.match(line)
            if dm:
                cur_date = dt.date(int(dm["y"]), int(dm["mo"]), int(dm["d"]))
                last_msg = None
                continue

            mm = MSG_RE.match(line)
            if mm and cur_date is not None:
                h24, m = _to_24h(mm["ampm"], int(mm["h"]), int(mm["m"]))
                ts_str = f"{h24:02d}:{m:02d}"
                epoch = int(dt.datetime.combine(cur_date, dt.time(h24, m)).timestamp())
                seq = seq_by_date.get(cur_date, 0)
                seq_by_date[cur_date] = seq + 1
                msg = Message(
                    msg_id=f"{room}:{cur_date:%Y%m%d}:{seq:05d}",
                    room=room,
                    date=cur_date.isoformat(),
                    ts=ts_str,
                    ts_epoch=epoch,
                    sender=mm["sender"],
                    text=mm["text"],
                    seq=seq,
                )
                msgs.append(msg)
                last_msg = msg
                continue

            if last_msg is not None and line.strip():
                last_msg.text += "\n" + line

    if start_date is not None and end_date is not None:
        s_iso, e_iso = start_date.isoformat(), end_date.isoformat()
        msgs = [m for m in msgs if s_iso <= m.date <= e_iso]
    return msgs


def write_jsonl(msgs: list[Message], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps(m.to_dict(), ensure_ascii=False) + "\n")
