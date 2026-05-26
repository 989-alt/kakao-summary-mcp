"""자유 질의 및 turn_ids 기반 조회."""
from __future__ import annotations

import json
from pathlib import Path

from ..indexer import chroma_store


def load_session(session_path: Path) -> dict:
    with open(session_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_session(session_path: Path, session: dict) -> None:
    session_path.parent.mkdir(parents=True, exist_ok=True)
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)


def turns_by_ids(chroma_path: Path, turn_ids: list[str]) -> list[dict]:
    return chroma_store.get_turns_by_ids(chroma_path, turn_ids)


def semantic_query(chroma_path: Path, query: str,
                   room: str | None = None, date: str | None = None,
                   top_k: int = 15,
                   model_name: str = "BAAI/bge-m3", device: str = "cpu") -> list[dict]:
    clauses: list[dict] = []
    if room:
        clauses.append({"room": {"$eq": room}})
    if date:
        clauses.append({"date": {"$eq": date}})

    if len(clauses) == 0:
        where: dict | None = None
    elif len(clauses) == 1:
        where = clauses[0]
    else:
        where = {"$and": clauses}

    return chroma_store.search(
        chroma_path, query, where=where, top_k=top_k,
        model_name=model_name, device=device,
    )


def format_turns(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        m = t["metadata"]
        lines.append(f"[{m.get('room','?')} {m.get('date','?')} {m.get('ts_start','?')}] "
                     f"{m.get('sender','?')}: {t['text']}")
    return "\n\n".join(lines)
