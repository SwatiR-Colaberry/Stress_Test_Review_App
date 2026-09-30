# STORY-022 — Track Review Status Through the Full Model

As a reviewer, I want a case to move through Pending, In Review, Feedback Generated and Completed, so that the queue tells me what is waiting on me and what is waiting on the AI.

**Release:** r2 · Human Review Workflow (weeks 5–6)
**Owner:** System
**Blocked by:** nothing — you can start this now

## The requirement this satisfies

- **REQ-028** (Functional, must) — The system must track a review through Pending, In Review, Feedback Generated and Completed, where Completed means a human finished the review, never that the AI finished.

## How to build it

Build exactly what the acceptance lines describe, from the Master Project Specification section this story came from.

## Failure paths you must handle


## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given a detected critique marker, when the review is created, then its status is Pending.
- [ ] Given a reviewer opens a case, when they start work on it, then the status becomes In Review.
- [ ] Given the AI draft has been produced and stored, when that completes, then the status becomes Feedback Generated.
- [ ] Given a human reviewer finalises the review and the final feedback is posted or stored, when that completes, then the status becomes Completed, and the system never sets Completed because the AI finished.
- [ ] Trust: every status change is logged with the previous status, the new status, who changed it and when.

When every box above is ticked, stop and show the demo.
