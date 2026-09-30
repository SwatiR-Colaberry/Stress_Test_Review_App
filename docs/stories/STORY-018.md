# STORY-018 — Run the ST0 Review in Three Stages

As a reviewer, I want the ST0 review to run as structural check, then artifact check, then dataset advisory, so that a submission with structural problems comes back with one clear list instead of a mixed pile.

**Release:** r1 · Rule Application and AI Evaluation (weeks 3–4)
**Owner:** System
**Blocked by:** nothing — you can start this now

## The requirement this satisfies

- **REQ-024** (Functional, must) — The system must run the ST0 review in three stages, report every Stage 1 structural issue together and stop, and never let the dataset advisory create a structural failure.

## How to build it

Build exactly what the acceptance lines describe, from the Master Project Specification section this story came from.

## Failure paths you must handle


## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given a submission for ST0, when the review runs, then Stage 1 Structural Check runs first and Stage 2 Artifact Check runs only after Stage 1 passes.
- [ ] Given Stage 1 finds structural issues, when the result is produced, then all Stage 1 issues are listed together, no Stage 2 issue is included, and the review stops there.
- [ ] Given the Stage 3 dataset advisory raises concerns, when the result is produced, then they are reported as advisory only and never turn the submission into a structural failure.
- [ ] Given any completed evaluation, when the result is stored, then it is never marked approved by the system itself and always awaits a human reviewer.
- [ ] Trust: each stage run is logged with the stage, the rules evaluated, the outcome and the rule module version.

When every box above is ticked, stop and show the demo.
