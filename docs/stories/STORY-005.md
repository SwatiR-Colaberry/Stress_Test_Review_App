# STORY-005 — Human Review of AI Findings

As a human reviewer, I want to review AI findings, so that I can approve, edit, or reject them before posting feedback.

**Release:** r2 · Human Review Workflow (weeks 5–6)
**Owner:** Human Reviewer
**Blocked by:** STORY-004

## The requirement this satisfies

- **REQ-006** (Functional, must) — Human reviewers must be able to approve, edit, reject, or add findings before final feedback is posted back to Basecamp.

## How to build it

Develop a web UI for reviewers to manage and edit AI findings before final approval.

## Failure paths you must handle

- Reviewer UI fails to load
- Edits are not saved
- Network issues during feedback posting

## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given AI findings, When a reviewer approves them, Then feedback is prepared for Basecamp posting.
- [ ] Given AI findings, When a reviewer edits them, Then the edits are saved and prepared for posting.
- [ ] Trust: The system logs all reviewer actions with timestamps.

When every box above is ticked, stop and show the demo.
