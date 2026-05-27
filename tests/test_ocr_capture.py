"""Tests for the pure logic of the OCR background extractor.

Win32/OCR pieces require the live app; here we cover the deterministic parts:
line cleaning, overlap merge, multi-screen stitching, and date splitting.
"""
from __future__ import annotations

from kakao_summary_mcp.extractor.ocr_capture import (
    clean_lines,
    dedupe_consecutive,
    filter_days_in_range,
    merge_overlapping,
    messages_from_ocr_lines,
    split_by_date,
    stitch_scrolls,
)


class TestCleanLines:
    def test_strips_and_drops_blank(self):
        assert clean_lines(["  hi  ", "", "   "]) == ["hi"]

    def test_drops_ui_noise(self):
        assert clean_lines(["메시지 입력", "안녕", "전송"]) == ["안녕"]


class TestMergeOverlapping:
    def test_no_overlap_concatenates(self):
        assert merge_overlapping(["a", "b"], ["c", "d"]) == ["a", "b", "c", "d"]

    def test_full_overlap(self):
        assert merge_overlapping(["a", "b", "c"], ["b", "c", "d"]) == ["a", "b", "c", "d"]

    def test_single_line_overlap(self):
        assert merge_overlapping(["x", "y"], ["y", "z"]) == ["x", "y", "z"]

    def test_empty_upper(self):
        assert merge_overlapping([], ["a", "b"]) == ["a", "b"]

    def test_empty_lower(self):
        assert merge_overlapping(["a"], []) == ["a"]

    def test_identical(self):
        assert merge_overlapping(["a", "b"], ["a", "b"]) == ["a", "b"]


class TestStitchScrolls:
    def test_two_overlapping_screens(self):
        # screens[0] = newest (bottom), screens[1] = older (after scroll up)
        newest = ["msg3", "msg4", "msg5"]
        older = ["msg1", "msg2", "msg3"]
        # stitched old->new with overlap "msg3" removed once
        assert stitch_scrolls([newest, older]) == ["msg1", "msg2", "msg3", "msg4", "msg5"]

    def test_three_screens(self):
        s0 = ["d", "e"]      # newest
        s1 = ["c", "d"]
        s2 = ["a", "b", "c"]  # oldest
        assert stitch_scrolls([s0, s1, s2]) == ["a", "b", "c", "d", "e"]

    def test_single_screen(self):
        assert stitch_scrolls([["a", "b"]]) == ["a", "b"]

    def test_cleans_noise_while_stitching(self):
        assert stitch_scrolls([["b", "메시지 입력"], ["a", "b"]]) == ["a", "b"]


class TestFuzzyMergeAndDedupe:
    def test_fuzzy_overlap_merges_near_identical_ocr(self):
        # Same sentence OCR'd twice with minor garbling should be treated as overlap.
        newest = ["웨비나는 보통 목요일날 진행하며", "여기까지 읽으셨습니다"]
        older = ["공개 웨비나 진행합니다", "웨비나는 보통 목오일날 진향하고"]
        merged = merge_overlapping(older, newest, fuzzy=0.7)
        # the near-identical 웨비나 line should appear once, not twice
        webina = [l for l in merged if l.startswith("웨비나는 보통")]
        assert len(webina) == 1

    def test_fuzzy_does_not_merge_short_distinct(self):
        # short lines must not be fuzzily merged
        assert merge_overlapping(["오후 11:05"], ["오후 11:16"], fuzzy=0.7) == \
            ["오후 11:05", "오후 11:16"]

    def test_dedupe_consecutive_removes_near_dupes(self):
        lines = ["여러분 안녕하세요!", "여러분 안녕하서요!", "다른 메시지"]
        out = dedupe_consecutive(lines, fuzzy=0.8)
        assert out == ["여러분 안녕하세요!", "다른 메시지"]

    def test_dedupe_keeps_distinct(self):
        lines = ["회의 10시", "점심 12시", "회의 10시"]
        assert dedupe_consecutive(lines, fuzzy=0.85) == ["회의 10시", "점심 12시", "회의 10시"]


