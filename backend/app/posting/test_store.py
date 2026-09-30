from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.posting.comment import feedback_id_for
from app.posting.models import PostingRecord
from app.posting.store import PostingStore, PostingStoreError

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def record(review_id="review-1", status="posting", **extra):
    return PostingRecord(feedback_id=feedback_id_for(review_id), review_id=review_id, status=status,
                         recorded_at=NOW, attempt=1, **extra)


def test_records_are_appended_and_the_latest_is_the_state(tmp_path):
    store = PostingStore(tmp_path)
    store.append(record(status="posting"))
    store.append(record(status="posted", basecamp_comment_id=77))
    store.append(record(review_id="review-2", status="failed", reason_code="UpstreamUnavailable"))
    assert [r.status for r in store.history("review-1")] == ["posting", "posted"]
    assert store.latest("review-1").basecamp_comment_id == 77
    assert store.latest("review-2").reason_code == "UpstreamUnavailable"
    assert store.latest("review-3") is None
    assert (tmp_path / "posted.jsonl").read_text().count("\n") == 3


def test_empty_or_missing_file_means_no_history(tmp_path):
    assert PostingStore(tmp_path / "not-yet").history("review-1") == []


def test_a_corrupt_line_is_reported_with_its_number_never_skipped(tmp_path):
    store = PostingStore(tmp_path)
    store.append(record())
    with open(tmp_path / "posted.jsonl", "a") as handle:
        handle.write("{not json\n")
    with pytest.raises(PostingStoreError, match="line 2"):
        store.history("review-1")


def test_an_unwritable_folder_raises_a_store_error(tmp_path):
    blocker = tmp_path / "file-not-folder"
    blocker.write_text("x")
    with pytest.raises(PostingStoreError):
        PostingStore(blocker).append(record())


@pytest.mark.parametrize("bad", [
    {"feedback_id": "FB-XYZ"},
    {"status": "done"},
    {"reason_code": "free text with spaces"},
    {"basecamp_comment_id": 0},
])
def test_record_contract_rejects_bad_values(bad):
    fields = dict(feedback_id=feedback_id_for("r"), review_id="r", status="posted", recorded_at=NOW, attempt=1)
    fields.update(bad)
    with pytest.raises(ValidationError):
        PostingRecord(**fields)


def test_posted_is_final_even_if_a_later_record_says_failed(tmp_path):
    store = PostingStore(tmp_path)
    store.append(record(status="posting"))
    assert store.posted("review-1") is None
    store.append(record(status="posted", basecamp_comment_id=77))
    store.append(record(status="failed", reason_code="POSTING_IN_PROGRESS"))
    assert store.latest("review-1").status == "failed"
    assert store.posted("review-1").basecamp_comment_id == 77
