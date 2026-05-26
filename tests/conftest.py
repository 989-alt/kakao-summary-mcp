"""Shared pytest fixtures for offline test suite."""
from __future__ import annotations

import hashlib

import pytest


# ---------------------------------------------------------------------------
# Sample KakaoTalk export text (realistic format the regexes expect)
# ---------------------------------------------------------------------------

SAMPLE_TXT = """\
--------------- 2026년 5월 26일 화요일 ---------------
[홍길동] [오전 9:15] 안녕하세요
[홍길동] [오전 9:16] 오늘 회의 몇 시예요?
[김철수] [오전 9:17] 10시입니다
[김철수] [오전 9:18] 회의실 A에서 만나요
이 줄은 연속 메시지입니다
[홍길동] [오전 12:00] 알겠습니다
[홍길동] [오후 12:00] 점심 먹고 올게요
[홍길동] [오후 1:30] 회의 끝났습니다
--------------- 2026년 5월 27일 수요일 ---------------
[홍길동] [오전 8:00] 좋은 아침입니다
[김철수] [오후 11:59] 야근 중...
"""


@pytest.fixture
def sample_txt(tmp_path) -> "pathlib.Path":
    """Write the sample KakaoTalk export to a temp file and return the path."""
    import pathlib
    p = tmp_path / "sample_chat.txt"
    p.write_text(SAMPLE_TXT, encoding="utf-8-sig")
    return p


# ---------------------------------------------------------------------------
# Fake embedder — deterministic, fixed-dimension (8-dim), no model download
# ---------------------------------------------------------------------------

_EMB_DIM = 8


def _fake_embed_one(text: str) -> list[float]:
    """Hash-based deterministic 8-dim unit vector from text."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [(b - 128) / 128.0 for b in digest[:_EMB_DIM]]
    norm = sum(v * v for v in raw) ** 0.5 or 1.0
    return [v / norm for v in raw]


def fake_embed(texts: list[str], **_kwargs) -> list[list[float]]:
    """Drop-in replacement for kakao_summary_mcp.indexer.embedder.embed."""
    return [_fake_embed_one(t) for t in texts]
