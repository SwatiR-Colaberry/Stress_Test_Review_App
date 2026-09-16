# STORY-009 — Implement Error Handling for External Calls

As a system, I want to handle errors in external API calls, so that I can maintain system stability.

**Release:** r4 · Error Handling and Extensibility (weeks 9–10)
**Owner:** System
**Blocked by:** STORY-007

## The requirement this satisfies

- **REQ-010** (Safety, must) — The system must retry external API calls safely within a bounded number of attempts and surface visible errors if they fail.

## How to build it

Develop error handling logic for external API calls, ensuring retries and error logging.

## Failure paths you must handle

- API call exceeds retry limit
- Network issues persist
- Error logging fails

## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given an API call failure, When the system retries, Then it succeeds or logs an error after bounded attempts.
- [ ] Given a network issue, When the system detects it, Then it surfaces a visible error state.
- [ ] Trust: The system logs all API call attempts and outcomes.

When every box above is ticked, stop and show the demo.
