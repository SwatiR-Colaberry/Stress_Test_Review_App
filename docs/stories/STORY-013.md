# STORY-013 — Historical Retrieval with a Vector Database

As a reviewer, I want the AI draft to draw on similar past reviews from the same Stress Test, so that feedback stays consistent with how we reviewed before.

**Release:** r1 · Rule Application and AI Evaluation (weeks 3–4)
**Owner:** System
**Blocked by:** STORY-003 (Load ST0 Rule Module) — retrieval filters by Stress Test and rule id, so the rule module must exist first. *(Added in the repo 2026-09-25; the portal form had no blocked-by field.)*

## The requirement this satisfies

- **REQ-019** (Functional, should) — Historical Retrieval with a Vector Database

> **Intended wording (not yet in the portal, 2026-09-25):** REQ-019 was auto-created from the story title, with cluster "Marker Detection" and priority "should". The intended requirement is: *"The system must retrieve a small set (top 5–10) of relevant historical reviews for a submission, filtered to the same Stress Test and ranked by semantic similarity using a vector database stored outside SQL Server, without changing existing SQL Server tables or procedures."* — cluster Historical Retrieval, priority must. Correct it in the portal; `plan.json` is not edited by hand so the plan keeps syncing.

## How to build it

Implement exactly what the acceptance lines describe for this story, and nothing that belongs to another one.

Guidance (Master Spec §14–15, Figure 4, and user decisions of 2026-09-25):

- **First data to index:** the per-Stress-Test history extract, `data/extracts/<date>-per-stress-test/` (15 most recent approved projects for each of ST0–ST5; see `directives/ST-historical-comment-extraction.md`). Later, completed reviews from this app are added to the same index (STORY-007).
- **Retrieval order:** filter by Stress Test (and rule id once STORY-003 exists), then rank by vector similarity, then return the top 5–10.
- **Storage:** the vector database lives outside SQL Server; existing SQL Server tables and procedures must not change. The index holds student text and personal data, so it stays out of git like `data/extracts/`.
- **Choose the vector database and embedding service at the start of the story.** Both are new dependencies (and the embedding service may be a paid external service), so they need approval before they are added.
- Every external call (embedding service, vector database) gets an explicit timeout and capped retries; indexing the same case twice must not create a duplicate entry.

## Failure paths you must handle

- Vector database unreachable
- Embedding generation fails
- No similar historical cases found

## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given historical critique and feedback comments for a Stress Test are indexed in a vector database stored outside SQL Server, when a new submission for that Stress Test is reviewed, then the system returns the top 5–10 most similar cases from that same Stress Test only.
- [ ] Given a submission for one Stress Test, when historical cases are retrieved, then no case from a different Stress Test is returned.
- [ ] Given the vector database or the embedding service is unavailable, when retrieval runs, then the review continues without historical examples and the error is shown to the reviewer.
- [ ] Given no similar historical cases exist, when retrieval runs, then the system returns an empty list and says so, rather than failing.
- [ ] Trust: Historical examples never override the current Stress Test rules, and existing SQL Server tables and procedures are never changed.

When every box above is ticked, stop and show the demo.
