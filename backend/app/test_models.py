from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import BasecampComment, ReviewItem

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _comment(**overrides):
    fields = {"comment_id": 1001, "message_id": 500, "body": "##Critique##", "created_at": _NOW}
    fields.update(overrides)
    return fields


def test_a_well_formed_comment_parses():
    comment = BasecampComment(**_comment())
    assert comment.comment_id == 1001
    assert comment.message_id == 500


@pytest.mark.parametrize(
    "overrides",
    [
        {"comment_id": None},
        {"comment_id": 0},
        {"comment_id": -5},
        {"comment_id": "not-a-number"},
        {"comment_id": True},
        {"comment_id": "1001"},
        {"comment_id": 1001.0},
        {"message_id": None},
        {"body": None},
        {"created_at": "yesterday-ish"},
    ],
)
def test_malformed_comment_data_is_rejected(overrides):
    with pytest.raises(ValidationError):
        BasecampComment(**_comment(**overrides))


def test_a_comment_missing_its_id_entirely_is_rejected():
    fields = _comment()
    del fields["comment_id"]
    with pytest.raises(ValidationError):
        BasecampComment(**fields)


def test_a_new_review_item_defaults_to_pending():
    item = ReviewItem(review_id="r-1", comment_id=1001, message_id=500, created_at=_NOW)
    assert item.status == "Pending"


def test_a_review_item_rejects_a_status_outside_the_spec():
    with pytest.raises(ValidationError):
        ReviewItem(review_id="r-1", comment_id=1001, message_id=500, created_at=_NOW, status="Approved")
