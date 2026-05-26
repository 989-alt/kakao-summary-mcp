"""메시지를 turn(연속된 같은 발신자 발화 묶음) 단위로 청킹."""
from __future__ import annotations

from ..parser.schema import Message, Turn


def messages_to_turns(msgs: list[Message], max_gap_sec: int = 1800) -> list[Turn]:
    turns: list[Turn] = []
    cur: list[Message] = []

    def flush(buf: list[Message]) -> None:
        if not buf:
            return
        head = buf[0]
        idx = len(turns)
        turns.append(Turn(
            turn_id=f"{head.room}:{head.date.replace('-', '')}:t{idx:04d}",
            room=head.room,
            date=head.date,
            sender=head.sender,
            ts_start=head.ts,
            ts_epoch=head.ts_epoch,
            msg_ids=[m.msg_id for m in buf],
            text="\n".join(m.text for m in buf),
        ))

    for m in msgs:
        if not cur:
            cur.append(m)
            continue
        last = cur[-1]
        if m.sender == last.sender and (m.ts_epoch - last.ts_epoch) <= max_gap_sec:
            cur.append(m)
        else:
            flush(cur)
            cur = [m]
    flush(cur)
    return turns
