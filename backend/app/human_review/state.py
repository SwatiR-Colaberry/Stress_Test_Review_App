"""Rebuild a review's current state from the AI draft plus the reviewer's
recorded actions (STORY-005). Pure: no files, no clock.

The AI draft is never modified. Each action is applied in the order it was
recorded, so the same draft and the same log always give the same state.

Rules:
- approve / reject set the decision; a later decision replaces an earlier one
  (a reviewer may change their mind before feedback is prepared). The log
  keeps both.
- edit replaces the feedback text and accepts the finding in the reviewer's
  words (decision = approved, edited = True).
- add creates a reviewer finding, approved, with id "added-<n>" (n counts the
  adds in log order, so ids are stable on every rebuild).
- An action whose action_id was already applied is skipped: a replayed request
  that reached the log twice (e.g. two processes) still counts once.
- An action naming a finding that does not exist raises InvalidReviewerAction.
"""
from typing import Dict, List

from app.human_review.models import RecordedAction, ReviewedFinding, ReviewState
from app.models import DraftFinding


class InvalidReviewerAction(Exception):
    error_class = "InvalidReviewerAction"

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def initial_findings(draft: List[DraftFinding]) -> List[ReviewedFinding]:
    return [
        ReviewedFinding(finding_id=f.rule_id, source="ai", rule_id=f.rule_id, ai_draft=f,
                        feedback_text=f.suggested_feedback)
        for f in draft
    ]


def apply_one(findings: Dict[str, ReviewedFinding], record: RecordedAction) -> None:
    """Apply one action to the findings in place. Raises InvalidReviewerAction."""
    action = record.action
    decided = {"decided_by": record.reviewer_id, "decided_at": record.recorded_at}
    if action.kind == "add_finding":
        finding_id = f"added-{sum(1 for f in findings.values() if f.source == 'reviewer') + 1}"
        findings[finding_id] = ReviewedFinding(
            finding_id=finding_id, source="reviewer", rule_id=action.rule_id,
            decision="approved", feedback_text=action.text, **decided,
        )
        return
    current = findings.get(action.finding_id)
    if current is None:
        raise InvalidReviewerAction(
            "UNKNOWN_FINDING", f"review {record.review_id} has no finding {action.finding_id}"
        )
    if action.kind == "edit_finding":
        update = {"feedback_text": action.text, "edited": True, "decision": "approved"}
    else:
        update = {"decision": "approved" if action.kind == "approve_finding" else "rejected"}
    findings[action.finding_id] = current.model_copy(update={**update, **decided})


def build_state(review_id: str, draft: List[DraftFinding], log: List[RecordedAction]) -> ReviewState:
    findings = {f.finding_id: f for f in initial_findings(draft)}
    seen = set()
    for record in log:
        if record.review_id != review_id or record.action.action_id in seen:
            continue
        apply_one(findings, record)
        seen.add(record.action.action_id)
    return ReviewState(review_id=review_id, findings=list(findings.values()), actions_applied=len(seen))
