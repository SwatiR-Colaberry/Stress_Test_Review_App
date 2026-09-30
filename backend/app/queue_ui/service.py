"""Build what the Review Queue web UI shows (STORY-012, REQ-018). Read-only:
nothing here writes a store. The routes add the audit trail (step 3).

Sources, all existing: the Review Queue item (STORY-001), the newest AI
evaluation of its comment (STORY-004, via DraftSource), the reviewer action
log and prepared feedback (STORY-005), and the posting records (STORY-006).
The shown status is worked out from them; see queue_ui/models.py.

Failure modes: unknown review -> ReviewNotInQueue (404); any store that
cannot be read or has a corrupt line -> QueueReadError naming which store
(the page shows "could not load" and offers Retry; nothing is guessed);
saved actions that do not fit the newest AI draft (re-evaluated under a newer
rule version) -> ReviewStateMismatch (409) for the detail; the list still loads.
Not handled: the queue is in memory (STORY-001), so after a restart it is
empty until intake runs again; the reviewer files under data/ survive.
Known limit: every row reads the action and posting files once, fine at
hundreds of reviews, not at millions.
"""
from datetime import datetime, timezone
from typing import List, Optional

from app.evaluation.store import EvaluationStoreError
from app.human_review.drafts import DraftSource, ReviewDraft
from app.human_review.models import PreparedFeedback, RecordedAction
from app.human_review.state import InvalidReviewerAction, build_state
from app.human_review.store import ReviewActionStore, ReviewStoreError
from app.models import EvaluationResult, ReviewItem, ReviewStatus
from app.posting.models import PostingRecord
from app.posting.store import PostingStore, PostingStoreError
from app.queue_ui.models import HistoryEntry, QueueRow, ReviewDetail
from app.review_queue.store import ReviewQueueStore

_ACTION_WORDS = {
    "approve_finding": "Approved finding",
    "edit_finding": "Edited finding",
    "reject_finding": "Rejected finding",
    "add_finding": "Added a finding",
}


class ReviewNotInQueue(Exception):
    error_class = "ReviewNotInQueue"
    reason_code = "REVIEW_NOT_FOUND"


class ReviewStateMismatch(Exception):
    """The reviewer's saved actions do not fit the newest AI draft (e.g. the
    comment was re-evaluated under a newer rule version and a finding they
    decided is gone). Nothing is guessed: the detail is refused (409)."""
    error_class = "ReviewStateMismatch"
    reason_code = "REVIEW_STATE_MISMATCH"


class QueueReadError(Exception):
    error_class = "QueueReadError"

    def __init__(self, source: str, cause: Exception) -> None:
        super().__init__(f"could not read the {source}: {cause}")
        self.reason_code = f"{source.upper().replace(' ', '_')}_UNREADABLE"


def shown_status(item: ReviewItem, actions: List[RecordedAction], prepared: Optional[PreparedFeedback],
                 postings: List[PostingRecord]) -> ReviewStatus:
    if item.status == "Completed" or any(p.status == "posted" for p in postings):
        return "Completed"
    if prepared is not None:
        return "Feedback Generated"
    if actions:
        return "In Review"
    return "Pending"


