# STORY-019 — Evaluate ST0 Rules ST0-001 to ST0-008

As a reviewer, I want each ST0 rule reported with its own result, so that I can see exactly which requirement a submission missed rather than a single overall verdict.

**Release:** r1 · Rule Application and AI Evaluation (weeks 3–4)
**Owner:** System
**Blocked by:** nothing — you can start this now

## The requirement this satisfies

- **REQ-025** (Functional, must) — The system must evaluate rules ST0-001 to ST0-008 and report each outcome as PASS, Required Fix or Needs Attention, never as PASS when a rule could not be evaluated.

## How to build it

Build exactly what the acceptance lines describe, from the Master Project Specification section this story came from.

## Failure paths you must handle


## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given a submission, when Stage 1 runs, then each rule from ST0-001 to ST0-008 is evaluated and reported with its own result of PASS, Required Fix or Needs Attention.
- [ ] Given the data collection explanation is missing or not separate from the dataset description, when ST0-003 is reported, then it is Needs Attention rather than Required Fix.
- [ ] Given a rule whose input is missing so it cannot be judged, when results are produced, then it is reported as unevaluated with the reason and never as PASS.
- [ ] Trust: every rule result is logged with its rule id, the evidence it was judged from, and the rule module version.

When every box above is ticked, stop and show the demo.
