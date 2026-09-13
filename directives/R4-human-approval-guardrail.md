# R4 — Human-Approval Safety Guardrail

**Status:** PLANNED (was UNMAPPED)
**Fulfils:** R4 — "the application must never produce an unsafe result"

## What "safe" means here

Per the Master Project Specification (`docs/01-Master-Project-Specification.md`, §22 Status Model and §26 MVP Acceptance Criteria):

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

## Acceptance criterion (moves R4 UNMAPPED → PLANNED)

R4 is PLANNED when all of the following hold:

1. `assertSafeToFinalize()` exists and is documented as the single required gate before any "mark Completed" / "post final feedback to Basecamp" operation.
2. `backend/src/services/guardrails/reviewFinalizationGuardrail.test.js` passes and covers: the happy path (genuine human approval), every rejection reason code above, and an idempotency check (the same input evaluated twice yields the same result).
3. `npm test` runs the suite with zero additional setup.

R4 advances beyond PLANNED only once a real finalize / post-to-Basecamp code path in Phase 4 actually calls this guard, and that call is covered by an integration test — that wiring is out of scope for PLANNED and depends on the Basecamp integration (§27) not yet existing.

## Known limitation (logged, not solved here)

`AI_CANNOT_APPROVE` currently detects AI/system identities with a static denylist (`ai`, `claude`, `claude-ai`, `system`, `bot`, `automation`) plus an exact match against the review's own `aiDraftAuthorId`. Once reviewer authentication/SSO is defined (§27), this should be replaced with a positive check — "reviewerId belongs to a known human reviewer account" — instead of a denylist. Tracked here so it isn't lost before Phase 4.