def build_history(item: ReviewItem, evaluation: Optional[EvaluationResult], actions: List[RecordedAction],
                  prepared: Optional[PreparedFeedback], postings: List[PostingRecord]) -> List[HistoryEntry]:
    """Every step of one review, oldest first. Summaries use codes only."""
    entries = [HistoryEntry(at=item.created_at, kind="request_received", actor=None,
                            summary=f"Added to the Review Queue (Basecamp comment {item.comment_id})")]
    if evaluation is not None:
        entries.append(HistoryEntry(
            at=evaluation.evaluated_at, kind="ai_draft", actor="ai",
            summary=f"AI draft: {len(evaluation.findings)} finding(s), {evaluation.stress_test_id} "
                    f"rules {evaluation.rule_version}"))
    for recorded in actions:
        action = recorded.action
        target = action.finding_id or action.rule_id or ""
        entries.append(HistoryEntry(at=recorded.recorded_at, kind="reviewer_action", actor=recorded.reviewer_id,
                                    summary=f"{_ACTION_WORDS[action.kind]} {target}".strip()))
    if prepared is not None:
        entries.append(HistoryEntry(
            at=prepared.prepared_at, kind="feedback_prepared", actor=prepared.reviewer_id,
            summary=f"Feedback prepared: {len(prepared.included_finding_ids)} included, "
                    f"{len(prepared.rejected_finding_ids)} rejected"))
    for record in postings:
        reason = f" ({record.reason_code})" if record.reason_code else ""
        entries.append(HistoryEntry(at=record.recorded_at, kind="posting", actor=None,
                                    summary=f"Posting {record.status}, attempt {record.attempt}, "
                                            f"{record.feedback_id}{reason}"))
    return sorted(entries, key=lambda e: _utc(e.at))  # sorted() is stable: same-moment steps keep their order


def list_rows(queue: ReviewQueueStore, drafts: DraftSource, actions: ReviewActionStore,
              postings: PostingStore) -> List[QueueRow]:
    """Every queue item, newest request first (the reviewer works top-down)."""
    rows = [_row(item, drafts, actions, postings) for item in queue.list_items()]
    return sorted(rows, key=lambda r: _utc(r.created_at), reverse=True)


def review_detail(review_id: str, drafts: DraftSource, actions: ReviewActionStore,
                  postings: PostingStore) -> ReviewDetail:
    draft = _draft(review_id, drafts)
    if draft is None:
        raise ReviewNotInQueue(f"no review {review_id} in the Review Queue")
    item, evaluation = draft.item, draft.evaluation
    log, prepared, posted = _records(review_id, actions, postings)
    try:
        findings = build_state(review_id, draft.findings, log).findings if evaluation else []
    except InvalidReviewerAction as exc:
        raise ReviewStateMismatch(f"review {review_id}: {exc}") from exc
    return ReviewDetail(
        review_id=review_id, status=shown_status(item, log, prepared, posted), comment_id=item.comment_id,
        message_id=item.message_id, created_at=item.created_at, student_name=item.author_name,
        basecamp_url=item.app_url, marker_note=item.marker_note,
        stress_test_id=evaluation.stress_test_id if evaluation else None,
        rule_version=evaluation.rule_version if evaluation else None,
        findings=findings, prepared=prepared, postings=posted,
        history=build_history(item, evaluation, log, prepared, posted),
    )


def _row(item: ReviewItem, drafts: DraftSource, actions: ReviewActionStore, postings: PostingStore) -> QueueRow:
    draft = _draft(item.review_id, drafts)
    evaluation = draft.evaluation if draft else None
    log, prepared, posted = _records(item.review_id, actions, postings)
    history = build_history(item, evaluation, log, prepared, posted)
    return QueueRow(review_id=item.review_id, status=shown_status(item, log, prepared, posted),
                    created_at=item.created_at, last_activity_at=history[-1].at,
                    stress_test_id=evaluation.stress_test_id if evaluation else None,
                    student_name=item.author_name, basecamp_url=item.app_url, marker_note=item.marker_note)


def _draft(review_id: str, drafts: DraftSource) -> Optional[ReviewDraft]:
    try:
        return drafts.get(review_id)
    except EvaluationStoreError as exc:
        raise QueueReadError("evaluation results", exc) from exc


def _records(review_id: str, actions: ReviewActionStore, postings: PostingStore):
    try:
        log, prepared = actions.history(review_id), actions.prepared(review_id)
    except ReviewStoreError as exc:
        raise QueueReadError("reviewer actions", exc) from exc
    try:
        posted = postings.history(review_id)
    except PostingStoreError as exc:
        raise QueueReadError("posting records", exc) from exc
    return log, prepared, posted


def _utc(moment: datetime) -> datetime:
    """Stored times are UTC; one written without a zone is read as UTC so the
    sort never mixes naive and aware datetimes (a TypeError)."""
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment
