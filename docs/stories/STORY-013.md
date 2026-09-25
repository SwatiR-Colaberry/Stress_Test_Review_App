# STORY-013 — Historical Retrieval with a Vector Database

As a reviewer, I want the AI draft to draw on similar past reviews from the same Stress Test, so that feedback stays consistent with how we reviewed before.

**Release:** r1 · Rule Application and AI Evaluation (weeks 3–4)
**Owner:** System
**Blocked by:** nothing — you can start this now

## The requirement this satisfies

- **REQ-019** (Functional, should) — Historical Retrieval with a Vector Database

## How to build it

Implement exactly what the acceptance lines describe for this story, and nothing that belongs to another one.

## Failure paths you must handle


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
