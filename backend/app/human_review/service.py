"""Reviewer workflow with its audit trail (STORY-005). The routes are thin
wrappers around these three functions.

Trust (REQ-008, story criterion "logs all reviewer actions with timestamps"):
every reviewer request writes an AuditEvent (recorded_at = when) before its
result is returned: success for a saved action or prepared feedback, blocked
(reviewer_action_blocked + reason code) for a refused one.

Retry safety: a saved action's event_id is derived from (review_id,
action_id), and prepared feedback's from review_id, so a retried request
writes its event only if it is not in the trail yet. Order: save, then audit.
If the audit write fails after the save, the caller gets AuditWriteError (503,
"retry"); the retry is a replay of the saved action and writes the missing
event. So nothing is reported done without its record, and nothing is
recorded twice. Known limit: the check reads the whole trail each time, which
is fine at the current volume (hundreds of reviews), not at millions.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.audit.trail import AuditTrail
from app.human_review.drafts import DraftSource, ReviewDraft
from app.human_review.models import PreparedFeedback, ReviewerAction, ReviewView
from app.human_review.rule_names import rule_names
from app.human_review.state import InvalidReviewerAction
from app.human_review.store import ReviewActionStore
from app.models import AuditAction, AuditEvent

logger = logging.getLogger("stress_test_review.human_review")

_EVENT_NAMESPACE = uuid.UUID("5f0c1d2e-0005-4a5b-9c6d-000000000005")  # fixed: ids must be stable across runs
_ACTION_EVENTS = {
    "approve_finding": "reviewer_finding_approved",
    "edit_finding": "reviewer_finding_edited",
    "reject_finding": "reviewer_finding_rejected",
    "add_finding": "reviewer_finding_added",
}
UNIDENTIFIED_ACTOR_ID = "unidentified"


class ReviewNotFound(Exception):
    error_class = "ReviewNotFound"

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def view_review(review_id: str, drafts: DraftSource, store: ReviewActionStore) -> ReviewView:
    draft = _load(review_id, drafts)
    state = store.state(review_id, draft.findings)
    evaluation = draft.evaluation
    return ReviewView(review_id=review_id, comment_id=draft.item.comment_id,
                      student_name=draft.item.author_name, basecamp_url=draft.item.app_url,
                      stress_test_id=evaluation.stress_test_id, rule_version=evaluation.rule_version,
                      rule_names=rule_names(evaluation.stress_test_id, evaluation.rule_version),
                      findings=state.findings, actions_applied=state.actions_applied,
                      prepared=store.prepared(review_id))


def apply_action(review_id: str, reviewer_id: Optional[str], action: ReviewerAction, drafts: DraftSource,
                 store: ReviewActionStore, audit: AuditTrail, correlation_id: str) -> ReviewView:
    draft = _load(review_id, drafts)
    try:
        state = store.record(review_id, reviewer_id or "", action, draft.findings)
    except InvalidReviewerAction as exc:
        _blocked(audit, draft, reviewer_id, correlation_id, exc)
        raise
    rule_id = action.rule_id if action.kind == "add_finding" else next(
        (f.rule_id for f in state.findings if f.finding_id == action.finding_id), None)
    _record_once(audit, _event(draft, _ACTION_EVENTS[action.kind], reviewer_id, correlation_id, "success",
                               event_id=_stable_id(f"{review_id}:{action.action_id}"), rule_id=rule_id))
    _log("reviewer_action_saved", correlation_id, review_id=review_id, kind=action.kind, rule_id=rule_id)
    return view_review(review_id, drafts, store)


def prepare_feedback(review_id: str, reviewer_id: Optional[str], drafts: DraftSource, store: ReviewActionStore,
                     audit: AuditTrail, correlation_id: str) -> PreparedFeedback:
    draft = _load(review_id, drafts)
    try:
        prepared = store.prepare(review_id, reviewer_id or "", draft.findings)
    except InvalidReviewerAction as exc:
        _blocked(audit, draft, reviewer_id, correlation_id, exc)
        raise
    _record_once(audit, _event(draft, "reviewer_feedback_prepared", prepared.reviewer_id, correlation_id,
                               "success", event_id=_stable_id(f"{review_id}:prepared")))
    _log("reviewer_feedback_prepared", correlation_id, review_id=review_id,
         findings=len(prepared.included_finding_ids), characters=len(prepared.feedback_text))
    return prepared


def _load(review_id: str, drafts: DraftSource) -> ReviewDraft:
    """Not audited (there is no review to attach an event to), but logged, so a
    404 never happens silently."""
    draft = drafts.get(review_id)
    reason = "REVIEW_NOT_FOUND" if draft is None else "NO_AI_DRAFT" if draft.evaluation is None else None
    if reason:
        _log("review_not_found", str(uuid.uuid4()), level=logging.WARNING, review_id=review_id[:128],
             reason_code=reason, error_class=ReviewNotFound.error_class)
        message = (f"no review {review_id} in the Review Queue" if reason == "REVIEW_NOT_FOUND"
                   else f"review {review_id} has no AI evaluation yet")
        raise ReviewNotFound(reason, message)
    return draft


def _blocked(audit: AuditTrail, draft: ReviewDraft, reviewer_id: Optional[str], correlation_id: str,
             exc: InvalidReviewerAction) -> None:
    audit.record(_event(draft, "reviewer_action_blocked", reviewer_id, correlation_id, "blocked",
                        event_id=str(uuid.uuid4()), reason_code=exc.reason_code))
    _log("reviewer_action_blocked", correlation_id, level=logging.WARNING, review_id=draft.item.review_id,
         reason_code=exc.reason_code, error_class=exc.error_class)


def _event(draft: ReviewDraft, action: AuditAction, reviewer_id: Optional[str], correlation_id: str,
           outcome: str, event_id: str, **fields) -> AuditEvent:
    return AuditEvent(
        event_id=event_id, recorded_at=datetime.now(timezone.utc), action=action,
        actor_id=(reviewer_id or "").strip() or UNIDENTIFIED_ACTOR_ID, outcome=outcome,
        correlation_id=correlation_id, review_id=draft.item.review_id, comment_id=draft.item.comment_id,
        message_id=draft.item.message_id, stress_test_id=draft.evaluation.stress_test_id,
        rule_version=draft.evaluation.rule_version, **fields,
    )


def _record_once(audit: AuditTrail, event: AuditEvent) -> None:
    if not any(existing.event_id == event.event_id for existing in audit.read_all()):
        audit.record(event)


def _stable_id(key: str) -> str:
    return str(uuid.uuid5(_EVENT_NAMESPACE, key))


def _log(event: str, correlation_id: str, level: int = logging.INFO, **context) -> None:
    logger.log(level, json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(), "level": logging.getLevelName(level).lower(),
        "service": "backend", "event": event, "correlation_id": correlation_id,
        "outcome": "failure" if level >= logging.WARNING else "success", **context,
    }))
