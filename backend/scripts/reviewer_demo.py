"""Demo: STORY-005 reviewer page with a made-up review. Offline and free:
no Basecamp, no Claude, no SQL Server. Everything (evaluation, reviewer
actions, audit trail) is written to a new temporary folder, never data/.

Run from the repo root:
  .venv/bin/python backend/scripts/reviewer_demo.py [--port 8005]
then open the printed URL. Stop with Ctrl+C.
"""
import argparse
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# Point every store at the temporary folder BEFORE the app modules read these.
_TMP = Path(tempfile.mkdtemp(prefix="reviewer-demo-"))
os.environ["EVALUATIONS_DIR"] = str(_TMP / "evaluations")
os.environ["REVIEWS_DIR"] = str(_TMP / "reviews")
os.environ["AUDIT_TRAIL_PATH"] = str(_TMP / "audit" / "audit_trail.jsonl")

import uvicorn  # noqa: E402

from app.evaluation.store import ResultStore  # noqa: E402
from app.main import app  # noqa: E402
from app.models import BasecampComment, DraftFinding, EvaluationResult, PrecheckResults, TokenUsage  # noqa: E402
from app.review_queue.dependencies import get_review_queue_store  # noqa: E402

_NOW = datetime.now(timezone.utc)
_COMMENT_ID = 900001  # fictional


def _seed() -> str:
    # Fictional submission, matched to the real ST0 v1 rules (ids and checks).
    findings = [
        DraftFinding(rule_id="ST0-002", status="FAIL", severity="Required Fix",
                     evidence="The dataset is described but no source link appears in the submission.",
                     reason="ST0 needs at least one valid public link to the dataset source.",
                     suggested_feedback="Please provide the public source link for the dataset.",
                     confidence=0.92),
        DraftFinding(rule_id="ST0-006", status="FAIL", severity="Required Fix",
                     evidence="7 problem statements are listed.",
                     reason="ST0 asks for 8 to 10 problem statements.",
                     suggested_feedback="Please add at least 1 more problem statement so you have 8 to 10 in total.",
                     confidence=0.88),
        DraftFinding(rule_id="ST0-004", status="ADVISORY", severity="Required Fix",
                     evidence="An image is attached; what it shows cannot be read from the text.",
                     reason="Check that the screenshot shows the column headers and some preview rows.",
                     suggested_feedback="Please make sure your dataset screenshot shows the column headers and a few rows.",
                     confidence=0.5),
    ]
    ResultStore(Path(os.environ["EVALUATIONS_DIR"])).put(EvaluationResult(
        comment_id=_COMMENT_ID, message_id=900000, stress_test_id="ST0", rule_version="v1",
        model="fake-claude (demo)", evaluated_at=_NOW, correlation_id="demo", stages_evaluated=[1, 2],
        passed_rule_ids=["ST0-001", "ST0-003", "ST0-005", "ST0-007", "ST0-008"], findings=findings,
        prechecks=PrecheckResults(problem_count=7, selected_count=1, link_count=0, dataset_link_present=False,
                                  dataset_file_count=0, image_count=1),
        usage=TokenUsage(),
    ))
    item, _ = get_review_queue_store().create_pending(BasecampComment(
        comment_id=_COMMENT_ID, message_id=900000, body="Ready for review ##Critique##", created_at=_NOW,
        author_name="Demo Student (fictional)",
        app_url=f"https://3.basecamp.com/0000000/buckets/0/messages/900000#__recording_{_COMMENT_ID}"))
    return item.review_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8005)
    args = parser.parse_args()
    review_id = _seed()
    print(f"Demo data folder: {_TMP}")
    print(f"Open: http://127.0.0.1:{args.port}/reviewer/?review={review_id}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
