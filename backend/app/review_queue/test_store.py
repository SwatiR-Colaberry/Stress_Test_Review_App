from datetime import datetime, timezone
from itertools import count

from app.models import BasecampComment
from app.review_queue.store import InMemoryReviewQueueStore

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _store():
    ids = count(1)
    return InMemoryReviewQueueStore(clock=lambda: _NOW, new_id=lambda: f"review-{next(ids)}")


def _comment(comment_id=1001, message_id=500):
    return BasecampComment(comment_id=comment_id, message_id=message_id, body="##Critique##", created_at=_NOW)


def test_creates_a_pending_item_tied_to_the_exact_comment_version():
    item, created = _store().create_pending(_comment())
    assert created is True
    assert item.status == "Pending"
    assert (item.comment_id, item.message_id) == (1001, 500)


def test_processing_the_same_comment_twice_creates_only_one_item():
    store = _store()
    first, first_created = store.create_pending(_comment())
    second, second_created = store.create_pending(_comment())
    assert (first_created, second_created) == (True, False)
    assert second.review_id == first.review_id
    assert len(store.list_items()) == 1


def test_a_new_version_on_the_same_thread_gets_its_own_review_and_keeps_the_old_one():
    store = _store()
    v1, _ = store.create_pending(_comment(comment_id=1001))
    v2, _ = store.create_pending(_comment(comment_id=1002))
    assert v1.review_id != v2.review_id
    assert [i.comment_id for i in store.list_items()] == [1001, 1002]
    assert store.get_by_comment_id(1001) == v1


def test_an_empty_store_lists_nothing():
    store = _store()
    assert store.list_items() == []
    assert store.get_by_comment_id(1001) is None
