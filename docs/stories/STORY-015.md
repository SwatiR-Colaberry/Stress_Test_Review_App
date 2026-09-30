# STORY-015 — Images in Reviewer Feedback

As a reviewer, I want to attach images such as annotated screenshots to my feedback points, so that students see exactly what I mean, as I do in Basecamp today.

**Release:** r2 · Human Review Workflow (weeks 5–6)
**Owner:** System
**Blocked by:** nothing — you can start this now

## The requirement this satisfies

- **REQ-021** (Functional, should) — The system must let a reviewer attach images to a finding and post them to Basecamp alongside the written feedback.

## How to build it

Implement exactly what the acceptance lines describe for this story, and nothing that belongs to another one.

## Failure paths you must handle


## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given a finding under review, when I attach a PNG, JPG or GIF under 10 MB, then it is saved with that finding and shown in my preview
- [ ] Given a file that is not an image or is over 10 MB, when I attach it, then it is refused with a message and nothing is saved
- [ ] Given prepared feedback with images, when it is posted to Basecamp, then each image appears in the posted comment next to its point
- [ ] Given a posting retry, when the same feedback is posted again, then each image appears in Basecamp only once
- [ ] Trust: every image attached, removed or uploaded is logged with reviewer and time, and images are never committed to the repo

When every box above is ticked, stop and show the demo.
