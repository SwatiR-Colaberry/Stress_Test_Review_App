"""What the Review Queue UI is sent (STORY-012): shown status, history, detail."""
from datetime import datetime, timedelta, timezone

import pytest

from app.evaluation.store import ResultStore
from app.human_review.drafts import DraftSource
from app.human_review.models import ReviewerAction
from app.human_review.store import ReviewActionStore
from app.human_review.test_routes import BASECAMP_URL, _evaluation
from app.human_review.test_store import DRAFT
from app.models import BasecampComment
from app.posting.models import PostingRecord
from app.posting.store import PostingStore
from app.queue_ui.service import QueueReadError, ReviewNotInQueue, ReviewStateMismatch, list_rows, review_detail
from app.review_queue.store import InMemoryReviewQueueStore

_T0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


class _Env:
    """A queue with one review (r-1, comment 2002) and its stores in tmp_path."""

    def __init__(self, tmp_path, evaluated=True):
        ids = iter(["r-1", "r-2"])
        ticks = iter(_T0 + timedelta(minutes=n) for n in range(100))  # r-1 at _T0, r-2 a minute later
        self.queue = InMemoryReviewQueueStore(clock=lambda: next(ticks), new_id=lambda: next(ids))
        self.queue.create_pending(BasecampComment(comment_id=2002, message_id=500, body="##Critique##",
                                                  created_at=_T0, author_name="Asha Verma", app_url=BASECAMP_URL))
        if evaluated:
            ResultStore(tmp_path / "evaluations").put(_evaluation())
        self.drafts = DraftSource(self.queue, tmp_path / "evaluations")
        self.actions = ReviewActionStore(tmp_path / "reviews")
        self.postings = PostingStore(tmp_path / "reviews")
        self.dir = tmp_path

    def act(self, action_id, kind, **fields):
        self.actions.record("r-1", "reviewer-7", ReviewerAction(action_id=action_id, kind=kind, **fields), DRAFT)

    def post(self, status, attempt=1, reason_code=None):
        self.postings.append(PostingRecord(feedback_id="FB-0123456789ab", review_id="r-1", status=status,
                                           recorded_at=datetime.now(timezone.utc), attempt=attempt,
                                           reason_code=reason_code))

    def detail(self):
        return review_detail("r-1", self.drafts, self.actions, self.postings)

    def rows(self):
        return list_rows(self.queue, self.drafts, self.actions, self.postings)


@pytest.fixture
def env(tmp_path):
    return _Env(tmp_path)


# --- Criterion 1: a pending review shows everything needed to review it -------

def test_a_pending_review_shows_student_link_draft_and_findings(env):
    detail = env.detail()
    assert detail.status == "Pending"
    assert (detail.student_name, detail.basecamp_url) == ("Asha Verma", BASECAMP_URL)
    assert (detail.comment_id, detail.message_id) == (2002, 500)
    assert (detail.stress_test_id, detail.rule_version) == ("ST0", "v1")
    assert [f.finding_id for f in detail.findings] == ["ST0-001", "ST0-002"]
    assert all(f.decision == "pending" for f in detail.findings)
    assert [h.kind for h in detail.history] == ["request_received", "ai_draft"]


def test_a_review_not_yet_evaluated_says_so_instead_of_failing(tmp_path):
    detail = _Env(tmp_path, evaluated=False).detail()
    assert detail.status == "Pending"
    assert detail.stress_test_id is None and detail.findings == []
    assert [h.kind for h in detail.history] == ["request_received"]


# --- Shown status: worked out from the records, not the stale queue item ------

def test_status_moves_with_the_review_even_though_the_queue_item_says_pending(env):
    assert env.rows()[0].status == "Pending"
    env.act("a1", "approve_finding", finding_id="ST0-001")
    assert env.rows()[0].status == "In Review"
    env.act("a2", "reject_finding", finding_id="ST0-002")
    env.actions.prepare("r-1", "reviewer-7", DRAFT)
    assert env.rows()[0].status == "Feedback Generated"
    env.post("failed", reason_code="UpstreamUnavailable")
    assert env.rows()[0].status == "Feedback Generated"  # a failed post is not Completed
    env.post("posted", attempt=2)
    assert env.rows()[0].status == "Completed"
    assert env.queue.get_by_review_id("r-1").status == "Pending"  # the queue item was not written


