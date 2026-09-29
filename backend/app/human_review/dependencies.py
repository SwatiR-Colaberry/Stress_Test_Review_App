"""Process-wide reviewer stores, handed to routes via FastAPI Depends so tests
can override them (app.dependency_overrides) instead of writing to data/.

REVIEWS_DIR and EVALUATIONS_DIR override the folders; unset, they are the
git-ignored data/reviews/ and data/evaluations/ at the repo root.
"""
import os
from pathlib import Path

from fastapi import Depends

from app.evaluation.store import DEFAULT_DIR as EVALUATION_DIR
from app.human_review.drafts import DraftSource
from app.human_review.store import DEFAULT_DIR as REVIEWS_DIR
from app.human_review.store import ReviewActionStore
from app.review_queue.dependencies import get_review_queue_store
from app.review_queue.store import ReviewQueueStore

_store = ReviewActionStore(Path(os.environ.get("REVIEWS_DIR") or REVIEWS_DIR))
_evaluations = Path(os.environ.get("EVALUATIONS_DIR") or EVALUATION_DIR)


def get_review_action_store() -> ReviewActionStore:
    return _store


def get_draft_source(queue: ReviewQueueStore = Depends(get_review_queue_store)) -> DraftSource:
    return DraftSource(queue, _evaluations)
