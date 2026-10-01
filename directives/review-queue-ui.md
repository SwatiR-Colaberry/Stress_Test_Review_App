# Review Queue web UI — how reviewers see the queue, a review's history, and the rules

STORY-012 · REQ-018 (a web UI for reviewers to manage the Review Queue and perform reviews).
Code: `backend/app/queue_ui/` (queue and detail), `backend/app/rules_ui/` (Rules page),
routes in `backend/app/routers/queue_ui.py` and `backend/app/routers/rules_ui.py`.

## The pages

| Page | What it shows |
|---|---|
| `/queue/` | Every review: student name, status, Stress Test, when it was added and last touched. Status tiles (also the filter), search by student or review id, and a "What each status means" section. Clicking a review opens its detail: progress steps, student and Basecamp link, the findings as the reviewer currently sees them (edits beside the AI's original), the prepared feedback, and the full history timeline. "Start review" / "Continue review" opens the reviewer page. |
| `/reviewer/?review=<id>` | The STORY-005 page where findings are approved, edited, rejected or added. Now has the same app bar, a "← Review Queue" link, and "What does this rule mean?" on each finding. |
| `/rules/` | One tab per active Stress Test ("Stress Test 0"): purpose, required problem fields, what is out of scope, then each rule by stage with the feedback a student gets and a fictional ✓ passes / ✗ fails example. `/rules/#ST0-004` jumps to a rule. |

All three share `backend/app/human_review/web/reviewer.css` (colours, app bar) and
`review_logic.js` (e.g. `stressTestName`: headings say "Stress Test 0", not "ST0").
They are served with `Cache-Control: no-cache` (`backend/app/web_static.py`), so a browser
always checks for a newer copy; without it a new page ran against an old shared file once.

## What each status means (worked out when the page loads)

The Review Queue item itself stays "Pending" until a post succeeds, so the page works the
status out from the records the app already keeps (user decision 2026-09-30):

| Status | When |
|---|---|
| Pending | No reviewer decision yet |
| In Review | At least one reviewer action saved |
| Feedback Generated | The reviewer prepared the final feedback (locked) |
| Completed | Basecamp confirmed the post, or the queue item is marked Completed |

After Feedback Generated, the review waits: real posting is still off
(`BASECAMP_POSTING_ENABLED=no`) and there is no "Post" button yet (user decision 2026-09-30;
Basecamp sign-in, the precondition, landed with STORY-014 on 2026-10-01).

## Trust: every page load is audited

Each request the pages make writes one audit event with `recorded_at` and `actor_id`
(the signed-in reviewer's Basecamp email), whatever the outcome — `queue_viewed`,
`review_detail_viewed` (also the reviewer page's load) and `rules_viewed`. Outcome `success`,
`blocked` or `failure` (the reason code, or the error class of an unexpected error). A request
with no session is refused before it is a view (401, logged, not audited; STORY-014). A successful view is recorded
**before** its data is returned: if the audit trail cannot be written the page gets 503 and
shows nothing. Reviewer actions, prepare and post are audited by STORY-005/006 as before.
Filtering and searching in the browser never reach the server and are not audited.

## Reviewer identity

The app bar shows who is signed in with Basecamp, their role and **Sign out** (STORY-014,
`directives/basecamp-sign-in.md`); admins also see **Admins**. The pages send no identity of
their own: the session cookie does. The reviewer-id box and its `X-Reviewer-Id` header were
removed on 2026-10-01.

## Failures

| What happens | What the reviewer sees | Code |
|---|---|---|
| Not signed in, or the 8-hour session ended | the page goes to sign-in and comes back (401) | `NOT_SIGNED_IN`, logged |
| Unknown review (e.g. server restarted: the queue is in memory) | "not in the Review Queue" (404) | `REVIEW_NOT_FOUND` |
| A store cannot be read or has a corrupt line | "Could not load … Retry" (503) | `REVIEWER_ACTIONS_UNREADABLE`, `POSTING_RECORDS_UNREADABLE`, `EVALUATION_RESULTS_UNREADABLE` |
| Saved decisions no longer fit the newest AI draft (re-evaluated under newer rules) | detail refused (409); the list still loads | `REVIEW_STATE_MISMATCH` |
| Audit trail cannot be written | 503, nothing shown | `AuditWriteError` |
| Rule registry unreadable / one rule file broken | 503 / that tab "not available", others shown | `RULE_REGISTRY_UNREADABLE`, `RULE_MODULE_NOT_FOUND`, `RULE_MODULE_INVALID`, `RULE_VERSION_MISMATCH` |
| Server slow or unreachable | "did not answer in time" / "network problem", Retry | 15 s timeout per request |

Every request times out after 15 s; Retry is offered only where it may help (no answer, 503).
A failed refresh never leaves an older review looking current. All names and text from
Basecamp are inserted as text, never as HTML.

## Rule examples

`example` (`passes`, `fails`, each ≤ 600 characters) is optional on every rule in
`backend/app/rules/modules/<ST>/<version>.json`. It is display only: the evaluation prompt picks
its fields by name, so examples are never sent to Claude and changing one does not change an
evaluation (`test_rule_examples_are_never_sent_to_claude`). Examples must be fictional — the
repo is public. The ST0 examples were drafted 2026-09-30 and approved by the project owner.

## Running it

```
.venv/bin/python backend/scripts/signin_demo.py          # port 8014, same three reviews
# open http://127.0.0.1:8014/queue/, choose "Demo Reviewer" on the demo sign-in page, click a review
```
(`queue_ui_demo.py` seeds the same data but serves the real Basecamp sign-in, so it needs the
settings in `directives/basecamp-sign-in.md`.) The demo seeds three fictional reviews (Pending, In Review, Completed) into a new temporary
folder — evaluations, reviewer actions, posting records and the audit trail — never `data/`.
The Completed review's post is simulated; nothing is sent to Basecamp.

## Not yet

- Posting button (needs a decision now that sign-in exists).
- Images in feedback (STORY-015). Highlighting the evidence in the student's submission and
  showing the attached image a finding is about: follow-up story approved 2026-09-30, to be
  added in the portal first (see PROGRESS.md). Marking a spot inside an image is not needed (user decision 2026-09-30).
- The queue is in memory (STORY-001): after a restart it is empty until intake runs again.
- No automated browser (layout) test: checked by eye by the project owner, 2026-09-30.

## How success is verified

1. `.venv/bin/python -m pytest backend/app/queue_ui backend/app/rules_ui` — acceptance tests
   `test_a_pending_review_in_the_queue_shows_all_details_needed_for_review`,
   `test_a_completed_review_shows_status_and_history`,
   `test_every_ui_view_is_audited_with_timestamp_and_user_id`, plus
   `test_opening_the_reviewer_page_is_audited_with_user_and_time` and
   `test_opening_the_rules_page_is_audited_with_user_and_time`.
2. Run the demo and open the three pages; the printed audit file lists every page load with
   the signed-in reviewer's email and time.
