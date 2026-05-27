"""Tests for kakao_summary_mcp.parser (pure logic, fully offline)."""
from __future__ import annotations

import datetime as dt

import pytest

from kakao_summary_mcp.parser.regex_parser import _to_24h, parse_file


# ---------------------------------------------------------------------------
# _to_24h
# ---------------------------------------------------------------------------

class TestTo24h:
    def test_am_normal(self):
        assert _to_24h("오전", 9, 15) == (9, 15)

    def test_am_midnight_12(self):
        # 오전 12:00 → 00:00
        assert _to_24h("오전", 12, 0) == (0, 0)

    def test_am_midnight_12_30(self):
        assert _to_24h("오전", 12, 30) == (0, 30)

    def test_pm_noon_12(self):
        # 오후 12:00 → 12:00  (noon)
        assert _to_24h("오후", 12, 0) == (12, 0)

    def test_pm_1(self):
        # 오후 1:30 → 13:30
        assert _to_24h("오후", 1, 30) == (13, 30)

    def test_pm_11(self):
        assert _to_24h("오후", 11, 59) == (23, 59)

    def test_am_1(self):
        assert _to_24h("오전", 1, 0) == (1, 0)


# ---------------------------------------------------------------------------
# parse_file
# ---------------------------------------------------------------------------

class TestParseFile:
    def test_basic_message_count(self, sample_txt):
        msgs = parse_file(sample_txt, room="test_room")
        # 5/26: 7 messages ([홍길동]×5, [김철수]×2; the bare continuation line is
        # appended to the prior message's text, not counted). 5/27: 2 → 9 total.
        assert len(msgs) == 9

    def test_sender_fields(self, sample_txt):
        msgs = parse_file(sample_txt, room="test_room")
        senders = {m.sender for m in msgs}
        assert senders == {"홍길동", "김철수"}

    def test_msg_id_format(self, sample_txt):
        msgs = parse_file(sample_txt, room="test_room")
        # first message should be room:YYYYMMDD:00000
        first = msgs[0]
        assert first.msg_id == "test_room:20260526:00000"
        assert first.room == "test_room"
        assert first.date == "2026-05-26"

    def test_sequential_msg_ids(self, sample_txt):
        msgs = parse_file(sample_txt, room="myroom")
        may26 = [m for m in msgs if m.date == "2026-05-26"]
        for i, m in enumerate(may26):
            assert m.msg_id == f"myroom:20260526:{i:05d}"

    def test_seq_resets_per_date(self, sample_txt):
        msgs = parse_file(sample_txt, room="test_room")
        may27 = [m for m in msgs if m.date == "2026-05-27"]
        # msg_id uses the date in YYYYMMDD, i.e., 20260527 for 2026-05-27
        assert may27[0].msg_id == "test_room:20260527:00000"

    def test_multiline_continuation(self, sample_txt):
        msgs = parse_file(sample_txt, room="test_room")
        # 김철수's second message (오전 9:18) should have the continuation line appended
        철수_msgs = [m for m in msgs if m.sender == "김철수" and m.date == "2026-05-26"]
        msg_with_cont = [m for m in 철수_msgs if "회의실 A에서 만나요" in m.text]
        assert len(msg_with_cont) == 1
        assert "이 줄은 연속 메시지입니다" in msg_with_cont[0].text

    def test_target_date_filter(self, sample_txt):
        target = dt.date(2026, 5, 27)
        msgs = parse_file(sample_txt, room="test_room", target_date=target)
        assert all(m.date == "2026-05-27" for m in msgs)
        assert len(msgs) == 2

    def test_target_date_no_match(self, sample_txt):
        target = dt.date(2025, 1, 1)
        msgs = parse_file(sample_txt, room="test_room", target_date=target)
        assert msgs == []

    def test_ts_epoch_am_12(self, sample_txt):
        """오전 12:00 must map to hour=0, not 12."""
        msgs = parse_file(sample_txt, room="test_room")
        msg = next(m for m in msgs if m.ts == "00:00" and m.date == "2026-05-26")
        d = dt.datetime.fromtimestamp(msg.ts_epoch)
        assert d.hour == 0

    def test_ts_epoch_pm_12(self, sample_txt):
        """오후 12:00 must map to hour=12."""
        msgs = parse_file(sample_txt, room="test_room")
        msg = next(m for m in msgs if m.ts == "12:00" and m.date == "2026-05-26")
        d = dt.datetime.fromtimestamp(msg.ts_epoch)
        assert d.hour == 12

    def test_ts_epoch_pm_1(self, sample_txt):
        """오후 1:30 must map to hour=13."""
        msgs = parse_file(sample_txt, room="test_room")
        msg = next(m for m in msgs if m.ts == "13:30" and m.date == "2026-05-26")
        d = dt.datetime.fromtimestamp(msg.ts_epoch)
        assert d.hour == 13
        assert d.minute == 30


class TestParseFileRange:
    def test_range_includes_both_days(self, sample_txt):
        msgs = parse_file(
            sample_txt, room="r",
            start_date=dt.date(2026, 5, 26), end_date=dt.date(2026, 5, 27),
        )
        dates = {m.date for m in msgs}
        assert dates == {"2026-05-26", "2026-05-27"}
        assert len(msgs) == 9  # all messages across both days

    def test_range_single_day_excludes_other(self, sample_txt):
        msgs = parse_file(
            sample_txt, room="r",
            start_date=dt.date(2026, 5, 27), end_date=dt.date(2026, 5, 27),
        )
        assert {m.date for m in msgs} == {"2026-05-27"}
        assert len(msgs) == 2

    def test_range_reversed_is_swapped(self, sample_txt):
        msgs = parse_file(
            sample_txt, room="r",
            start_date=dt.date(2026, 5, 27), end_date=dt.date(2026, 5, 26),
        )
        assert {m.date for m in msgs} == {"2026-05-26", "2026-05-27"}

    def test_range_no_match_empty(self, sample_txt):
        msgs = parse_file(
            sample_txt, room="r",
            start_date=dt.date(2025, 1, 1), end_date=dt.date(2025, 1, 31),
        )
        assert msgs == []

    def test_target_date_still_works(self, sample_txt):
        """Back-compat: target_date alone filters to that single day."""
        msgs = parse_file(sample_txt, room="r", target_date=dt.date(2026, 5, 26))
        assert {m.date for m in msgs} == {"2026-05-26"}

    def test_no_filter_returns_all(self, sample_txt):
        msgs = parse_file(sample_txt, room="r")
        assert len(msgs) == 9
