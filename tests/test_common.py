"""Tests for kakao_summary_mcp.common (pure logic, fully offline)."""
from __future__ import annotations

import datetime as dt

import pytest

from kakao_summary_mcp.common import (
    always_rooms,
    enabled_rooms,
    open_key_for,
    resolve_date,
    resolve_range,
    room_entries,
    room_link_map,
    safe_room_dir,
)

FIXED = dt.date(2026, 5, 27)
YEST = dt.date(2026, 5, 26)


class TestResolveDate:
    def test_today(self):
        assert resolve_date("today") == dt.date.today()

    def test_오늘(self):
        assert resolve_date("오늘") == dt.date.today()

    def test_yesterday(self):
        assert resolve_date("yesterday") == dt.date.today() - dt.timedelta(days=1)

    def test_어제(self):
        assert resolve_date("어제") == dt.date.today() - dt.timedelta(days=1)

    def test_none_returns_today(self):
        assert resolve_date(None) == dt.date.today()

    def test_empty_string_returns_today(self):
        assert resolve_date("") == dt.date.today()

    def test_iso_date(self):
        assert resolve_date("2026-05-26") == dt.date(2026, 5, 26)

    def test_iso_date_single_digit_month_day(self):
        assert resolve_date("2026-1-5") == dt.date(2026, 1, 5)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            resolve_date("not-a-date")

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            resolve_date("26/05/2026")


class TestEnabledRooms:
    def test_override_list(self):
        cfg = {}
        result = enabled_rooms(cfg, override=["room1", "room2"])
        assert result == ["room1", "room2"]

    def test_override_strips_whitespace(self):
        cfg = {}
        result = enabled_rooms(cfg, override=["  room1  ", " room2"])
        assert result == ["room1", "room2"]

    def test_override_filters_empty(self):
        cfg = {}
        result = enabled_rooms(cfg, override=["room1", "", "room2"])
        assert result == ["room1", "room2"]

    def test_from_cfg_enabled_true(self):
        cfg = {
            "rooms": [
                {"name": "방1", "enabled": True},
                {"name": "방2", "enabled": False},
                {"name": "방3", "enabled": True},
            ]
        }
        result = enabled_rooms(cfg)
        assert result == ["방1", "방3"]

    def test_from_cfg_only_enabled(self):
        cfg = {
            "rooms": [
                {"name": "방A", "enabled": False},
            ]
        }
        result = enabled_rooms(cfg)
        assert result == []

    def test_from_cfg_no_rooms_key(self):
        cfg = {}
        result = enabled_rooms(cfg)
        assert result == []

    def test_override_takes_precedence_over_cfg(self):
        cfg = {
            "rooms": [
                {"name": "방1", "enabled": True},
            ]
        }
        result = enabled_rooms(cfg, override=["custom_room"])
        assert result == ["custom_room"]


class TestResolveRange:
    def test_default_is_yesterday(self):
        assert resolve_range(None, today=FIXED) == (YEST, YEST, False)

    def test_empty_string_is_yesterday(self):
        assert resolve_range("  ", today=FIXED) == (YEST, YEST, False)

    def test_yesterday_keyword(self):
        assert resolve_range("yesterday", today=FIXED) == (YEST, YEST, False)
        assert resolve_range("어제", today=FIXED) == (YEST, YEST, False)

    def test_today_keyword(self):
        assert resolve_range("today", today=FIXED) == (FIXED, FIXED, False)
        assert resolve_range("오늘", today=FIXED) == (FIXED, FIXED, False)

    def test_single_iso_date(self):
        assert resolve_range("2026-05-20", today=FIXED) == (
            dt.date(2026, 5, 20), dt.date(2026, 5, 20), False)

    def test_explicit_range_tilde(self):
        assert resolve_range("2026-05-21~2026-05-25", today=FIXED) == (
            dt.date(2026, 5, 21), dt.date(2026, 5, 25), False)

    def test_explicit_range_dotdot(self):
        assert resolve_range("2026-05-21..2026-05-23", today=FIXED) == (
            dt.date(2026, 5, 21), dt.date(2026, 5, 23), False)

    def test_explicit_range_to(self):
        assert resolve_range("2026-05-21 to 2026-05-22", today=FIXED) == (
            dt.date(2026, 5, 21), dt.date(2026, 5, 22), False)

    def test_range_swaps_when_reversed(self):
        assert resolve_range("2026-05-25~2026-05-21", today=FIXED) == (
            dt.date(2026, 5, 21), dt.date(2026, 5, 25), False)

    def test_last_n_days(self):
        # 지난 3일 = 오늘 포함 최근 3일 → 5/25~5/27
        assert resolve_range("지난 3일", today=FIXED) == (
            dt.date(2026, 5, 25), FIXED, False)

    def test_last_n_days_english(self):
        assert resolve_range("last 2 days", today=FIXED) == (
            dt.date(2026, 5, 26), FIXED, False)

    def test_seven_day_range_not_clamped(self):
        # 5/21~5/27 = exactly 7 days
        s, e, clamped = resolve_range("2026-05-21~2026-05-27", today=FIXED)
        assert (s, e) == (dt.date(2026, 5, 21), FIXED)
        assert clamped is False

    def test_over_seven_days_clamped_to_recent_seven(self):
        # 5/1~5/27 spans 27 days → clamp to most-recent 7 ending 5/27 → 5/21~5/27
        s, e, clamped = resolve_range("2026-05-01~2026-05-27", today=FIXED)
        assert e == FIXED
        assert (e - s).days + 1 == 7
        assert s == dt.date(2026, 5, 21)
        assert clamped is True

    def test_last_30_days_clamped(self):
        s, e, clamped = resolve_range("지난 30일", today=FIXED)
        assert (e - s).days + 1 == 7
        assert clamped is True

    def test_tuple_spec(self):
        assert resolve_range(("2026-05-20", "2026-05-22"), today=FIXED) == (
            dt.date(2026, 5, 20), dt.date(2026, 5, 22), False)

    def test_tuple_none_none_is_yesterday(self):
        assert resolve_range((None, None), today=FIXED) == (YEST, YEST, False)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            resolve_range("garbage", today=FIXED)


