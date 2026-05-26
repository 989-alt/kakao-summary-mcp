"""Tests for kakao_summary_mcp.common (pure logic, fully offline)."""
from __future__ import annotations

import datetime as dt

import pytest

from kakao_summary_mcp.common import enabled_rooms, resolve_date, safe_room_dir


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
