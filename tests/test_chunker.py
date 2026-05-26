"""Tests for kakao_summary_mcp.indexer.chunker (pure logic, fully offline)."""
from __future__ import annotations

import datetime as dt

import pytest

from kakao_summary_mcp.indexer.chunker import messages_to_turns
from kakao_summary_mcp.parser.schema import Message


def _make_msg(sender: str, ts_epoch: int, seq: int = 0,
              room: str = "room1", date: str = "2026-05-26",
              text: str = "hello") -> Message:
    """Helper to build a Message with minimal boilerplate."""
    hm = dt.datetime.fromtimestamp(ts_epoch)
    return Message(
        msg_id=f"{room}:{date.replace('-', '')}:{seq:05d}",
        room=room,
        date=date,
        ts=f"{hm.hour:02d}:{hm.minute:02d}",
        ts_epoch=ts_epoch,
        sender=sender,
        text=text,
        seq=seq,
    )


BASE_EPOCH = int(dt.datetime(2026, 5, 26, 9, 0, 0).timestamp())


class TestMessageToTurns:
    def test_empty(self):
        assert messages_to_turns([]) == []

    def test_single_message_one_turn(self):
        msgs = [_make_msg("Alice", BASE_EPOCH, seq=0, text="hi")]
        turns = messages_to_turns(msgs)
        assert len(turns) == 1
        assert turns[0].sender == "Alice"
        assert turns[0].text == "hi"

    def test_same_sender_merges_within_gap(self):
        """Two messages from same sender within max_gap_sec → one turn."""
        msgs = [
            _make_msg("Alice", BASE_EPOCH, seq=0, text="hello"),
            _make_msg("Alice", BASE_EPOCH + 60, seq=1, text="world"),
        ]
        turns = messages_to_turns(msgs, max_gap_sec=1800)
        assert len(turns) == 1
        assert turns[0].text == "hello\nworld"
        assert turns[0].msg_ids == [
            "room1:20260526:00000",
            "room1:20260526:00001",
        ]

    def test_different_sender_splits(self):
        """Different sender always starts a new turn."""
        msgs = [
            _make_msg("Alice", BASE_EPOCH, seq=0, text="hi"),
            _make_msg("Bob", BASE_EPOCH + 30, seq=1, text="hey"),
        ]
        turns = messages_to_turns(msgs, max_gap_sec=1800)
        assert len(turns) == 2
        assert turns[0].sender == "Alice"
        assert turns[1].sender == "Bob"

    def test_same_sender_gap_too_large_splits(self):
        """Same sender but gap > max_gap_sec → two turns."""
        msgs = [
            _make_msg("Alice", BASE_EPOCH, seq=0, text="first"),
            _make_msg("Alice", BASE_EPOCH + 3600, seq=1, text="second"),
        ]
        turns = messages_to_turns(msgs, max_gap_sec=1800)
        assert len(turns) == 2

    def test_same_sender_exactly_at_gap_boundary_merges(self):
        """Gap == max_gap_sec should still merge (<=)."""
        msgs = [
            _make_msg("Alice", BASE_EPOCH, seq=0, text="a"),
            _make_msg("Alice", BASE_EPOCH + 1800, seq=1, text="b"),
        ]
        turns = messages_to_turns(msgs, max_gap_sec=1800)
        assert len(turns) == 1

    def test_turn_id_format(self):
        """turn_id must be room:YYYYMMDD:tNNNN (zero-padded 4 digits)."""
        msgs = [
            _make_msg("Alice", BASE_EPOCH, seq=0, room="myroom"),
        ]
        turns = messages_to_turns(msgs)
        assert turns[0].turn_id == "myroom:20260526:t0000"

    def test_turn_id_increments(self):
        msgs = [
            _make_msg("Alice", BASE_EPOCH, seq=0, text="a"),
            _make_msg("Bob", BASE_EPOCH + 10, seq=1, text="b"),
            _make_msg("Alice", BASE_EPOCH + 20, seq=2, text="c"),
        ]
        turns = messages_to_turns(msgs)
        assert turns[0].turn_id.endswith(":t0000")
        assert turns[1].turn_id.endswith(":t0001")
        assert turns[2].turn_id.endswith(":t0002")

    def test_text_aggregation_newline_join(self):
        msgs = [
            _make_msg("Alice", BASE_EPOCH, seq=0, text="line1"),
            _make_msg("Alice", BASE_EPOCH + 60, seq=1, text="line2"),
            _make_msg("Alice", BASE_EPOCH + 120, seq=2, text="line3"),
        ]
        turns = messages_to_turns(msgs)
        assert len(turns) == 1
        assert turns[0].text == "line1\nline2\nline3"

    def test_ts_start_is_first_message(self):
        msgs = [
            _make_msg("Alice", BASE_EPOCH, seq=0, text="first"),
            _make_msg("Alice", BASE_EPOCH + 60, seq=1, text="second"),
        ]
        turns = messages_to_turns(msgs)
        # ts_start should be the ts of the first message
        assert turns[0].ts_start == msgs[0].ts

    def test_msg_ids_order_preserved(self):
        msgs = [
            _make_msg("Alice", BASE_EPOCH, seq=0, text="a"),
            _make_msg("Alice", BASE_EPOCH + 10, seq=1, text="b"),
            _make_msg("Alice", BASE_EPOCH + 20, seq=2, text="c"),
        ]
        turns = messages_to_turns(msgs)
        assert turns[0].msg_ids == [
            "room1:20260526:00000",
            "room1:20260526:00001",
            "room1:20260526:00002",
        ]

    def test_room_and_date_propagated(self):
        msgs = [_make_msg("Alice", BASE_EPOCH, seq=0, room="chatroom", date="2026-05-26")]
        turns = messages_to_turns(msgs)
        assert turns[0].room == "chatroom"
        assert turns[0].date == "2026-05-26"
