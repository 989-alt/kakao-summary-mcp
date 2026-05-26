"""파싱된 메시지/turn 데이터 스키마."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Message:
    msg_id: str
    room: str
    date: str
    ts: str
    ts_epoch: int
    sender: str
    text: str
    seq: int
    is_system: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Turn:
    turn_id: str
    room: str
    date: str
    sender: str
    ts_start: str
    ts_epoch: int
    msg_ids: list[str] = field(default_factory=list)
    text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
