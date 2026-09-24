"""The process-wide Review Queue store, handed to routes via FastAPI Depends
so tests can override it with a fresh store (app.dependency_overrides)."""
from app.review_queue.store import InMemoryReviewQueueStore, ReviewQueueStore

_store = InMemoryReviewQueueStore()


def get_review_queue_store() -> ReviewQueueStore:
    return _store
