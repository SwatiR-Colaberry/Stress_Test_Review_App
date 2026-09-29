"""STORY-013: the retrieval contract (models) and the in-memory vector index."""
import pytest
from pydantic import ValidationError

from app.history.vector_index import IndexedCase, InMemoryVectorIndex, cosine
from app.models import MAX_HISTORY_CASES, HistoricalCase, HistoryRetrieval, SimilarCase


def case(case_id: str, stress_test_id: str = "ST0") -> HistoricalCase:
    return HistoricalCase(case_id=case_id, stress_test_id=stress_test_id,
                          submission_excerpt=f"submission {case_id}", reviewer_feedback=f"feedback {case_id}")


def similar(case_id: str, stress_test_id: str = "ST0", similarity: float = 0.5) -> SimilarCase:
    return SimilarCase(**case(case_id, stress_test_id).model_dump(), similarity=similarity)


def indexed(case_id: str, vector, stress_test_id: str = "ST0") -> IndexedCase:
    return IndexedCase(case=case(case_id, stress_test_id), vector=list(vector))


# --- HistoryRetrieval: the contract -------------------------------------------

def test_found_with_cases_from_the_same_stress_test():
    result = HistoryRetrieval(stress_test_id="ST0", status="found", cases=[similar("a"), similar("b")],
                              message="2 similar past reviews")
    assert [c.case_id for c in result.cases] == ["a", "b"]


def test_a_case_from_another_stress_test_is_rejected():
    with pytest.raises(ValidationError, match="different Stress Test"):
        HistoryRetrieval(stress_test_id="ST0", status="found", cases=[similar("a"), similar("b", "ST1")],
                         message="x")


def test_none_found_is_an_empty_list_with_a_message():
    result = HistoryRetrieval(stress_test_id="ST2", status="none_found", cases=[],
                              message="No similar past reviews for ST2.")
    assert result.cases == [] and result.error_class is None


def test_unavailable_needs_an_error_class_and_no_cases():
    ok = HistoryRetrieval(stress_test_id="ST0", status="unavailable", cases=[],
                          message="History unavailable", error_class="EmbeddingUnavailable")
    assert ok.error_class == "EmbeddingUnavailable"
    with pytest.raises(ValidationError):
        HistoryRetrieval(stress_test_id="ST0", status="unavailable", cases=[], message="x")
    with pytest.raises(ValidationError):
        HistoryRetrieval(stress_test_id="ST0", status="unavailable", cases=[similar("a")],
                         message="x", error_class="E")


@pytest.mark.parametrize("status,cases", [("found", []), ("none_found", ["a"])])
def test_status_must_match_whether_cases_exist(status, cases):
    with pytest.raises(ValidationError):
        HistoryRetrieval(stress_test_id="ST0", status=status, cases=[similar(c) for c in cases], message="x")


def test_at_most_max_history_cases():
    too_many = [similar(str(i)) for i in range(MAX_HISTORY_CASES + 1)]
    with pytest.raises(ValidationError):
        HistoryRetrieval(stress_test_id="ST0", status="found", cases=too_many, message="x")


@pytest.mark.parametrize("field,value", [("stress_test_id", "ST10"), ("stress_test_id", "st0"),
                                         ("submission_excerpt", ""), ("reviewer_feedback", "x" * 2001),
                                         ("case_id", "x" * 129)])
def test_historical_case_bounds(field, value):
    data = case("a").model_dump() | {field: value}
    with pytest.raises(ValidationError):
        HistoricalCase(**data)


# --- InMemoryVectorIndex -------------------------------------------------------

def test_search_returns_the_most_similar_first():
    index = InMemoryVectorIndex()
    index.upsert([indexed("far", [0, 1]), indexed("near", [1, 0.1]), indexed("mid", [1, 1])])
    assert [c.case_id for c in index.search("ST0", [1, 0], k=3)] == ["near", "mid", "far"]


def test_search_never_returns_another_stress_test_even_when_it_is_closer():
    index = InMemoryVectorIndex()
    index.upsert([indexed("st1-exact", [1, 0], "ST1"), indexed("st0-far", [0, 1], "ST0")])
    result = index.search("ST0", [1, 0], k=10)
    assert [(c.case_id, c.stress_test_id) for c in result] == [("st0-far", "ST0")]


def test_search_returns_at_most_k():
    index = InMemoryVectorIndex()
    index.upsert([indexed(str(i), [1, i]) for i in range(12)])
    assert len(index.search("ST0", [1, 0], k=10)) == 10


def test_search_on_an_empty_stress_test_returns_an_empty_list():
    index = InMemoryVectorIndex()
    index.upsert([indexed("a", [1, 0], "ST1")])
    assert index.search("ST0", [1, 0], k=10) == []


def test_upsert_twice_does_not_duplicate():
    index = InMemoryVectorIndex()
    index.upsert([indexed("a", [1, 0]), indexed("b", [0, 1])])
    index.upsert([indexed("a", [1, 0]), indexed("b", [0, 1])])
    assert index.count("ST0") == 2
    assert len(index.search("ST0", [1, 0], k=10)) == 2


def test_upsert_again_replaces_the_entry():
    index = InMemoryVectorIndex()
    index.upsert([indexed("a", [1, 0])])
    index.upsert([indexed("a", [0, 1])])
    assert index.search("ST0", [0, 1], k=1)[0].similarity == pytest.approx(1.0)


@pytest.mark.parametrize("k", [0, MAX_HISTORY_CASES + 1])
def test_k_out_of_range_is_rejected(k):
    with pytest.raises(ValueError):
        InMemoryVectorIndex().search("ST0", [1, 0], k=k)


def test_cosine_edge_cases():
    assert cosine([1, 0], [2, 0]) == pytest.approx(1.0)
    assert cosine([0, 0], [1, 0]) == 0.0
    with pytest.raises(ValueError):
        cosine([1, 0], [1, 0, 0])
