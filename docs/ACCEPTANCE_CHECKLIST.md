# Acceptance Checklist

One-line, repo-verifiable acceptance checks for each of the 18 canonical requirements in [`.colaberry/plan.json`](../.colaberry/plan.json) (rendered for humans in [`REQUIREMENTS.md`](REQUIREMENTS.md)), cross-referenced against each requirement's fulfilling story's Given/When/Then acceptance criteria in [`STORIES.md`](STORIES.md). Each line names a concrete artifact (a file, a test, a grep) rather than a narrative description — the check should be answerable by looking at the repo, not by trusting a claim.

**Superseded note:** an earlier version of this file was written before `.colaberry/plan.json`/`progress.json` existed in this repo, grouped by Master Spec section number with invented labels (e.g. "R4" for the human-approval guardrail). The canonical data pulled 2026-09-16 revealed the platform's real R4 is REQ-016 (credentials), not REQ-011 (human approval) — see `directives/REQ-016-credential-leak-guardrail.md` and `directives/REQ-011-human-approval-guardrail.md` for the correction. This version replaces that one, keyed on the real `REQ-XXX` ids. Later the same day, the entire backend was migrated from Node.js to Python/FastAPI+Pydantic per explicit user direction (see "Stack conflict" note below, now resolved) — file paths throughout this checklist reflect that migration.

Update this file's checkboxes as work lands; each `[x]` should be backed by a passing test or a verifiable grep, the same evidence standard `PROGRESS.md` requires. A `[x]` here means the requirement's own one-sentence statement is met — it does not always mean every acceptance criterion of every story that also fulfills it is met (noted inline where that gap exists).

## AI Evaluation
- [ ] REQ-005 — Claude returns structured findings (`rule_id`/`status`/`severity`/`evidence`/`reason`/`confidence`) for a valid submission and an error for an invalid one — a test asserts both shapes (STORY-004 AC1/AC2); not built, no Claude client exists yet
- [ ] REQ-014 *(constraint, unassigned — `fulfilled_by: []` in `plan.json`)* — Claude is called via the Anthropic API — grep for an `@anthropic-ai/sdk` dependency and a call site; not built, and no story in the current 12-story plan is assigned to build it

## API Design
- [x] REQ-015 *(constraint, unassigned — `fulfilled_by: []` in `plan.json`)* — the system exposes a typed API via FastAPI + Pydantic — root `requirements.txt` pins `fastapi`/`pydantic`; `backend/app/main.py` constructs a real `FastAPI()` app whose three routers (`reviews`, `security`, `basecamp`) all take/return Pydantic models from `backend/app/models.py`; `backend/app/test_main.py` (9/9 passing) exercises every route via `TestClient`, including a 422 on malformed input. Scope note: this covers the 3 endpoints that wrap already-built logic, not a full production API — REQ-002/003/004/etc. still have no endpoints since their underlying logic isn't built yet.

## Audit and History
- [ ] REQ-008 — a completed review's AI draft and human edits are both preserved and retrievable by an audit request — a test archives a completed review and asserts both are present (STORY-007 AC1/AC2); not built. Note: STORY-011's own audit-trail criterion (`Given a submission is processed, when an action is taken, then it is logged in the audit trail`) is explicitly `"passed": false` in `.colaberry/progress.json` right now — the trust-spine story left this the one criterion it did *not* close.

## Data Retrieval
- [x] REQ-004 — a Basecamp submission fetch includes comments, attachments, and links; an empty project returns an empty dataset — `backend/app/basecamp/test_submission_retrieval.py` asserts both (STORY-002 AC1/AC2), plus the audit log with timestamp and user id (AC3). **Verified against simulated Basecamp API responses only (session CC-20260925-dpme, 2026-09-25): not yet run on live data, because no Basecamp OAuth app is registered.** Live check: `backend/scripts/retrieve_submissions.py --project-id <id> --user-id <you>`

