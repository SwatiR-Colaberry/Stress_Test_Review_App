# Acceptance Checklist

One-line, repo-verifiable acceptance checks derived from [`01-Master-Project-Specification.md`](01-Master-Project-Specification.md) and [`directives/R4-human-approval-guardrail.md`](../directives/R4-human-approval-guardrail.md). Each line names a concrete artifact (a file, a test, a grep) rather than a narrative description — the check should be answerable by looking at the repo, not by trusting a claim.

Update this file's checkboxes as work lands; each `[x]` should be backed by a passing test or a verifiable grep, the same evidence standard `PROGRESS.md` requires.

## Marker Detection & Versioning (§4, §23, §26)
- [x] Recognizes `##Critique##` variants, rejects near-misses — `backend/src/services/basecamp/critiqueMarkerDetector.test.js` asserts `##Critique##`/`## Critique##`/`##Critique ##`/`## Critique ##` trigger and `Critique`/`#Critique`/`##Review##` don't
- [ ] `CommentId` (not `IsSubmitted`) is the version identity key — grep marker/intake source shows review rows keyed on `CommentId`, with no code path keying on `IsSubmitted`
- [ ] One review record per submission version, even on retries — a test posts the same critique event twice and asserts exactly one row is created
- [ ] New critique on a later version creates a new review, preserving the old one — a test with two `CommentId`s asserts two rows exist and the first is unchanged

## Identification & Retrieval (§2, §6, §23)
- [ ] Ambiguous project/Stress-Test/submission routes to manual resolution, never guessed — a test feeding an ambiguous event asserts a manual-resolution state, not an auto-assigned module
- [ ] Failed Basecamp retrieval preserves the queue item with a surfaced integration error — a test mocking a fetch failure asserts the review row survives with an error state, not deletion or silent completion

## Rule Architecture & ST0 Scope (§7, §8, §9, §10, §11, §12)
- [ ] Rules are versioned config, not baked into prompts — a `stress_test_rules`/`docs/stress-test-rules` artifact carries `rule_id`/`rule_version` fields, and no ST0 rule text is hard-coded in prompt-builder source
- [ ] Rule IDs `ST0-001`–`ST0-008` exist and are the sole IDs the ST0 module emits — grep the ST0 rule module for exactly these IDs, no modeling/forecasting/strategy rule IDs present
- [ ] Stage 2 never runs before Stage 1 passes — a test asserts zero Stage-2 findings when a Stage-1 fixture fails
- [ ] Stage 1 failures are reported together, uncontaminated by Stage 2 — a failing-Stage-1 fixture test asserts only Stage-1 rule IDs appear in the result
- [ ] Dataset advisory (Stage 3) can never flip to a structural failure — a test asserts Stage-3 findings always carry `status: ADVISORY`, never affecting overall pass/fail
- [ ] Missing problem fields are pinpointed by problem number + field name — a fixture missing "Target Audience" on problem 4 asserts the finding names problem 4 and that exact field
- [ ] Heading-wording variance doesn't cause false failures — a fixture with varied casing/numbering/singular-plural headings asserts no false-negative finding
- [ ] Exactly one selected problem is enforced (ST0-008) — a test asserts 0-selected and 2-selected fixtures both fail, 1-selected passes
- [ ] Submission is never auto-approved — grep every code path that sets `status = 'Completed'` and confirm each calls `assertSafeToFinalize()` (`backend/src/services/guardrails/reviewFinalizationGuardrail.js`) first

## AI Finding Structure (§13, §26)
- [ ] Every finding carries `rule_id`, `status`, `severity`, `evidence`, `reason`, `suggested_feedback`, `confidence` — a schema (Zod/TS type) rejects a finding object missing any of the seven fields
- [ ] Prompt sent to Claude contains only the identified Stress Test's rules — a test asserts the ST0 prompt payload contains no rule text from another module

## Human Review & Finalization Safety (§9, §22, §24)
- [x] Review can never be finalized without genuine human approval — `npm test` runs `reviewFinalizationGuardrail.test.js`, 9/9 passing (happy path + all 5 rejection codes + idempotency)
- [x] AI/system identity can't supply the approving decision — same suite asserts `AI_CANNOT_APPROVE` throws for denylisted/self-authored reviewer ids
- [ ] Reviewer can approve/edit/reject/add findings — a reviewer-decision type/enum test exercises each of the four outcomes
- [ ] Completed requires both human approval AND successful Basecamp post — a test simulating a failed post asserts `status` never reaches `Completed`

## Historical Retrieval (§14, §15, §26)
- [ ] Retrieval narrows SQL → rule match → domain → full-text → vector, in order — a retrieval-service test asserts call order and short-circuiting when earlier layers return enough
- [ ] Claude never receives more than 5–10 historical cases — a test asserts the retrieval function's return length is capped at 10 regardless of upstream candidate count
- [ ] Historical examples never override current rules — a test with a conflicting historical case asserts the finding's outcome matches the current rule module, not the precedent

## Error Handling (§23)
- [ ] Unsupported Stress Test never borrows another module's rules — a test requesting an unimplemented module returns an error/manual-resolution state, not ST0 fallback
- [ ] Claude/API failure retries with a bounded count, retains queue item + error state — a test mocks repeated failures and asserts the retry count is capped (no infinite loop) and the row persists

## Security & Audit (§18, §24)
- [ ] No secrets in source or history — a secret scan (e.g. `git log -p | grep -E` for key patterns, or `trufflehog`) over the repo returns zero hits
- [ ] AI draft and human-final feedback are stored separately — schema has distinct `ai_draft_feedback`/`final_feedback_text` columns, and a test asserts editing final feedback doesn't mutate the stored draft
- [ ] Reviewer identity + completion timestamp recorded — audit table schema includes `reviewer_id` and `completed_at`, populated by a completion test
- [ ] Rules are versioned so old reviews interpret against contemporaneous rules — rule schema has a `rule_version`/effective-date field, and a test asserts a stored historical review keeps its original `rule_version` after the active rule set changes
