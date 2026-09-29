"""Text embeddings for historical retrieval (STORY-013).

FastEmbedEmbedder runs a small model locally (fastembed, ONNX), so student
text never leaves this machine and no key or paid service is involved. The
model is downloaded once, on first use, into a cache outside the repo; that
download is its only network call.

Failure modes, all raised as EmbeddingError (the caller reports history as
'unavailable' and the review goes on without it):
- the model cannot be downloaded or loaded (no network on first use, corrupt
  cache) -> load is retried, bounded by load_timeout_s x attempts;
- embedding hangs or errors -> bounded by timeout_s x attempts;
- the model returns the wrong number of vectors or empty ones.
"""
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

from app.history.bounded import bounded_call

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"  # 384 dimensions, ~67 MB
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "stress-test-review" / "fastembed"
MAX_ATTEMPTS = 3


class EmbeddingError(Exception):
    error_class = "EmbeddingUnavailable"


class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        """One vector per text, in the same order."""


def _load_fastembed(model_name: str, cache_dir: str) -> Any:
    from fastembed import TextEmbedding  # imported here: heavy, and not needed by tests

    return TextEmbedding(model_name, cache_dir=cache_dir)


class FastEmbedEmbedder(Embedder):
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        timeout_s: float = 30.0,
        load_timeout_s: float = 120.0,  # the first use downloads the model
        attempts: int = MAX_ATTEMPTS,
        backoff_s: float = 0.5,
        load_model: Optional[Callable[[str, str], Any]] = None,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._timeout_s = timeout_s
        self._load_timeout_s = load_timeout_s
        self._attempts = attempts
        self._backoff_s = backoff_s
        self._load_model = load_model or _load_fastembed
        self._model: Any = None
        self._lock = threading.Lock()

    def _model_or_load(self) -> Any:
        with self._lock:
            if self._model is None:
                self._model = bounded_call(
                    lambda: self._load_model(self._model_name, str(self._cache_dir)),
                    what="embedding model load", error=EmbeddingError,
                    timeout_s=self._load_timeout_s, attempts=self._attempts, backoff_s=self._backoff_s,
                )
            return self._model

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        model = self._model_or_load()
        vectors = bounded_call(
            lambda: [[float(x) for x in vector] for vector in model.embed(list(texts))],
            what="embedding", error=EmbeddingError,
            timeout_s=self._timeout_s, attempts=self._attempts, backoff_s=self._backoff_s,
        )
        if len(vectors) != len(texts) or any(not vector for vector in vectors):
            raise EmbeddingError(f"embedding returned {len(vectors)} vectors for {len(texts)} texts")
        return vectors