## Data Storage
- [ ] REQ-013 *(constraint, unassigned — `fulfilled_by: []` in `plan.json`)* — the system connects to Microsoft SQL Server — **partially built (session CC-20260924-e18o, 2026-09-25): retrieval only.** `pyodbc` + ODBC Driver 18 are pinned in `requirements.txt`, and `backend/app/db/` holds the typed config (`config.py`), a connection with a timeout, capped retries and classified errors (`connection.py`), schema inspection (`inspection.py`) and logged, parameterised queries (`queries.py`), all unit-tested. These were run read-only against the real server via `backend/scripts/check_db_connection.py` and `extract_st_history.py` (see `directives/ST-historical-comment-extraction.md`). Still open: *storage* (the app writes nothing to SQL Server; the Review Queue is in-memory), a least-privilege login, and a story in the plan that owns this requirement. Left unticked for those reasons.

## Error Handling
- [ ] REQ-009 — an ambiguous project ID and an ambiguous Stress Test ID both route to manual resolution rather than a guess — a test asserts both cases (STORY-008 AC1/AC2); not built
- [ ] REQ-010 — a failing external call retries a bounded number of times then either succeeds or surfaces a visible/logged error — a test mocks repeated failures and asserts the retry count is capped, never infinite (STORY-009 AC1/AC2); not built — no external call code exists in this repo yet to wrap

## Extensibility
- [ ] REQ-017 — a new Stress Test module (e.g. a fake "ST9") integrates purely via configuration, with zero changes to engine source — a test registers one and asserts the engine picks it up (STORY-010 AC1); not built

## Human Review
- [ ] REQ-006 — a reviewer can approve or edit AI findings, and both actions leave the result "prepared for posting" — a test exercises approve and edit and asserts the prepared-for-posting state (STORY-005 AC1/AC2); not built (only the downstream finalization *gate* exists — see REQ-011 — not the review-editing workflow itself)
- [x] REQ-011 — the system never auto-approves a submission; human review is mandatory — `backend/app/guardrails/test_review_finalization_guardrail.py` (9/9 passing) proves `assert_safe_to_finalize()` blocks finalization unless a genuine, non-AI, `approved` human decision is recorded, matching STORY-011 AC2 exactly; also exercised over HTTP via `POST /reviews/finalize-check` in `backend/app/test_main.py`; `.colaberry/progress.json`'s STORY-011 entry has this criterion locally marked `"passed": true`

## Integration
- [x] REQ-012 — Basecamp authentication uses OAuth 2.0 — `backend/app/basecamp/config.py` sends only `Authorization: Bearer <OAuth access token>` (no API key or password path; Basecamp offers none), and `backend/app/basecamp/oauth.py` + `backend/scripts/basecamp_oauth_setup.py` implement the Launchpad authorization-code flow (`test_config.py`, `test_oauth.py`). **Not yet exercised against real Launchpad: needs a registered app (client id/secret).**

## Marker Detection
- [x] REQ-001 — `##Critique##` is detected in a Basecamp comment with reasonable spacing/case variants normalized — `backend/app/basecamp/test_critique_marker_detector.py` (9/9 passing) asserts the four documented spacing variants and case variants trigger, and `Critique`/`#Critique`/`##Review##`/ordinary prose don't; also exercised over HTTP via `POST /basecamp/critique-marker/detect` (STORY-001 AC1/AC2, detection half)

## Review Completion
- [ ] REQ-007 — a review is marked `Completed` only once approved feedback is actually posted to Basecamp, and a posting error is retried/logged rather than silently marking Completed — a test asserts both (STORY-006 AC1/AC2); not built — the guardrail (REQ-011) exists, but nothing calls it yet since there's no finalize/post-to-Basecamp code path

## Review Queue
- [x] REQ-002 — detecting a marker creates a Review Queue row with status `Pending`, tied to the exact submission/version (comment id, not thread id) — a test asserts the row and its status (STORY-001 AC1) — `backend/app/review_queue/test_intake.py` and `backend/app/test_intake_routes.py` assert a Pending item keyed on `comment_id` (with `message_id` alongside), one item per comment on re-processing, and a separate item per new version; exposed via `POST /basecamp/comments/process` + `GET /reviews/queue`. Scope note (session CC-20260924-e18o): the queue is **in-memory only** (lost on restart) and comments arrive via fixtures/HTTP — no live `Basecamp_MessageBoards_MessageComments` (SQL Server) reader yet; both are recorded decisions, not gaps hidden here.

