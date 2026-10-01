# Human Review of AI Findings — how a reviewer turns an AI draft into feedback

STORY-005 · REQ-006 (approve, edit, reject or add findings before feedback is posted).
Code: `backend/app/human_review/`, routes in `backend/app/routers/human_review.py`.

## What it does

1. A reviewer opens `/reviewer/?review=<review id>`. The page shows the Stress Test, the
   student's name and an "Open in Basecamp" link, then one card per AI finding: the rule in
   plain words, severity, decision, and the suggested feedback text. Evidence, the AI's reason
   and confidence, the rule code and who decided are under **Show details**.
2. For each finding the reviewer chooses **Approve**, **Save edit** (accepts it in the
   reviewer's own words) or **Reject**, and can **Add a finding** the AI did not raise.
   A later decision replaces an earlier one until feedback is prepared.
3. **Prepare feedback** is allowed only when every finding has a decision. Approved findings
   become a numbered list (reviewer wording where edited); rejected ones are left out. The
   REQ-011 guardrail checks it (a named human approver, never an AI id; not empty). The result
   is saved once as `ready_to_post`, and the review is then locked.
4. Posting to Basecamp is **STORY-006**; this step never contacts Basecamp.

## Limits (user decision 2026-09-29, measured on the history extract)

- A reviewer finding may hold **2,000** characters; the whole feedback **10,000**. The longest
  real reviewer reply was 4,513 characters (ST2, median 903). The AI's own suggestion stays
  capped at 400 (token cost).

## Where things are stored (git-ignored: they quote student work)

| File | What |
|---|---|
| `data/reviews/actions.jsonl` | Every reviewer action, append-only: reviewer, time, action. With the AI draft this is the review's full history (REQ-008). |
| `data/reviews/prepared.jsonl` | The prepared feedback, one per review, written once. |
| `data/audit/audit_trail.jsonl` | One audit event per reviewer request (`reviewer_finding_*`, `reviewer_feedback_prepared`, `reviewer_action_blocked`), with reviewer and timestamp. Ids and reason codes only; never the student's name or text. |

`REVIEWS_DIR`, `EVALUATIONS_DIR` and `AUDIT_TRAIL_PATH` override the folders.

## Reviewer identity

The reviewer is the person **signed in with Basecamp** (STORY-014, `directives/basecamp-sign-in.md`):
their Basecamp email is recorded on every action. Without a session the page goes to sign-in and
the API answers 401 before anything is read or saved. The temporary `X-Reviewer-Id` header was
removed on 2026-10-01. The service still refuses AI/system ids (`claude`, `system`, `bot`, …) and
blank ids as a second line of defence.

## Failures

| What goes wrong | What happens |
|---|---|
| Page cannot load the review (network, 10 s timeout, 404, 503) | Red banner with the reason; Retry when retrying can help |
| An edit or decision is not saved (network, timeout, 503) | The text stays in the box marked "Not saved"; Retry resends the same request (same `action_id`), which the server applies once. An added finding is retried with the same `action_id` while its text is unchanged (`web/review_logic.js`). |
| Audit trail fails after the action was saved | 503 "not saved, retry"; the retry writes the missing audit event without saving the action twice |
| Refused action | 401 not signed in (session ended: the page goes to sign-in) · 409 `UNKNOWN_FINDING`, `UNDECIDED_FINDINGS`, `REVIEW_LOCKED`, `ACTION_ID_REUSED`, `EMPTY_FEEDBACK`, `FEEDBACK_TOO_LONG` · 404 `REVIEW_NOT_FOUND`, `NO_AI_DRAFT`. Every 409 refusal is audited (a 401 is logged: nobody is signed in); a 404 has no review to attach an event to, so it is logged as a warning instead. |
| Rule module unreadable | Cards show rule codes instead of names; a warning is logged |
| Corrupt line in a review file | Error naming the file and line; never skipped |

Not handled: two server processes appending the same action at the same moment can both write
it; the rebuild applies it once, so the state is still right.

## Running it

```bash
.venv/bin/python backend/scripts/reviewer_demo.py        # offline demo, fictional data, temp folder
# open the printed http://127.0.0.1:8005/reviewer/?review=... link; stop with Ctrl+C
.venv/bin/python -m pytest backend/app/human_review      # this feature's tests
```

## Not yet

- The Review Queue is still in memory (STORY-001 decision): after a restart a review must be
  taken in again to open it. Saved reviewer actions survive on disk. A page left open across a
  restart says so ("The server no longer has this review…") instead of saving.
- Preparing does not change the queue status to "Feedback Generated" (queue store has no
  update yet) — STORY-006 / STORY-012.
- Student name and Basecamp link only arrive for comments retrieved through the Basecamp API.
- Images (STORY-015) and AI polish (STORY-016) are separate stories.

## How success is verified

- `pytest backend` passes, including `backend/app/human_review/test_routes.py`:
  `test_approving_the_findings_prepares_feedback_for_posting`,
  `test_edits_are_saved_and_prepared_for_posting`,
  `test_every_reviewer_action_is_audited_with_reviewer_and_time`.
- The demo: decide every finding, prepare, and the final text appears; the audit file in the
  demo's temp folder has one timestamped event per action.
