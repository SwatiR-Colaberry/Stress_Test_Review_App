"""Reviewer action log (STORY-005): where a reviewer's approvals, edits,
rejections and added findings are saved. SQL Server is not used: it stays
read-only (user rule, 2026-09-25).

Files (git-ignored: edits quote student work), both append-only:
  actions.jsonl   one RecordedAction per line
  prepared.jsonl  one PreparedFeedback per review, written once With the AI draft (kept in the
evaluation ResultStore) it is the whole history of a review (REQ-008).

record() order: identity check -> replay check -> validate against the
current state -> append -> return the new state. Nothing is appended for a
refused action, and the state is returned only after the line is on disk.

Idempotency: action_id is the key. The same action_id with the same content
returns the current state and appends nothing; with different content it is
refused (ACTION_ID_REUSED), since a key must not mean two actions.
prepare() saves feedback once per review; calling it again returns the saved
one. Once prepared, the review is locked: a new action is refused
(REVIEW_LOCKED) so the posted feedback always matches the saved review. Two
processes racing on one key can both append; build_state() applies it once.

Failure modes: file cannot be written or read -> ReviewStoreError (the caller
reports "not saved"); corrupt line -> ReviewStoreError naming the line, never
skipped; AI or blank reviewer identity, unknown finding, reused key ->
InvalidReviewerAction with a reason code.
"""
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Type, TypeVar

from app.evaluation.store import EvaluationStoreError, append_line, read_lines
from app.guardrails.review_finalization_guardrail import AI_ACTOR_IDS
from app.human_review.models import PreparedFeedback, RecordedAction, ReviewerAction, ReviewState
from app.human_review.prepare import build_prepared
from app.human_review.state import InvalidReviewerAction, apply_one, build_state
from app.models import DraftFinding

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data" / "reviews"

M = TypeVar("M", RecordedAction, PreparedFeedback)


class ReviewStoreError(Exception):
    error_class = "ReviewStoreError"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReviewActionStore:
    def __init__(self, directory: Path = DEFAULT_DIR, clock: Callable[[], datetime] = _utc_now) -> None:
        self._path = Path(directory) / "actions.jsonl"
        self._prepared_path = Path(directory) / "prepared.jsonl"
        self._lock = threading.Lock()
        self._clock = clock

    def history(self, review_id: str) -> List[RecordedAction]:
        with self._lock:
            return self._read(review_id)

    def state(self, review_id: str, draft: List[DraftFinding]) -> ReviewState:
        return build_state(review_id, draft, self.history(review_id))

    def record(self, review_id: str, reviewer_id: str, action: ReviewerAction,
               draft: List[DraftFinding]) -> ReviewState:
        reviewer_id = _check_reviewer(reviewer_id)
        with self._lock:
            log = self._read(review_id)
            for earlier in log:
                if earlier.action.action_id == action.action_id:
                    if earlier.action != action:
                        raise InvalidReviewerAction(
                            "ACTION_ID_REUSED", f"action {action.action_id} was already used for a different action"
                        )
                    return build_state(review_id, draft, log)
            if self._prepared(review_id) is not None:
                raise InvalidReviewerAction(
                    "REVIEW_LOCKED", f"review {review_id} feedback is already prepared; it can no longer change"
                )
            entry = RecordedAction(review_id=review_id, reviewer_id=reviewer_id,
                                   recorded_at=self._clock(), action=action)
            current = build_state(review_id, draft, log)
            apply_one({f.finding_id: f for f in current.findings}, entry)  # raises if invalid
            try:
                append_line(self._path, entry.model_dump_json())
            except EvaluationStoreError as exc:
                raise ReviewStoreError(f"reviewer action not saved: {exc}") from exc
            return build_state(review_id, draft, log + [entry])

    def prepared(self, review_id: str) -> Optional[PreparedFeedback]:
        with self._lock:
            return self._prepared(review_id)

    def prepare(self, review_id: str, reviewer_id: str, draft: List[DraftFinding]) -> PreparedFeedback:
        """Save the final feedback for posting, once. Raises InvalidReviewerAction
        (nothing saved) or ReviewStoreError (not saved)."""
        reviewer_id = _check_reviewer(reviewer_id)
        with self._lock:
            existing = self._prepared(review_id)
            if existing is not None:
                return existing
            state = build_state(review_id, draft, self._read(review_id))
            prepared = build_prepared(state, reviewer_id, self._clock())
            try:
                append_line(self._prepared_path, prepared.model_dump_json())
            except EvaluationStoreError as exc:
                raise ReviewStoreError(f"prepared feedback not saved: {exc}") from exc
            return prepared

    def _read(self, review_id: str) -> List[RecordedAction]:
        return self._load(self._path, RecordedAction, review_id)

    def _prepared(self, review_id: str) -> Optional[PreparedFeedback]:
        found = self._load(self._prepared_path, PreparedFeedback, review_id)
        return found[0] if found else None  # first write wins

    @staticmethod
    def _load(path: Path, model: Type[M], review_id: str) -> List[M]:
        try:
            records = read_lines(path, model)
        except EvaluationStoreError as exc:
            raise ReviewStoreError(str(exc)) from exc
        return [r for r in records if r.review_id == review_id]


def _check_reviewer(reviewer_id: str) -> str:
    """Only a named human may act on a review: no auto-approval (REQ-011)."""
    cleaned = (reviewer_id or "").strip()
    if not cleaned:
        raise InvalidReviewerAction("MISSING_REVIEWER_IDENTITY", "a reviewer action needs a reviewer id")
    if cleaned.lower() in AI_ACTOR_IDS:
        raise InvalidReviewerAction("AI_CANNOT_REVIEW", f'"{cleaned}" is an AI/system identity, not a reviewer')
    return cleaned
