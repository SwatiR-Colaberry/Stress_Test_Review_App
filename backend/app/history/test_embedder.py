"""STORY-013: the local embedder, with stub models (no download, no network)."""
import threading

import pytest

from app.history.embedder import EmbeddingError, FastEmbedEmbedder


class StubModel:
    def __init__(self, vectors=None, error=None, hang=None):
        self.vectors, self.error, self.hang = vectors, error, hang

    def embed(self, texts):
        if self.hang is not None:
            self.hang.wait(5)
        if self.error:
            raise self.error
        return self.vectors if self.vectors is not None else [[1.0, float(i)] for i, _ in enumerate(texts)]


def embedder(model=None, loader=None, **kw):
    return FastEmbedEmbedder(load_model=loader or (lambda name, cache: model), timeout_s=kw.pop("timeout_s", 1.0),
                             load_timeout_s=1.0, backoff_s=0, **kw)


def test_one_vector_per_text_in_order():
    assert embedder(StubModel()).embed(["a", "b"]) == [[1.0, 0.0], [1.0, 1.0]]


def test_the_model_is_loaded_once():
    loads = []

    def loader(name, cache):
        loads.append(name)
        return StubModel()

    e = embedder(loader=loader)
    e.embed(["a"])
    e.embed(["b"])
    assert loads == ["BAAI/bge-small-en-v1.5"]


def test_no_texts_needs_no_model():
    def loader(name, cache):
        raise AssertionError("must not load")

    assert embedder(loader=loader).embed([]) == []


def test_a_model_that_cannot_load_is_an_embedding_error():
    def loader(name, cache):
        raise OSError("no network for the first download")

    with pytest.raises(EmbeddingError, match="embedding model load failed after 3 attempts: OSError"):
        embedder(loader=loader).embed(["a"])


def test_an_embedding_failure_is_an_embedding_error():
    with pytest.raises(EmbeddingError, match="embedding failed after 3 attempts: RuntimeError"):
        embedder(StubModel(error=RuntimeError("onnx"))).embed(["a"])


def test_a_hanging_model_times_out():
    release = threading.Event()
    with pytest.raises(EmbeddingError, match="timed out"):
        embedder(StubModel(hang=release), timeout_s=0.05, attempts=1).embed(["a"])
    release.set()


@pytest.mark.parametrize("vectors", [[[1.0]], [[1.0], []]])
def test_a_wrong_shaped_answer_is_rejected(vectors):
    with pytest.raises(EmbeddingError):
        embedder(StubModel(vectors=vectors)).embed(["a", "b"])
