# STORY-021 — Review Images and Screenshots as Evidence

As a reviewer, I want the AI to actually look at the screenshots a student submitted, so that a rule about a dataset screenshot is judged on the image rather than on the text around it.

**Release:** r1 · Rule Application and AI Evaluation (weeks 3–4)
**Owner:** System
**Blocked by:** nothing — you can start this now

## The requirement this satisfies

- **REQ-027** (Functional, must) — The system must include images and screenshots from Basecamp as visual evidence in the review, and preserve the queue item with a visible integration error when that material cannot be retrieved.

## How to build it

Build exactly what the acceptance lines describe, from the Master Project Specification section this story came from.

## Failure paths you must handle


## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given a submission whose material includes images or screenshots, when the review runs, then those images are retrieved from Basecamp and included in the evaluation as visual evidence.
- [ ] Given a rule that depends on visual evidence such as ST0-004, when the image is missing or unreadable, then the rule is reported as Required Fix with the reason and is never silently passed.
- [ ] Given Basecamp material cannot be retrieved, when retrieval fails, then the queue item is preserved and the integration error is shown, rather than the review continuing without the evidence.
- [ ] Trust: every image used in an evaluation is logged with its Basecamp source id, and no submitted image is written into the repository.

When every box above is ticked, stop and show the demo.
