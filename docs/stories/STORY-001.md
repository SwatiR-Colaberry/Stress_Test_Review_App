# STORY-001 — Detect Critique Marker in Basecamp

As a system, I want to detect critique markers in Basecamp comments, so that I can create review items.

**Release:** r0 · Initial Integration and Detection (weeks 1–2)
**Owner:** System
**Blocked by:** nothing — you can start this now

## The requirement this satisfies

- **REQ-001** (Functional, must) — The system must detect a '##Critique##' marker in Basecamp comments, normalizing reasonable spacing and case variants.
- **REQ-002** (Functional, must) — The system must create a Review Queue item with status 'Pending' for each detected critique marker, tied to the exact submission/version.

## How to build it

Implement marker detection logic reading Basecamp_MessageBoards_MessageComments directly.

## Failure paths you must handle

- Comment does not contain a valid marker
- Basecamp API is unreachable
- Comment data is malformed

## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given a Basecamp comment with '##Critique##', When the system processes the comment, Then a review item is created with status 'Pending'.
- [ ] Given a comment with '## Review ##', When the system processes the comment, Then no review item is created.
- [ ] Trust: The system logs the detection event with the exact comment ID.

When every box above is ticked, stop and show the demo.
