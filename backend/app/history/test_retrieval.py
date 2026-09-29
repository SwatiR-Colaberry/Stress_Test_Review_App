"""STORY-013 acceptance, at the service level: found / same Stress Test only /
unavailable / none found. In-memory index and a stub embedder: no model, no disk."""
import json
import logging

import pytest

from app.history.config import HistoryConfigError, load_history_config
from app.history.embedder import Embedder, EmbeddingError
from app.history.retrieval import retrieve_similar_cases
from app.history.vector_index import IndexedCase, InMemoryVectorIndex, VectorIndex, VectorIndexError
from app.models import HistoricalCase, SimilarCase

SECRET_STUDENT_TEXT = "my private submission about hospital readmissions"


class StubEmbedder(Embedder):
    def __init__(self, vector=(1.0, 0.0), error=None):
        self.vector, self.error = list(vector), error

    def embed(self, texts):
        if self.error:
            raise self.error
        return [self.vector for _ in texts]


class BrokenIndex(VectorIndex):
    def __init__(self, error=None, returns=None):
        self.error, self.returns = error, returns or []

    def upsert(self, entries):
        raise AssertionError("not used")

    def search(self, stress_test_id, vector, k):
        if self.error:
            raise self.error
        return self.returns

    def count(self, stress_test_id):
        return 0


def indexed(case_id, vector, stress_test_id="ST0"):
    return IndexedCase(case=HistoricalCase(case_id=case_id, stress_test_id=stress_test_id,
                                           submission_excerpt=f"s {case_id}", reviewer_feedback=f"f {case_id}"),
                       vector=list(vector))


@pytest.fixture
def index():
    idx = InMemoryVectorIndex()
    # 12 ST0 cases at decreasing similarity to (1, 0), plus closer ST1/ST2 decoys.
    idx.upsert([indexed(f"st0-{i:02d}", [1, i / 10]) for i in range(12)])
    idx.upsert([indexed("st1-exact", [1, 0], "ST1"), indexed("st2-exact", [1, 0], "ST2")])
    return idx


def retrieve(stress_test_id="ST0", text="a submission", index=None, embedder=None, k=10):
    return retrieve_similar_cases(stress_test_id, text, index=index or InMemoryVectorIndex(),
                                  embedder=embedder or StubEmbedder(), k=k, correlation_id="corr-1")


# Criterion 1: top k most similar, same Stress Test.
def test_found_returns_the_top_k_most_similar(index):
    result = retrieve(index=index)
    assert result.status == "found"
    assert [c.case_id for c in result.cases] == [f"st0-{i:02d}" for i in range(10)]
    assert result.cases[0].similarity >= result.cases[-1].similarity
    assert "examples only" in result.message and "ST0 rules decide" in result.message


# Criterion 2: never another Stress Test, even when it is the exact match.
@pytest.mark.parametrize("stress_test_id", ["ST0", "ST1", "ST2"])
def test_only_the_same_stress_test_is_returned(index, stress_test_id):
    result = retrieve(stress_test_id, index=index)
    assert {c.stress_test_id for c in result.cases} == {stress_test_id}


def test_an_index_that_leaks_another_stress_test_is_reported_not_used():
    leaked = SimilarCase(case_id="x", stress_test_id="ST3", submission_excerpt="s", reviewer_feedback="f",
                         similarity=0.9)
    result = retrieve(index=BrokenIndex(returns=[leaked]))
    assert result.status == "unavailable" and result.cases == []
    assert result.error_class == "ContractViolation" and "ST3" in result.message


# Criterion 3: vector database or embedding service unavailable -> review continues, error visible.
@pytest.mark.parametrize("embedder,index,error_class", [
    (StubEmbedder(error=EmbeddingError("embedding failed after 3 attempts: OSError")), None, "EmbeddingUnavailable"),
    (None, BrokenIndex(error=VectorIndexError("vector index search failed after 3 attempts: timed out after 10s")),
     "VectorIndexUnavailable"),
    (None, BrokenIndex(error=VectorIndexError("the vector index has not been built yet (data/vector_index)")),
     "VectorIndexUnavailable"),
])
def test_unavailable_returns_empty_with_a_visible_error(embedder, index, error_class):
    result = retrieve(embedder=embedder, index=index)
    assert result.status == "unavailable" and result.cases == []
    assert result.error_class == error_class
    assert result.message.startswith("Historical examples are unavailable (")
    assert result.message.endswith("this review continues without them.")


def test_a_long_cause_is_shortened_to_fit_the_message():
    result = retrieve(index=BrokenIndex(error=VectorIndexError("x" * 1000)))
    assert len(result.message) <= 300 and result.message.endswith("continue" "s without them.")


# Criterion 4: nothing similar -> empty list and says so.
def test_nothing_indexed_for_the_stress_test_is_an_empty_list_that_says_so(index):
    result = retrieve("ST5", index=index)
    assert result.status == "none_found" and result.cases == [] and result.error_class is None
    assert "No similar past reviews" in result.message and "ST5" in result.message


def test_blank_submission_text_is_none_found_without_calling_the_model():
    result = retrieve(text="   ", embedder=StubEmbedder(error=AssertionError("must not embed")))
    assert result.status == "none_found"


def test_a_bad_k_is_a_programming_error_not_an_outage():
    with pytest.raises(ValueError):
        retrieve(k=0)


def test_same_input_same_result(index):
    assert retrieve(index=index) == retrieve(index=index)


# Observability: one line per retrieval, never the student's text.
def test_one_log_line_without_student_text(index, caplog):
    caplog.set_level(logging.INFO, logger="stress_test_review.history")
    retrieve(text=SECRET_STUDENT_TEXT, index=index)
    retrieve(text=SECRET_STUDENT_TEXT, embedder=StubEmbedder(error=EmbeddingError("down")))
    lines = [json.loads(r.getMessage()) for r in caplog.records]
    assert [(l["outcome"], l["context"]["status"]) for l in lines] == [("success", "found"),
                                                                       ("failure", "unavailable")]
    assert lines[1]["error_class"] == "EmbeddingUnavailable" and lines[0]["correlation_id"] == "corr-1"
    assert all(SECRET_STUDENT_TEXT not in r.getMessage() for r in caplog.records)


# Settings.
def test_default_top_k_is_10():
    assert load_history_config({}).top_k == 10


@pytest.mark.parametrize("value,expected", [("5", 5), ("15", 15), (" 7 ", 7)])
def test_top_k_can_be_set(value, expected):
    assert load_history_config({"HISTORY_TOP_K": value}).top_k == expected


@pytest.mark.parametrize("value", ["0", "16", "ten", "-1", "2.5"])
def test_a_bad_top_k_names_the_variable(value):
    with pytest.raises(HistoryConfigError, match="HISTORY_TOP_K"):
        load_history_config({"HISTORY_TOP_K": value})
