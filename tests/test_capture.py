"""Tests for the hybrid extraction orchestrator (capture.py).

UI automation itself can't run headless, so we verify the *orchestration*:
tier ordering, fallback on failure, aggregated error message, and that the
foreground-grab tier always restores the previous foreground window — even
when extraction raises.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kakao_summary_mcp.extractor import capture


class TestOrchestration:
    def test_first_tier_success_skips_rest(self, tmp_path):
        calls = []

        def t1():
            calls.append("t1")
            return tmp_path / "out.txt"

        def t2():
            calls.append("t2")
            raise AssertionError("should not run")

        result = capture.export_current_room_chat(
            "방", tmp_path / "out.txt", tmp_path, tmp_path,
            tiers=[("t1", t1), ("t2", t2)],
        )
        assert calls == ["t1"]
        assert result == tmp_path / "out.txt"

    def test_falls_through_to_second_tier(self, tmp_path):
        calls = []

        def t1():
            calls.append("t1")
            raise RuntimeError("백그라운드 실패")

        def t2():
            calls.append("t2")
            return tmp_path / "out.txt"

        result = capture.export_current_room_chat(
            "방", tmp_path / "out.txt", tmp_path, tmp_path,
            tiers=[("UIA(백그라운드)", t1), ("포그라운드-그랩", t2)],
        )
        assert calls == ["t1", "t2"]
        assert result == tmp_path / "out.txt"

    def test_all_fail_raises_with_all_reasons(self, tmp_path):
        def t1():
            raise RuntimeError("백그라운드 사유")

        def t2():
            raise RuntimeError("포그라운드 사유")

        with pytest.raises(RuntimeError) as ei:
            capture.export_current_room_chat(
                "방", tmp_path / "out.txt", tmp_path, tmp_path,
                tiers=[("UIA(백그라운드)", t1), ("포그라운드-그랩", t2)],
            )
        msg = str(ei.value)
        assert "백그라운드 사유" in msg
        assert "포그라운드 사유" in msg


class TestForegroundGrabRestoresFocus:
    def _patch_window(self, monkeypatch, recorder):
        import kakao_summary_mcp.extractor.window as window

        monkeypatch.setattr(window, "remember_foreground", lambda: 12345)
        monkeypatch.setattr(window, "restore_foreground",
                            lambda hwnd: recorder.append(("restore", hwnd)))
        monkeypatch.setattr(window, "focus_main_window",
                            lambda: recorder.append(("focus", None)))
        monkeypatch.setattr(window, "search_and_open_room",
                            lambda room: recorder.append(("open", room)))

    def test_restores_on_success(self, tmp_path, monkeypatch):
        rec = []
        self._patch_window(monkeypatch, rec)
        monkeypatch.setattr(capture, "export_via_shortcut",
                            lambda *a, **k: tmp_path / "out.txt")

        result = capture._tier_foreground_grab("방", tmp_path / "out.txt",
                                               tmp_path, 5.0)
        assert result == tmp_path / "out.txt"
        assert ("restore", 12345) in rec

    def test_restores_even_when_extraction_fails(self, tmp_path, monkeypatch):
        rec = []
        self._patch_window(monkeypatch, rec)

        def boom(*a, **k):
            raise RuntimeError("export 실패")

        monkeypatch.setattr(capture, "export_via_shortcut", boom)
        monkeypatch.setattr(capture, "export_via_uia", boom)

        with pytest.raises(RuntimeError):
            capture._tier_foreground_grab("방", tmp_path / "out.txt",
                                          tmp_path, 5.0)
        # focus must have been restored despite the failure
        assert ("restore", 12345) in rec

    def test_shortcut_failure_falls_back_to_click_input_uia(self, tmp_path, monkeypatch):
        rec = []
        self._patch_window(monkeypatch, rec)

        def shortcut_boom(*a, **k):
            raise RuntimeError("단축키 실패")

        monkeypatch.setattr(capture, "export_via_shortcut", shortcut_boom)
        monkeypatch.setattr(capture, "export_via_uia",
                            lambda *a, **k: tmp_path / "out.txt")

        result = capture._tier_foreground_grab("방", tmp_path / "out.txt",
                                               tmp_path, 5.0)
        assert result == tmp_path / "out.txt"
        assert ("restore", 12345) in rec


def test_default_tiers_are_background_first(tmp_path, monkeypatch):
    """Default tier order: background → foreground-grab → template."""
    order = []

    def bg(*a, **k):
        order.append("bg")
        raise RuntimeError("bg fail")

    def fg(*a, **k):
        order.append("fg")
        raise RuntimeError("fg fail")

    def tpl(*a, **k):
        order.append("tpl")
        return tmp_path / "out.txt"

    monkeypatch.setattr(capture, "_tier_background", bg)
    monkeypatch.setattr(capture, "_tier_foreground_grab", fg)
    monkeypatch.setattr(capture, "_tier_template", tpl)

    result = capture.export_current_room_chat(
        "방", tmp_path / "out.txt", tmp_path, tmp_path,
    )
    assert order == ["bg", "fg", "tpl"]
    assert result == tmp_path / "out.txt"
