# AI Draft Evaluation — how a submission is reviewed by Claude

**Serves:** STORY-004 (REQ-005: Claude evaluates submissions against the loaded rules and returns structured draft findings). Also meets REQ-014 (Claude via the Anthropic API). Builds on STORY-002 (submission data) and STORY-003 (rule modules). Feeds STORY-005 (human review): the result is a **draft**; a human reviewer decides everything.

## What it does

`evaluate_submission()` in `backend/app/evaluation/evaluate.py` takes one retrieved submission, the id of the `##Critique##` comment to review, and the loaded rule module, and returns an `EvaluationResult` (`backend/app/models.py`):

- `passed_rule_ids`: rules the submission meets;
- `findings`: one `DraftFinding` per rule that FAILs, or is ADVISORY (cannot be judged from text, e.g. what a screenshot shows; the reviewer checks it), with `rule_id`, `status`, `severity` (always the rule module's, not Claude's), `evidence`, `reason`, `suggested_feedback`, `confidence`;
- `stages_evaluated`, the deterministic `prechecks`, and token `usage`.

It has no approval or status field: an AI evaluation can never approve a submission (REQ-011).

| File | Role |
|---|---|
| `text.py` | Comment HTML → plain text. The yellow highlight (`rgb(250, 247, 133)` or Basecamp's `var(--highlight-bg-1)`) becomes `[SELECTED]…[/SELECTED]`; embedded files become `[image: name]` / `[file: name]`. |
| `input_check.py` | Rejects before any Claude call: `COMMENT_NOT_FOUND`, `NOT_A_SUBMISSION` (a reviewer's comment), `SUBMISSION_EMPTY` (incl. screenshot-only), `SUBMISSION_TOO_LARGE`, `RULES_NOT_LOADED`. |
| `prechecks.py` | Counted by code and passed to Claude as hints: problem count (from field labels; `None` when it cannot be told), `[SELECTED]` blocks, links (anchors and bare URLs), dataset links, dataset files, images. |
| `prompt.py` | System prompt = the rule module only (no dates or ids: cached); user message = one stage's rule ids + pre-checks + the submission inside `<submission>` tags, labelled as data. |
| `claude_client.py` | The only place that calls Claude (official `anthropic` SDK). |
| `store.py` | Local git-ignored stores: results, in-progress locks, usage ledger. |
| `thread.py` | Reads a thread: version number, split parts, previous reviewer feedback. Built; not yet used by the evaluator (see "Not yet"). |
| `fake.py` | `ScriptedEvaluator`, a fake Claude for tests and the demo. |

## The token-saving rules (user decisions, 2026-09-28)

1. A stable system prompt (the rule module) goes first with a cache marker; later calls read it from the cache.
2. Plain text, not HTML; the highlight survives as `[SELECTED]`.
3. Deterministic pre-checks first, passed to Claude.
4. Structured output via `output_config.format` (`ClaudeStageAnswer`).
5. Passes come back as a list of ids; only FAIL/ADVISORY get full findings; tight field limits (300/300/400 characters) and a `max_tokens` cap.
6. If Stage 1 has a FAIL, Stage 2 is never sent.
7. Effort `low` (or `medium`).
8. Idempotent on `(comment_id, rule_version)`: a stored result is returned without calling Claude. Only success blocks a later call; after a failure a re-run is allowed.
9. `count_tokens` before sending; above `EVALUATION_MAX_INPUT_TOKENS` → manual resolution.
10. Usage (input, cache write, cache read, output) logged per call; `EVALUATION_DAILY_TOKEN_LIMIT` refuses a call whose worst case would pass it.
11. Explicit timeout and at most 2 retries.
12. Audit events: `evaluation_started`, one `evaluation_finding` per evaluated rule (comment id + rule id + PASS/FAIL/ADVISORY), `evaluation_completed`; `evaluation_failed` / `evaluation_manual_resolution` with a reason code; `evaluation_already_done` on a replay.

## Configuration (`.env`, git-ignored; names in `.env.example`)

| Variable | Default | Allowed |
|---|---|---|
| `ANTHROPIC_API_KEY` | — (required for live calls) | a key scoped to one workspace; never logged |
| `EVALUATION_MODEL` | `claude-sonnet-5` | |
| `EVALUATION_EFFORT` | `low` | `low`, `medium` |
| `EVALUATION_TIMEOUT_S` | 60 | 10–300, per attempt |
| `EVALUATION_MAX_RETRIES` | 2 | 0–2 |
| `EVALUATION_MAX_TOKENS` | 4000 | 500–16000, output incl. thinking |
| `EVALUATION_MAX_INPUT_TOKENS` | 20000 | above: manual resolution |
| `EVALUATION_DAILY_TOKEN_LIMIT` | 500000 | all tokens per UTC day |

The scripts read `.env` **over** the shell environment, so a different `ANTHROPIC_API_KEY` left in the shell by another project is not used (it caused a 401 on 2026-09-28).

## Failures

| When | What happens | Retry | Recovery |
|---|---|---|---|
| Submission incomplete or not a submission | `SubmissionIncompleteError` with a reason code; `evaluation_failed`; nothing stored | no | fix the submission / manual review |
| Claude unreachable, 429, 5xx | retried twice (1 s, 2 s; `Retry-After` honoured up to 30 s), then `ClaudeUnavailableError` | ≤ 2 | re-run later; nothing was stored |
| Attempt over `EVALUATION_TIMEOUT_S` | as above, then `EvaluationTimeoutError` | ≤ 2 | re-run later |
| Key rejected (401/403) | `ClaudeAuthError`, not retried | no | fix the key in `.env` |
| Reply cut off, refused, off-schema, or missing/extra rule ids | `MalformedReplyError` / `EvaluationRefusedError` / `RuleCoverageError`; its tokens still counted | no | re-run, or manual review |
| Too many input tokens | `evaluation_manual_resolution` (`INPUT_TOO_LARGE`) | no | manual review |
| Daily token limit | `DailyTokenLimitExceededError` before sending | no | next UTC day, or raise the limit |
| Result cannot be stored | `evaluation_failed` (`EvaluationStoreError`) | no | fix the disk; re-run pays again |
| Another run on the same version | `EvaluationInProgressError` (lock); a crashed run's lock is taken over after 60 min | — | wait |

**Not handled:** a timed-out call reports no usage, so the ledger can undercount; the result store and the audit trail are not written in one transaction (a failed audit write after storing is re-raised; a re-run returns the stored result without paying again).

## Running it

```
.venv/bin/python backend/scripts/evaluate_demo.py                    # fake Claude: the acceptance demo, free
.venv/bin/python backend/scripts/compare_st0_history.py              # historical comparison, DRY RUN: count_tokens + cost estimate, free
.venv/bin/python backend/scripts/compare_st0_history.py --run --yes  # PAID: evaluates the cases, writes data/evaluations/comparison/report.md
```

The comparison takes, per ST0 thread in the history extract, the first reviewer `##FeedbackGiven##` comment and the last genuine student `##Critique##` before it. Markers are read from the comment text, not the extract's `MarkerType` column: SQL labels a comment by its first marker, so a reviewer's reply quoting `##Critique##` would otherwise be graded as a submission (4 of the first 15 cases on 2026-09-28). The case's thread stops at the critique, so Claude never sees the feedback that answers it.

**2026-09-28 result:** 15 historical ST0 submissions, 15/15 schema-valid answers, cache hit on every call after the first, $0.26 in total (21 calls, incl. 5 discarded evaluations of reviewer comments). Agreement is shown as keyword hints next to the reviewer's own words in the git-ignored report; read it, do not trust the counts alone.

## Not yet

- Reviewer notes from the rule module (`CONTENT_NOT_IN_TEXT`: the submission is in a Word file; `SPLIT_SUBMISSION`) are not produced; such a submission gets FAILs.
- The evaluator reads only the reviewed comment. Next: a thread history store, and passing Claude the split parts plus a short list of what the reviewer asked for last time, so a resubmission is checked against it.
- A reviewer who posts a bare `##Critique##` (no other marker) is still queued by the intake; telling reviewers from students needs the critiquer list.

## How success is verified

1. `.venv/bin/python -m pytest backend -q` passes (evaluation tests use a fake Claude or a mocked HTTP transport; `backend/conftest.py` removes every Anthropic credential so no test can call the paid API).
2. `.venv/bin/python backend/scripts/evaluate_demo.py` prints structured findings for comment 2002, `SUBMISSION_EMPTY` for comment 3003, "Claude calls in total: 1" after the replay, and `evaluation_finding … rule ST0-00n` audit lines.
3. `.venv/bin/python backend/scripts/scan_for_credentials.py` is clean.
4. Optional, live: the dry run prints per-case token counts and a cost estimate without evaluating anything.
