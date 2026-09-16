# STORY-006 — Post Final Feedback to Basecamp

As a system, I want to post final feedback to Basecamp, so that the review process is completed.

**Release:** r2 · Human Review Workflow (weeks 5–6)
**Owner:** System
**Blocked by:** STORY-005

## The requirement this satisfies

- **REQ-007** (Functional, must) — The system must mark reviews as 'Completed' only after human review and Basecamp posting are both done.

## How to build it

Implement feedback posting logic using Basecamp's REST API, ensuring retries on failure.

## Failure paths you must handle

- Basecamp API is unreachable
- Feedback data is malformed
- Posting exceeds time limit

## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given approved feedback, When the system posts it to Basecamp, Then the review is marked 'Completed'.
- [ ] Given a posting error, When the system retries, Then it eventually succeeds or logs an error.
- [ ] Trust: The system logs posting events with feedback ID and status.

When every box above is ticked, stop and show the demo.
