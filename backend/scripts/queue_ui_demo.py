"""Demo: STORY-012 Review Queue page with three made-up reviews, one per stage.
Offline and free: no Basecamp, no Claude, no SQL Server. Everything
(evaluations, reviewer actions, posting records, audit trail) is written to a
new temporary folder, never data/.

  r Pending          evaluated, nobody has opened it yet
  r In Review        one finding approved by demo-reviewer
  r Completed        all findings decided, feedback prepared, posted
                     (the posting is simulated: a "posted" record is written
                     and the queue item marked Completed, as STORY-006 does
                     after Basecamp confirms; nothing is sent anywhere)

Reviewer actions go through the real HTTP routes, so the audit trail holds
what a reviewer would have left. Run from the repo root:
  .venv/bin/python backend/scripts/queue_ui_demo.py [--port 8012]
then open the printed URL, enter any reviewer id, and click a row. The audit
file printed at the end of the output shows every view. Stop with Ctrl+C.
"""
import argparse
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

DEMO_REVIEWER = {"X-Reviewer-Id": "demo-reviewer"}
_BASE_COMMENT = 912000  # fictional ids
_STUDENTS = ["Demo Student A (fictional)", "Demo Student B (fictional)", "Demo Student C (fictional)"]


def _evaluation(comment_id: int, when: datetime):
    from app.models import DraftFinding, EvaluationResult, PrecheckResults, TokenUsage
    findings = [
        DraftFinding(rule_id="ST0-002", status="FAIL", severity="Required Fix",
                     evidence="No source link for the dataset appears in the submission.",
                     reason="ST0 needs at least one valid public link to the dataset source.",
                     suggested_feedback="Please provide the public source link for the dataset.", confidence=0.92),
        DraftFinding(rule_id="ST0-006", status="FAIL", severity="Required Fix",
                     evidence="7 problem statements are listed.", reason="ST0 asks for 8 to 10 problem statements.",
                     suggested_feedback="Please add at least 1 more problem statement so you have 8 to 10.",
                     confidence=0.88),
    ]
    return EvaluationResult(
        comment_id=comment_id, message_id=comment_id - 1, stress_test_id="ST0", rule_version="v1",
        model="fake-claude (demo)", evaluated_at=when, correlation_id="demo", stages_evaluated=[1, 2],
        passed_rule_ids=["ST0-001", "ST0-003"], findings=findings,
        prechecks=PrecheckResults(problem_count=7, selected_count=1, link_count=0, dataset_link_present=False,
                                  dataset_file_count=0, image_count=1),
        usage=TokenUsage())


def seed(client, queue, results, postings, now: datetime) -> Dict[str, str]:
    """Create the three reviews; returns {stage: review_id}. `client` is a
    TestClient on the app whose dependencies point at these same stores."""
    from app.models import BasecampComment
    from app.posting.comment import feedback_id_for
    from app.posting.models import PostingRecord

    ids = {}
    for n, stage in enumerate(["Pending", "In Review", "Completed"]):
        comment_id = _BASE_COMMENT + 2 * n + 1
        asked = now - timedelta(hours=3 - n)  # the student's comment time
        item, _ = queue.create_pending(BasecampComment(
            comment_id=comment_id, message_id=comment_id - 1, body="Ready for review ##Critique##", created_at=asked,
            author_name=_STUDENTS[n],
            app_url=f"https://3.basecamp.com/0000000/buckets/0/messages/{comment_id - 1}#__recording_{comment_id}"))
        # Evaluated after intake, as in real use (the queue stamps intake with its own clock).
        results.put(_evaluation(comment_id, item.created_at + timedelta(milliseconds=1)))
        ids[stage] = item.review_id

    def act(review_id, action_id, kind, **fields):
        response = client.post(f"/reviews/{review_id}/actions", headers=DEMO_REVIEWER,
                               json={"action_id": action_id, "kind": kind, **fields})
        response.raise_for_status()

    act(ids["In Review"], "demo-1", "approve_finding", finding_id="ST0-002")
    done = ids["Completed"]
    act(done, "demo-2", "edit_finding", finding_id="ST0-002",
        text="Please add the public link to where the dataset comes from (e.g. the Kaggle page).")
    act(done, "demo-3", "approve_finding", finding_id="ST0-006")
    client.post(f"/reviews/{done}/prepare", headers=DEMO_REVIEWER).raise_for_status()
    postings.append(PostingRecord(feedback_id=feedback_id_for(done), review_id=done, status="posted",
                                  recorded_at=datetime.now(timezone.utc), attempt=1,
                                  basecamp_comment_id=_BASE_COMMENT + 99))
    queue.mark_completed(done)
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()

    # Point every store at a new temporary folder BEFORE the app modules read these.
    tmp = Path(tempfile.mkdtemp(prefix="queue-ui-demo-"))
    os.environ["EVALUATIONS_DIR"] = str(tmp / "evaluations")
    os.environ["REVIEWS_DIR"] = str(tmp / "reviews")
    os.environ["AUDIT_TRAIL_PATH"] = str(tmp / "audit" / "audit_trail.jsonl")

    import uvicorn
    from fastapi.testclient import TestClient

    from app.evaluation.store import ResultStore
    from app.main import app
    from app.posting.dependencies import get_posting_store
    from app.review_queue.dependencies import get_review_queue_store

    ids = seed(TestClient(app), get_review_queue_store(), ResultStore(tmp / "evaluations"), get_posting_store(),
               datetime.now(timezone.utc))
    print(f"Demo data folder: {tmp}")
    print(f"Reviews: {ids}")
    print(f"Open: http://127.0.0.1:{args.port}/queue/")
    print(f"Audit trail: {tmp / 'audit' / 'audit_trail.jsonl'}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
