"""Find the AI draft a reviewer is working on (STORY-005): review_id ->
Review Queue item (REQ-002) -> the evaluation of that exact comment version
(STORY-004's results file).

If a comment was evaluated under more than one rule version, the newest
version (highest vN) is the draft. Reads the evaluation results with the
same validated reader the ResultStore uses; nothing is written.

Failure modes: unknown review -> None; review with no evaluation yet ->
ReviewDraft with evaluation None (the caller says "no AI draft yet");
unreadable or corrupt results file -> EvaluationStoreError.
"""
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel

from app.evaluation.store import DEFAULT_DIR as EVALUATION_DIR
from app.evaluation.store import read_lines
from app.models import DraftFinding, EvaluationResult, ReviewItem
from app.review_queue.store import ReviewQueueStore


class ReviewDraft(BaseModel):
    item: ReviewItem
    evaluation: Optional[EvaluationResult] = None

    @property
    def findings(self) -> List[DraftFinding]:
        return self.evaluation.findings if self.evaluation else []


class DraftSource:
    def __init__(self, queue: ReviewQueueStore, evaluation_dir: Path = EVALUATION_DIR) -> None:
        self._queue = queue
        self._results = Path(evaluation_dir) / "results.jsonl"

    def get(self, review_id: str) -> Optional[ReviewDraft]:
        item = next((i for i in self._queue.list_items() if i.review_id == review_id), None)
        if item is None:
            return None
        versions = [r for r in read_lines(self._results, EvaluationResult) if r.comment_id == item.comment_id]
        newest = max(versions, key=lambda r: int(r.rule_version[1:]), default=None)
        return ReviewDraft(item=item, evaluation=newest)