## Rule Application
- [ ] REQ-003 — loading rules for an ST0 submission returns only ST0-prefixed rules; an unknown Stress Test routes to manual resolution — a test asserts both (STORY-003 AC1/AC2); not built

## Security
- [x] REQ-016 — no credentials are stored in source code or shared documents — `python3 backend/scripts/scan_for_credentials.py` exits 0 ("No credential-shaped content found across 47 text files"); `backend/app/guardrails/test_credential_leak_guardrail.py` (12/12) passing; also exercised over HTTP via `POST /security/scan-credentials`; `.colaberry/progress.json`'s STORY-011 entry has this criterion locally marked `"passed": true`

## User Interface
- [ ] REQ-018 — the UI shows a pending review's full detail, and a completed review's status + history — a test/build asserts both views render (STORY-012 AC1/AC2); not built, no `frontend/` directory exists yet

---

## Not a requirement, but tracked and currently failing: the Command Center (STORY-000)

`.colaberry/progress.json` tracks a 13th, un-numbered story — **STORY-000, "Build your Command Center"** — with 5 of its own criteria, all currently `"passed": false`. It fulfills no `REQ-XXX` (per `STORIES.md`: "it belongs to no release and fulfils none of your requirements, because it is the window onto your system rather than a part of it"), so it's excluded from the 18-item list above, but it is real, platform-tracked work with its own 50 points.

Its criteria require an `index.html` **committed at the repo root**, reading `.colaberry/plan.json`/`progress.json`/`manifest.json` live at runtime (not hard-coded values), showing data staleness, and drilling down from every card. **The "Build" artifact published to claude.ai earlier this conversation does not satisfy this** — it's a separate, external, hand-authored summary of two pieces of work, not a repo-committed page reading the live JSON files. If STORY-000 credit matters, it needs its own build, following the exact brief in `docs/stories/STORY-000.md`.

## Stack conflict — resolved 2026-09-16

REQ-015 requires FastAPI + Pydantic (Python), but every module up to this point had been built in Node.js/CommonJS (a deliberate early assumption, logged when no toolchain was yet chosen). Flagged to the user rather than silently building around it or silently switching stacks; the user then explicitly directed the migration to Python/FastAPI+Pydantic. All three existing modules (both guardrails, the marker detector) were ported 1:1 — same logic, same reason codes, same test cases, now 39/39 passing under `pytest` — and wired into a real `FastAPI()` app with Pydantic request/response models. See the `PROGRESS.md` entry dated 2026-09-16 (session `CC-20260916-edil`) for the full change list.

REQ-013 (SQL Server) and REQ-014 (Anthropic API) are still `fulfilled_by: []` in `plan.json` — no story in the current 12-story plan builds either one. That gap is unrelated to the language choice and remains open.

## Not a requirement, but tracked separately: the local MCP server (2026-09-22)

`backend/app/mcp/server.py` (official `mcp` SDK) exposes one read-only resource, `basecamp://submissions`, and one tool stub, `finalize_review`, registered locally via `.mcp.json`. This is Claude-Code-integration tooling, not something `.colaberry/plan.json` tracks — it doesn't move any `REQ-XXX` checkbox above on its own.

The resource is honestly backed by sample data (see `backend/app/mcp/sample_data.py`) — it will become a genuine read of REQ-004/REQ-012 once the real Basecamp OAuth client exists, not before. The tool is a deliberate stub: it returns `{"status": "not_implemented", ...}` rather than pretending to finalize anything, since REQ-007's real finalize/post-to-Basecamp path still doesn't exist. Verified end-to-end (not just imported) via `backend/app/mcp/test_server.py`, which spawns the server as a real subprocess and drives it with the official `mcp` client over stdio — 2/2 passing, part of the 41/41 `pytest` total.
