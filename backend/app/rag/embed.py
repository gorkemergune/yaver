"""Local text embeddings (fastembed, ONNX on the CPU): no API key, nothing leaves the
machine. The multilingual model puts Turkish and English text in the same space, so a
Turkish question finds English slides. The model (~220 MB) is downloaded on first use
into MODEL_CACHE_DIR."""

import asyncio
import threading
from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from app.config import get_settings
from app.db.models.materials import EMBEDDING_DIM

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Embedder(Protocol):
    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class FastEmbedder:
    dim = EMBEDDING_DIM

    def __init__(self, model: str, cache_dir: str) -> None:
        self.model_name = model
        self.cache_dir = cache_dir
        self._model: object | None = None
        self._lock = threading.Lock()

    def _load(self) -> object:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(self.model_name, cache_dir=self.cache_dir)
            return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.embed(list(texts), batch_size=32)  # type: ignore[attr-defined]
        return [[float(x) for x in vector] for vector in vectors]


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    return FastEmbedder(settings.embedding_model, str(settings.model_cache_dir))


async def embed(texts: Sequence[str], embedder: Embedder | None = None) -> list[list[float]]:
    """Off the event loop: a few hundred passages take seconds on a CPU."""
    if not texts:
        return []
    return await asyncio.to_thread((embedder or get_embedder()).embed, texts)