class TestSplitByDate:
    def test_splits_on_date_separator(self):
        lines = ["2026년 5월 26일 화요일", "안녕", "회의 10시",
                 "2026년 5월 27일 수요일", "좋은 아침"]
        days = split_by_date(lines)
        assert [d.date for d in days] == ["2026-05-26", "2026-05-27"]
        assert days[0].lines == ["안녕", "회의 10시"]
        assert days[1].lines == ["좋은 아침"]

    def test_text_mentioning_date_not_treated_as_separator(self):
        # A long message line that merely mentions a date is not a separator.
        lines = ["2026년 5월 26일 화요일",
                 "다음 모임은 2026년 6월 3일에 진행하기로 했어요 모두 참석 바랍니다"]
        days = split_by_date(lines)
        assert len(days) == 1
        assert days[0].date == "2026-05-26"
        assert any("6월 3일" in l for l in days[0].lines)

    def test_default_date_before_first_separator(self):
        days = split_by_date(["leading text"], default_date="2026-05-27")
        assert days[0].date == "2026-05-27"
        assert days[0].lines == ["leading text"]

    def test_same_date_buckets_merged(self):
        # default date + a real separator for the SAME date → one bucket
        days = split_by_date(
            ["pre-separator line", "2026년 5월 27일 수요일", "post line"],
            default_date="2026-05-27",
        )
        assert len(days) == 1
        assert days[0].date == "2026-05-27"
        assert days[0].lines == ["pre-separator line", "post line"]


class TestMessagesFromOcrLines:
    def test_builds_messages_with_date_and_text(self):
        lines = ["2026년 5월 27일 수요일", "회의 10시", "점심 같이 먹어요"]
        msgs = messages_from_ocr_lines("방", lines, default_date="2026-05-27")
        assert [m.text for m in msgs] == ["회의 10시", "점심 같이 먹어요"]
        assert all(m.date == "2026-05-27" for m in msgs)
        assert all(m.room == "방" and m.sender == "(OCR)" for m in msgs)

    def test_time_only_line_sets_timestamp(self):
        # OCR often reads ':' as '.'; "오전 9.15" alone is a time marker, not content
        lines = ["오전 9.15", "안녕하세요"]
        msgs = messages_from_ocr_lines("방", lines, default_date="2026-05-27")
        assert len(msgs) == 1
        assert msgs[0].text == "안녕하세요"
        assert msgs[0].ts == "09:15"

    def test_pm_time_converted_24h(self):
        lines = ["오후 1:30", "오후 회의"]
        msgs = messages_from_ocr_lines("방", lines, default_date="2026-05-27")
        assert msgs[0].ts == "13:30"

    def test_inline_leading_time_stripped_into_text_time(self):
        lines = ["오전 8:05 좋은 아침입니다"]
        msgs = messages_from_ocr_lines("방", lines, default_date="2026-05-27")
        assert len(msgs) == 1
        assert msgs[0].ts == "08:05"
        assert msgs[0].text == "좋은 아침입니다"

    def test_seq_resets_per_day_and_msg_id_format(self):
        lines = ["2026년 5월 26일 화요일", "a", "b",
                 "2026년 5월 27일 수요일", "c"]
        msgs = messages_from_ocr_lines("room", lines, default_date="2026-05-26")
        d26 = [m for m in msgs if m.date == "2026-05-26"]
        d27 = [m for m in msgs if m.date == "2026-05-27"]
        assert d26[0].msg_id == "room:20260526:00000"
        assert d26[1].msg_id == "room:20260526:00001"
        assert d27[0].msg_id == "room:20260527:00000"


class TestFilterDaysInRange:
    def test_keeps_only_in_range(self):
        days = split_by_date([
            "2026년 5월 25일 일요일", "a",
            "2026년 5월 26일 월요일", "b",
            "2026년 5월 27일 화요일", "c",
        ])
        kept = filter_days_in_range(days, "2026-05-26", "2026-05-27")
        assert [d.date for d in kept] == ["2026-05-26", "2026-05-27"]