def test_a_queue_item_marked_completed_shows_completed(env):
    env.queue.mark_completed("r-1")
    assert env.detail().status == "Completed"


# --- Criterion 2: a completed review shows its status and full history --------

def test_a_completed_review_shows_status_and_every_step_in_order(env):
    env.act("a1", "edit_finding", finding_id="ST0-001", text="Reviewer wording.")
    env.act("a2", "reject_finding", finding_id="ST0-002")
    env.actions.prepare("r-1", "reviewer-7", DRAFT)
    env.post("posting", attempt=1)
    env.post("posted", attempt=1)
    detail = env.detail()
    assert detail.status == "Completed"
    assert [h.kind for h in detail.history] == [
        "request_received", "ai_draft", "reviewer_action", "reviewer_action", "feedback_prepared",
        "posting", "posting"]
    assert [h.actor for h in detail.history[2:5]] == ["reviewer-7"] * 3
    assert detail.history[0].summary == "Added to the Review Queue (Basecamp comment 2002)"
    assert detail.history[2].summary == "Edited finding ST0-001"
    assert detail.history[-1].summary == "Posting posted, attempt 1, FB-0123456789ab"
    # The AI draft is kept beside the human edit (REQ-008).
    edited = detail.findings[0]
    assert edited.ai_draft.suggested_feedback == "AI suggestion." and edited.feedback_text == "Reviewer wording."
    assert detail.prepared is not None and len(detail.postings) == 2


def test_history_never_quotes_reviewer_or_student_text(env):
    env.act("a1", "add_finding", text="Private note about Asha.", rule_id="ST0-003")
    assert all("Private" not in h.summary and "Asha" not in h.summary for h in env.detail().history)


# --- Queue list --------------------------------------------------------------

def test_the_queue_lists_newest_request_first_with_last_activity(env):
    env.queue.create_pending(BasecampComment(comment_id=2003, message_id=501, body="##Critique##",
                                             created_at=_T0))
    env.act("a1", "approve_finding", finding_id="ST0-001")
    rows = env.rows()
    assert [r.review_id for r in rows] == ["r-2", "r-1"]
    assert rows[1].last_activity_at > rows[1].created_at
    assert rows[0].status == "Pending" and rows[0].student_name is None
    assert (rows[0].stress_test_id, rows[1].stress_test_id) == (None, "ST0")  # r-2 not evaluated yet


def test_an_empty_queue_is_an_empty_list(tmp_path):
    env = _Env(tmp_path)
    env.queue = InMemoryReviewQueueStore()
    assert env.rows() == []


def test_running_it_twice_gives_the_same_answer_and_writes_nothing(env):
    env.act("a1", "approve_finding", finding_id="ST0-001")
    files = sorted(p.name for p in (env.dir / "reviews").iterdir())
    assert env.detail() == env.detail() and env.rows() == env.rows()
    assert sorted(p.name for p in (env.dir / "reviews").iterdir()) == files


# --- Failure paths: details cannot be loaded --------------------------------

def test_an_unknown_review_is_not_found(env):
    with pytest.raises(ReviewNotInQueue):
        review_detail("r-404", env.drafts, env.actions, env.postings)


@pytest.mark.parametrize("path, reason", [
    ("reviews/actions.jsonl", "REVIEWER_ACTIONS_UNREADABLE"),
    ("reviews/posted.jsonl", "POSTING_RECORDS_UNREADABLE"),
    ("evaluations/results.jsonl", "EVALUATION_RESULTS_UNREADABLE"),
])
def test_a_corrupt_store_is_a_clear_read_error_not_a_guess(env, path, reason):
    target = env.dir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    for call in (env.detail, env.rows):
        with pytest.raises(QueueReadError) as caught:
            call()
        assert caught.value.reason_code == reason


def test_actions_on_a_finding_the_newest_draft_lacks_are_a_clear_error(env):
    # The reviewer acted on the v1 draft; the comment was then re-evaluated
    # under v2, whose findings no longer include ST0-001.
    env.act("a1", "approve_finding", finding_id="ST0-001")
    ResultStore(env.dir / "evaluations").put(_evaluation(rule_version="v2", findings=DRAFT[1:]))
    with pytest.raises(ReviewStateMismatch) as caught:
        env.detail()
    assert caught.value.reason_code == "REVIEW_STATE_MISMATCH"
    assert env.rows()[0].status == "In Review"  # the list still loads
