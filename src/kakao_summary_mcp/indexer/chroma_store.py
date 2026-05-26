"""ChromaDB PersistentClient 래퍼. 단일 컬렉션 + room 메타필터."""
from __future__ import annotations

from pathlib import Path

from ..parser.schema import Turn
from .embedder import embed

COLLECTION_NAME = "kakao_turns"


def get_client(chroma_path: Path):
    import chromadb
    chroma_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(chroma_path))


def get_collection(chroma_path: Path):
    client = get_client(chroma_path)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_turns(chroma_path: Path, turns: list[Turn],
                 model_name: str = "BAAI/bge-m3", device: str = "cpu") -> int:
    if not turns:
        return 0
    col = get_collection(chroma_path)
    ids = [t.turn_id for t in turns]
    docs = [t.text for t in turns]
    metas = [{
        "room": t.room,
        "date": t.date,
        "date_int": int(t.date.replace("-", "")),
        "sender": t.sender,
        "ts_start": t.ts_start,
        "ts_epoch": t.ts_epoch,
        "msg_ids": ",".join(t.msg_ids),
    } for t in turns]
    embeddings = embed(docs, model_name=model_name, device=device)
    col.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
    return len(turns)


def search(chroma_path: Path, query: str, where: dict | None = None,
           top_k: int = 15, model_name: str = "BAAI/bge-m3",
           device: str = "cpu") -> list[dict]:
    col = get_collection(chroma_path)
    q_emb = embed([query], model_name=model_name, device=device)
    # Caller (retriever.semantic_query) owns where-clause validity: it passes
    # either None or a ChromaDB-valid dict ($and-wrapped when multi-filter).
    res = col.query(query_embeddings=q_emb, n_results=top_k, where=where)
    out = []
    for i in range(len(res["ids"][0])):
        out.append({
            "turn_id": res["ids"][0][i],
            "text": res["documents"][0][i],
            "metadata": res["metadatas"][0][i],
            "distance": res["distances"][0][i] if "distances" in res else None,
        })
    return out


def get_turns_by_ids(chroma_path: Path, turn_ids: list[str]) -> list[dict]:
    if not turn_ids:
        return []
    col = get_collection(chroma_path)
    res = col.get(ids=turn_ids)
    out = []
    for i in range(len(res["ids"])):
        out.append({
            "turn_id": res["ids"][i],
            "text": res["documents"][i],
            "metadata": res["metadatas"][i],
        })
    out.sort(key=lambda x: x["metadata"].get("ts_epoch", 0))
    return out
