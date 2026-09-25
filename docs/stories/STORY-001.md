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

> **Added 2026-09-25 (user decision):** `##Please Critique##` (any case/spacing) also counts as a critique request. It creates the Pending review item like `##Critique##`, but the item carries a note for the reviewer to remind the student: *"next time, just write ##Critique##"*. `#Critique#` and plain prose still do not count. See `backend/app/basecamp/critique_marker_detector.py` (`classify_critique_marker`) and `backend/app/review_queue/intake.py`.

## Failure paths you must handle

- Comment does not contain a valid marker
- Basecamp API is unreachable
- Comment data is malformed

## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [x] Given a Basecamp comment with '##Critique##', When the system processes the comment, Then a review item is created with status 'Pending'.
- [x] Given a comment with '## Review ##', When the system processes the comment, Then no review item is created.
- [x] Trust: The system logs the detection event with the exact comment ID.

When every box above is ticked, stop and show the demo.
