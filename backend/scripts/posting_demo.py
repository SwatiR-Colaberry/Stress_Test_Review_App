"""Demo: STORY-006, posting final feedback to Basecamp. Offline and free:
a fake Basecamp thread (app.posting.fake), fictional review data, and every
file (reviewer actions, posting records, audit trail) in a new temporary
folder, never data/. The real Basecamp is never contacted.

Each scenario runs the whole chain: a reviewer approves / edits / rejects the
AI findings and prepares the feedback (STORY-005), then the system posts it.

Run from the repo root:
  .venv/bin/python backend/scripts/posting_demo.py
"""
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import httpx  # noqa: E402

from app.audit.trail import JsonlFileAuditTrail  # noqa: E402
from app.human_review.models import ReviewerAction  # noqa: E402
from app.human_review.store import ReviewActionStore  # noqa: E402
from app.models import BasecampComment, DraftFinding  # noqa: E402
from app.posting.config import PostingConfig  # noqa: E402
from app.posting.fake import FakeThread  # noqa: E402
from app.posting.service import post_review_feedback  # noqa: E402
from app.posting.store import PostingStore  # noqa: E402
from app.review_queue.store import InMemoryReviewQueueStore  # noqa: E402

PROJECT = 111  # fictional project id
REVIEWER = "reviewer-demo"
TMP = Path(tempfile.mkdtemp(prefix="posting-demo-"))
AUDIT = JsonlFileAuditTrail(TMP / "audit" / "audit_trail.jsonl")
POSTINGS = PostingStore(TMP / "reviews")
REVIEWS = ReviewActionStore(TMP / "reviews")
CONFIG = PostingConfig(enabled=True, allowed_project_ids=frozenset({PROJECT}))

DRAFT = [
    DraftFinding(rule_id="ST0-002", status="FAIL", severity="Required Fix", evidence="No dataset link.",
                 reason="ST0 needs a public dataset link.",
                 suggested_feedback="Please provide the public source link for the dataset.", confidence=0.9),
    DraftFinding(rule_id="ST0-006", status="FAIL", severity="Required Fix", evidence="7 problems listed.",
                 reason="ST0 asks for 8 to 10.",
                 suggested_feedback="Please add at least 1 more problem statement.", confidence=0.88),
    DraftFinding(rule_id="ST0-004", status="ADVISORY", severity="Required Fix", evidence="Image attached.",
                 reason="Cannot read the screenshot.", suggested_feedback="Check the screenshot.", confidence=0.5),
]


def reviewed_item(comment_id: int, project_id: int = PROJECT, prepare: bool = True):
    """A queued review whose AI draft a human reviewer has decided and prepared."""
    queue = InMemoryReviewQueueStore()
    item, _ = queue.create_pending(BasecampComment(comment_id=comment_id, message_id=comment_id + 1000,
                                                   body="##Critique##", created_at=datetime.now(timezone.utc),
                                                   project_id=project_id))
    for kind, finding, text in [("approve_finding", "ST0-002", None),
                                ("edit_finding", "ST0-006", "Please list 8 to 10 problem statements (you have 7)."),
                                ("reject_finding", "ST0-004", None)]:
        REVIEWS.record(item.review_id, REVIEWER, ReviewerAction(action_id=str(uuid.uuid4()), kind=kind,
                                                                finding_id=finding, text=text), DRAFT)
    if prepare:
        REVIEWS.prepare(item.review_id, REVIEWER, DRAFT)
    return queue, item


def post(queue, item, thread, config=CONFIG):
    return post_review_feedback(item.review_id, REVIEWER, queue=queue, reviews=REVIEWS, postings=POSTINGS,
                                audit=AUDIT, client_factory=thread.client, config=config,
                                correlation_id=f"demo-{item.comment_id}", sleep=lambda s: None)


def show(title, queue, item, thread, result):
    print(f"\n=== {title}")
    print(f"  queue status before: Pending   after: {queue.get_by_review_id(item.review_id).status}")
    print(f"  result: {result.status}  reason={result.reason_code}  attempts={result.attempts}  "
          f"already_posted={result.already_posted}  basecamp_comment_id={result.basecamp_comment_id}")
    print(f"  Basecamp requests: {thread.requests}   comments on the thread: {len(thread.comments)}")
    for event in [e for e in AUDIT.read_all() if e.review_id == item.review_id and e.feedback_id]:
        print(f"  audit: {event.action:<24} feedback_id={event.feedback_id} outcome={event.outcome}"
              f"{'  reason=' + event.reason_code if event.reason_code else ''}")


def main() -> int:
    print(f"Posting demo (fake Basecamp, nothing real). Files in {TMP}")

    queue, item = reviewed_item(1)
    thread = FakeThread()
    show("1. Approved feedback is posted -> review Completed", queue, item, thread, post(queue, item, thread))
    print("  posted comment (HTML):\n    " + thread.comments[0]["content"].replace("</div>", "</div>\n    ").strip())
    second = post(queue, item, thread)
    print(f"  posting it again: status={second.status} already_posted={second.already_posted}, "
          f"Basecamp requests now {thread.requests}, comments still {len(thread.comments)}")

    queue, item = reviewed_item(2)
    thread = FakeThread(post_failures=[503])
    show("2. Basecamp error (503) -> retried -> succeeds", queue, item, thread, post(queue, item, thread))

    queue, item = reviewed_item(3)
    thread = FakeThread(post_failures=["land_then_timeout"])
    show("3. Post landed but the answer timed out -> found on retry, not posted twice",
         queue, item, thread, post(queue, item, thread))

    queue, item = reviewed_item(4)
    thread = FakeThread(get_failures=[httpx.ConnectError("unreachable")] * 3)
    show("4. Basecamp unreachable every time -> gives up after 3 attempts, error logged",
         queue, item, thread, post(queue, item, thread))

    queue, item = reviewed_item(5)

    def slow(request):
        time.sleep(3)
        return httpx.Response(200, json=[])
    thread = FakeThread(get_failures=[slow])
    limit = PostingConfig.model_construct(enabled=True, allowed_project_ids=frozenset({PROJECT}), time_limit_s=1.0)
    started = time.monotonic()
    result = post(queue, item, thread, config=limit)
    show(f"5. Posting exceeds the time limit (1 s; Basecamp hangs 3 s) -> stopped after "
         f"{time.monotonic() - started:.1f} s", queue, item, thread, result)

    queue, item = reviewed_item(6, prepare=False)
    thread = FakeThread()
    show("6a. Malformed: no prepared feedback -> refused, nothing sent", queue, item, thread,
         post(queue, item, thread))
    queue, item = reviewed_item(7, project_id=222)
    thread = FakeThread()
    show("6b. Malformed: project not on the posting list -> refused, nothing sent", queue, item, thread,
         post(queue, item, thread))
    queue, item = reviewed_item(8)
    thread = FakeThread()
    show("6c. Posting switched off (BASECAMP_POSTING_ENABLED=no) -> refused", queue, item, thread,
         post(queue, item, thread, config=PostingConfig()))

    print(f"\nAudit trail: {TMP / 'audit' / 'audit_trail.jsonl'}")
    print(f"Posting records: {TMP / 'reviews' / 'posted.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
