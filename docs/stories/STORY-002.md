# STORY-002 — Retrieve Submission Data from Basecamp

As a reviewer, I want to retrieve all necessary submission data from Basecamp, so that I can perform a comprehensive review.

**Release:** r0 · Initial Integration and Detection (weeks 1–2)
**Owner:** system
**Blocked by:** nothing — you can start this now

## The requirement this satisfies

- **REQ-004** (Functional, must) — The system must retrieve all necessary submission data from Basecamp, including comments, attachments, and links.
- **REQ-012** (Constraint, must) — The system must use Basecamp's OAuth 2.0 for authentication and authorization.

## How to build it

Use Basecamp API to fetch project data including comments, attachments, and links. Ensure OAuth tokens are securely managed.

## Failure paths you must handle

- Basecamp API rate limits exceeded
- Invalid OAuth token
- Network failure during data retrieval

## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given a Basecamp project with submissions, when the system retrieves data, then it includes comments, attachments, and links.
- [ ] Given a Basecamp project with no submissions, when the system attempts to retrieve data, then it returns an empty dataset.
- [ ] Trust: The system logs all data retrieval actions with timestamps and user IDs.

When every box above is ticked, stop and show the demo.
