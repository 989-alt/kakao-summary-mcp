"""bge-m3 임베딩 래퍼. 최초 호출 시 ~2GB 다운로드."""
from __future__ import annotations

import sys

_model = None
_model_key: tuple[str, str] | None = None


def get_model(model_name: str = "BAAI/bge-m3", device: str = "cpu"):
    global _model, _model_key
    key = (model_name, device)
    if _model is not None and _model_key == key:
        return _model
    print(f"[embedder] loading {model_name} on {device} (최초 1회 다운로드 ~2GB)",
          file=sys.stderr, flush=True)
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer(model_name, device=device)
    _model_key = key
    print(f"[embedder] model ready", file=sys.stderr, flush=True)
    return _model


def embed(texts: list[str], model_name: str = "BAAI/bge-m3", device: str = "cpu"):
    m = get_model(model_name, device)
    return m.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()
