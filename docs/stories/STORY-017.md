# STORY-017 — Recognise Marker Variants and Handle Submission Versions

As the review system, I want to recognise the real critique markers and tell one submission version from another, so that a re-submitted piece of work gets its own review and the earlier one is not lost.

**Release:** r0 · Initial Integration and Detection (weeks 1–2)
**Owner:** System
**Blocked by:** nothing — you can start this now

## The requirement this satisfies

- **REQ-023** (Functional, must) — The system must recognise reasonable ##Critique## marker variations, ignore near-misses, identify the thread by MessageId and the version by CommentId, and create a new review for a later version while preserving the previous one.

## How to build it

Build exactly what the acceptance lines describe, from the Master Project Specification section this story came from.

## Failure paths you must handle


## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given a comment containing ##Critique##, ## Critique##, ##Critique ## or ## Critique ##, when it is processed, then the marker is normalised and a review is created.
- [ ] Given a comment containing plain Critique, #Critique, ##Review##, or prose that merely uses the word critique, when it is processed, then no review is created.
- [ ] Given a detected marker, when the review is created, then MessageId identifies the Basecamp thread and CommentId identifies the exact submission version, and IsSubmitted is never used as the version identifier.
- [ ] Given a later version of the same submission carrying a new critique marker, when it is processed, then a new review is created and the previous review is preserved for history.
- [ ] Trust: every detection logs the normalised marker, the MessageId and the CommentId it was taken from.

When every box above is ticked, stop and show the demo.
