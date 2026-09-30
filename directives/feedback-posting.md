# Posting final feedback to Basecamp — and only then marking the review Completed

STORY-006 · REQ-007 ("mark reviews Completed only after human review and Basecamp posting are both done").
Code: `backend/app/posting/`, route in `backend/app/routers/posting.py`, POST support in
`backend/app/basecamp/api_client.py`. Connection setup: `directives/basecamp-connection-setup.md`.

## What it does

1. A reviewer has prepared the feedback (STORY-005: `data/reviews/prepared.jsonl`, `ready_to_post`).
2. `POST /reviews/{review_id}/post` (header `X-Reviewer-Id`) calls `post_review_feedback()`:
   - already posted? return that result and send nothing;
   - posting switched off, or the feedback fails the checks? refuse with a reason code, nothing sent;
   - otherwise up to **3 attempts**, each: read the thread's comments, and only if this feedback's
     ref is not there, post the comment.
3. Only after Basecamp confirms the comment: a `posted` record, a `feedback_posted` audit event,
   then the Review Queue item becomes **Completed**. Never before, never on failure.

The posted comment (HTML, reviewer text escaped):

```
1. <first approved finding, reviewer's wording where edited>
2. …

Review ref: FB-1a2b3c4d5e6f
##FeedbackGiven##
```

- `FB-…` is the **feedback id**, derived from the review id (the same on every attempt). It is how a
  retry recognizes a comment that already landed (user decision 2026-09-30).
- `##FeedbackGiven##` is the marker reviewers write today; STORY-001 intake treats such a comment as
  the reviewer's, so it never opens a new review.

## Settings (`.env`; names in `.env.example`)

| Variable | Default | Meaning |
|---|---|---|
| `BASECAMP_POSTING_ENABLED` | `no` | `yes` posts to the real Basecamp. **Off until STORY-014** (Basecamp sign-in) ties posts to a verified reviewer (user decision 2026-09-30). |
| `BASECAMP_POSTING_PROJECT_IDS` | empty = none | Projects feedback may be posted into. A review pointing anywhere else is refused. |
| `BASECAMP_POSTING_TIME_LIMIT_S` | 60 (5–300) | Upper bound for one posting request, all attempts included. |

Plus the Basecamp connection settings (`BASECAMP_ACCOUNT_ID`, `BASECAMP_ACCESS_TOKEN`,
`BASECAMP_USER_AGENT`). The API server reads settings from its **environment**; `.env` is loaded
only by the scripts. To post through a local server, start it with the settings exported
(`set -a; source .env; set +a` before `uvicorn`).

## Failures

| What goes wrong | What happens | HTTP |
|---|---|---|
| Feedback malformed or not allowed: `NO_PREPARED_FEEDBACK`, `FEEDBACK_REVIEW_MISMATCH`, `REVIEWER_NOT_HUMAN` (REQ-011 again), `EMPTY_FEEDBACK`, `FEEDBACK_TOO_LONG`, `NO_POSTING_TARGET` (no project id on the review), `PROJECT_NOT_ALLOWED`, `POSTING_DISABLED` | Refused before any Basecamp call; `failed` record (attempt 0) + `feedback_post_refused` audit event | 409 |
| Basecamp unreachable, 5xx, 429 | Retried after 1 s, 2 s while attempts and time remain; then `failed` with the error class, audited, logged as an **error** | 502 |
| Posting exceeds the time limit | Stops at the limit (`TimeLimitExceeded`), audited, logged as an error | 502 |
| A post whose answer was lost (read timeout, dropped connection) | The client does **not** re-post blindly; the next attempt reads the thread, finds the ref, records it as posted | 200 |
| Token rejected (`AuthError`), unexpected Basecamp answer (`ContractViolation`), Basecamp settings missing (`ConfigError`) | Fails at once (a retry cannot help) | 502 |
| Two requests for one review at once | Per-review lock: the second waits, then returns the first one's post; if it waits past the time limit, `POSTING_IN_PROGRESS` | 200 / 409 |
| No `X-Reviewer-Id` | Refused and logged | 401 |
| Posting records or audit trail cannot be written; bad posting settings | "Retry; it is safe" (the thread is checked before any new post) | 503 |
| A request dies after Basecamp confirmed | The next request finds the `posted` record, writes any missing audit event once, marks the review Completed, sends nothing | 200 |

**Not handled (known):**
- Two **server processes** posting the same review at the same moment: the lock is per process.
  Run one process until posting records move to a database with a unique key.
- A Basecamp call that hangs past the time limit and then succeeds *after* a new request has
  already read the thread could post twice. Needs Basecamp to hang over 60 s and a person to retry
  within that window.
- Access-token refresh (tokens last ~2 weeks): re-run the OAuth setup script (see the connection runbook).
- Review intake has no SQL Server reader yet (REQ-013 has no story); comments come from the Basecamp
  API, which carries the project id. If a SQL Server intake is built, it must set the review's
  `project_id` from `ADF_CCS_BasecampProjects_Details.ProjectID`. Checked read-only 2026-09-30: for
  all 7,695 Stress Test steps with a readable `MessageBoardURL`, the URL's project number equals
  `pd.ProjectID` and its message number equals `pd.MessageBoardID`; every step with comments has one.
  (`ADF_CCS_BasecampProjects.ProjectID` is a different number: do not use it.) Without it such
  reviews are refused with `NO_POSTING_TARGET`.

## Records (git-ignored: they concern student reviews)

| File | What |
|---|---|
| `data/reviews/posted.jsonl` | One `PostingRecord` per step: `posting` (per attempt), `posted`, `failed`, with feedback id, attempt, Basecamp comment id, reason code. A review is posted once any record says `posted`. |
| `data/audit/audit_trail.jsonl` | `feedback_post_refused` / `feedback_post_attempted` / `feedback_posted` / `feedback_post_failed`, each with `feedback_id`, review, comment, message and project ids, actor, outcome and reason code. Never the feedback text. |

Log lines (`stress_test_review.posting`, JSON): `event=feedback_posting` with `feedback_id` and
`status` (`posting`, `retrying`, `posted`, `failed`, `refused`).

## Running it

```bash
.venv/bin/python backend/scripts/posting_demo.py           # offline demo against a fake Basecamp, temp folder
.venv/bin/python -m pytest backend/app/posting             # this feature's tests
.venv/bin/python backend/scripts/check_basecamp_connection.py --project-id <id>   # real Basecamp, read-only
```

## First live test (not done yet)

Needs: the connection set up (done 2026-09-30), a **sandbox** Basecamp project with one test message,
`BASECAMP_POSTING_PROJECT_IDS` set to only that project, and `BASECAMP_POSTING_ENABLED=yes` for the
test only (a one-time exception to the STORY-014 rule, the project owner's call). Confirms: Basecamp
accepts the comment HTML, the ref is still findable after Basecamp stores it, and the real
response shape.

## How success is verified

- `pytest backend` passes, including `backend/app/posting/test_service.py`:
  `test_approved_feedback_is_posted_and_the_review_is_marked_completed` (AC1),
  `test_the_review_is_not_completed_when_posting_fails` (AC1),
  `test_a_posting_error_is_retried_and_then_succeeds`,
  `test_basecamp_unreachable_every_time_gives_up_after_three_attempts_and_logs_an_error` (AC2),
  `test_every_posting_event_is_audited_with_feedback_id_and_status` (AC3), plus the time-limit,
  malformed-feedback, double-post and concurrency tests.
- `posting_demo.py`: scenarios 1–3 end `Completed` with one comment on the thread; 4–6 stay
  `Pending` with the reason shown; every scenario lists its audit events with the feedback id.
