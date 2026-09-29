"""STORY-013: the LanceDB vector index, on a temporary folder."""
import pytest

from app.history.lancedb_index import LanceDbVectorIndex
from app.history.vector_index import IndexedCase, VectorIndexError
from app.models import HistoricalCase


def indexed(case_id, vector, stress_test_id="ST0"):
    return IndexedCase(case=HistoricalCase(case_id=case_id, stress_test_id=stress_test_id,
                                           submission_excerpt=f"s {case_id}", reviewer_feedback=f"f {case_id}"),
                       vector=list(vector))


@pytest.fixture
def index(tmp_path):
    return LanceDbVectorIndex(tmp_path / "vector_index", backoff_s=0)


def test_most_similar_first_same_stress_test_only(index):
    index.upsert([indexed("st1-exact", [1, 0], "ST1"), indexed("near", [1, 0.1]),
                  indexed("mid", [1, 1]), indexed("far", [0, 1])])
    result = index.search("ST0", [1, 0], k=10)
    assert [c.case_id for c in result] == ["near", "mid", "far"]
    assert {c.stress_test_id for c in result} == {"ST0"}
    assert result[0].similarity == pytest.approx(0.995, abs=0.001)


def test_top_k_only(index):
    index.upsert([indexed(f"c{i:02d}", [1, i / 10]) for i in range(12)])
    assert [c.case_id for c in index.search("ST0", [1, 0], k=10)] == [f"c{i:02d}" for i in range(10)]


def test_indexing_twice_does_not_duplicate(index):
    entries = [indexed("a", [1, 0]), indexed("b", [0, 1])]
    index.upsert(entries)
    index.upsert(entries)
    assert index.count("ST0") == 2


def test_indexing_again_replaces_the_row(index):
    index.upsert([indexed("a", [1, 0])])
    index.upsert([indexed("a", [0, 1])])
    assert index.count("ST0") == 1
    assert index.search("ST0", [0, 1], k=1)[0].similarity == pytest.approx(1.0)


def test_a_stress_test_with_no_cases_returns_an_empty_list(index):
    index.upsert([indexed("a", [1, 0], "ST1")])
    assert index.search("ST0", [1, 0], k=10) == []
    assert index.count("ST0") == 0


def test_the_index_survives_a_reopen(tmp_path):
    LanceDbVectorIndex(tmp_path / "vi").upsert([indexed("a", [1, 0])])
    assert LanceDbVectorIndex(tmp_path / "vi").count("ST0") == 1


def test_an_unbuilt_index_is_reported_not_treated_as_empty(index):
    with pytest.raises(VectorIndexError, match="has not been built") as raised:
        index.search("ST0", [1, 0], k=10)
    assert "/" not in str(raised.value)  # no server path in what the reviewer sees


def test_a_wrong_vector_size_is_a_vector_index_error(index):
    index.upsert([indexed("a", [1, 0])])
    with pytest.raises(VectorIndexError, match="failed after 3 attempts"):
        index.search("ST0", [1, 0, 0], k=10)


def test_an_unreadable_location_is_a_vector_index_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    with pytest.raises(VectorIndexError):
        LanceDbVectorIndex(blocker / "vi", backoff_s=0).upsert([indexed("a", [1, 0])])


@pytest.mark.parametrize("bad", ["ST0' OR '1'='1", "ST10", ""])
def test_the_filter_accepts_only_a_stress_test_id(index, bad):
    with pytest.raises(ValueError):
        index.search(bad, [1, 0], k=10)


def test_a_malformed_stored_row_is_a_vector_index_error(index, monkeypatch):
    index.upsert([indexed("a", [1, 0])])
    monkeypatch.setattr(index, "_bounded", lambda fn, what: [{"case_id": "a", "_distance": 0.1}])
    with pytest.raises(VectorIndexError, match="malformed row: KeyError"):
        index.search("ST0", [1, 0], k=10)
