# STORY-007 — Preserve Review History

As a system, I want to preserve review history, so that audits can be conducted on AI drafts and human edits.

**Release:** r3 · Audit and History (weeks 7–8)
**Owner:** System
**Blocked by:** STORY-006

## The requirement this satisfies

- **REQ-008** (Safety, must) — The system must preserve the history of each review, including AI drafts and human edits, for audit purposes.

## How to build it

Develop archival logic to store AI drafts and human edits separately in the database.

## Failure paths you must handle

- Archival process fails
- History retrieval is incomplete
- Database connection issues

## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given a completed review, When the system archives it, Then both AI drafts and human edits are preserved.
- [ ] Given an audit request, When the system retrieves history, Then it shows all relevant actions and timestamps.
- [ ] Trust: The system logs all archival events with review ID.

When every box above is ticked, stop and show the demo.
