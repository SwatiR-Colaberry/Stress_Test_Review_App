# REQ-011 — Human-Approval Safety Guardrail

**Fulfils:** REQ-011 (Safety, must) — "The system must not auto-approve any submission; human review is mandatory." Part of **STORY-011**, criterion 2: "Given a submission is processed without human review, when the system attempts to auto-approve, then it blocks the action."

> **Correction:** this file was originally written and named as "R4" before `.colaberry/plan.json` existed locally. Now that the canonical plan is synced, `derived.guardrails[]` shows R4 is actually **REQ-016** (see `directives/REQ-016-credential-leak-guardrail.md`) — the credential-leak check. This file's content still stands on its own merits (it satisfies REQ-011 / STORY-011 criterion 2, a real safety requirement); only the "R4" label was wrong.

## What "safe" means here

Per the Master Project Specification (`docs/01-Master-Project-Specification.md`, §22 Status Model and §26 MVP Acceptance Criteria) and `docs/stories/STORY-011.md`:

- "Completed must never mean 'AI finished.' It means human review is finished and final feedback has been accepted/delivered." (§22)
- "Review is marked Completed only after human review." (§26)
- "AI never final-approves a submission." (§26)

An **unsafe result**, for this application, is defined precisely as: **a review reaching `Completed` status — i.e. final feedback being posted to Basecamp — without a genuine, recorded human reviewer approval.** Any code path that can post to Basecamp or set `status = 'Completed'` without that approval is a safety violation, regardless of how good the AI's draft is.

## The check that enforces it

`backend/src/services/guardrails/reviewFinalizationGuardrail.js` exports `assertSafeToFinalize(review)`. It must be called — and must not throw — before any code finalizes a review (marks it `Completed`) or posts `finalFeedbackText` to Basecamp. It rejects (throws `UnsafeFinalizationError`, `errorClass: 'ContractViolation'`) when:

| Reason code | Condition | Maps to |
|---|---|---|
| `NO_HUMAN_REVIEW` | No `reviewerDecision` recorded at all | "Review is marked Completed only after human review" |
| `MISSING_REVIEWER_IDENTITY` | Decision has no reviewer id | An unattributed decision is not a human decision |
| `AI_CANNOT_APPROVE` | Reviewer id is a known AI/system actor, or matches the review's own `aiDraftAuthorId` | "AI never final-approves a submission" |
| `NOT_APPROVED` | Decision outcome is `pending` or `rejected`, not `approved` | Only an explicit approval finalizes a review |
| `EMPTY_FEEDBACK` | `finalFeedbackText` is blank | Nothing is posted to Basecamp with no content |

The function is pure, synchronous, and dependency-free by design: it does not touch the database, Basecamp, or Claude, so it can be unit tested in isolation today and reused unchanged once the real finalize / post-to-Basecamp path is built in Phase 4 (§25).

## Acceptance evidence

`backend/src/services/guardrails/reviewFinalizationGuardrail.test.js` passes and covers: the happy path (genuine human approval), every rejection reason code above, and an idempotency check (the same input evaluated twice yields the same result). Runs via `npm test` with zero additional setup.

This satisfies STORY-011 criterion 2 today. STORY-011 criterion 1 (audit trail logging) is not yet built and is out of scope for this guard — it depends on the database layer, which doesn't exist yet (§27).

## Known limitation (logged, not solved here)

`AI_CANNOT_APPROVE` currently detects AI/system identities with a static denylist (`ai`, `claude`, `claude-ai`, `system`, `bot`, `automation`) plus an exact match against the review's own `aiDraftAuthorId`. Once reviewer authentication/SSO is defined (§27), this should be replaced with a positive check — "reviewerId belongs to a known human reviewer account" — instead of a denylist. Tracked here so it isn't lost before Phase 4.