class TestRoomEntries:
    def test_normalizes_missing_mode_to_always(self):
        cfg = {"rooms": [{"name": "공부방", "enabled": True}]}
        entries = room_entries(cfg)
        assert entries == [{"name": "공부방", "mode": "always", "link": "", "enabled": True}]

    def test_keeps_optional_mode(self):
        cfg = {"rooms": [{"name": "방", "mode": "optional", "enabled": True, "link": "u"}]}
        assert room_entries(cfg)[0]["mode"] == "optional"
        assert room_entries(cfg)[0]["link"] == "u"

    def test_invalid_mode_falls_back_to_always(self):
        cfg = {"rooms": [{"name": "방", "mode": "weird", "enabled": True}]}
        assert room_entries(cfg)[0]["mode"] == "always"

    def test_skips_entries_without_name(self):
        cfg = {"rooms": [{"enabled": True}, "not-a-dict", {"name": "ok", "enabled": True}]}
        names = [e["name"] for e in room_entries(cfg)]
        assert names == ["ok"]

    def test_empty(self):
        assert room_entries({}) == []


class TestAlwaysRooms:
    def test_only_enabled_always(self):
        cfg = {"rooms": [
            {"name": "A", "mode": "always", "enabled": True},
            {"name": "B", "mode": "optional", "enabled": True},
            {"name": "C", "mode": "always", "enabled": False},
            {"name": "D", "enabled": True},  # missing mode → always
        ]}
        assert always_rooms(cfg) == ["A", "D"]

    def test_empty(self):
        assert always_rooms({}) == []


class TestRoomLinkMapAndOpenKey:
    def test_link_map_only_nonempty(self):
        cfg = {"rooms": [
            {"name": "A", "link": "https://open.kakao.com/o/a", "enabled": True},
            {"name": "B", "link": "", "enabled": True},
            {"name": "C", "enabled": True},
        ]}
        assert room_link_map(cfg) == {"A": "https://open.kakao.com/o/a"}

    def test_open_key_prefers_registered_link(self):
        lm = {"공부방": "https://open.kakao.com/o/x"}
        assert open_key_for("공부방", lm) == "https://open.kakao.com/o/x"

    def test_open_key_falls_back_to_name(self):
        assert open_key_for("부동산방", {}) == "부동산방"

    def test_open_key_url_passthrough(self):
        # user passed a link directly as the room → use it as-is
        url = "https://open.kakao.com/o/EXAMPLE"
        assert open_key_for(url, {}) == url


class TestSafeRoomDir:
    def test_clean_name(self):
        assert safe_room_dir("MyRoom") == "MyRoom"

    def test_strips_backslash(self):
        assert "\\" not in safe_room_dir("room\\name")

    def test_strips_slash(self):
        assert "/" not in safe_room_dir("room/name")

    def test_strips_colon(self):
        assert ":" not in safe_room_dir("room:name")

    def test_strips_asterisk(self):
        assert "*" not in safe_room_dir("room*name")

    def test_strips_question_mark(self):
        assert "?" not in safe_room_dir("room?name")

    def test_strips_double_quote(self):
        assert '"' not in safe_room_dir('room"name')

    def test_strips_angle_brackets(self):
        result = safe_room_dir("room<name>")
        assert "<" not in result
        assert ">" not in result

    def test_strips_pipe(self):
        assert "|" not in safe_room_dir("room|name")

    def test_replaces_with_underscore(self):
        assert safe_room_dir("a:b") == "a_b"

    def test_korean_preserved(self):
        result = safe_room_dir("한국어방")
        assert result == "한국어방"

    def test_all_forbidden_chars(self):
        forbidden = r'\/:*?"<>|'
        result = safe_room_dir(forbidden)
        for ch in forbidden:
            assert ch not in result
