# STORY-004 — Evaluate Submission with Claude

As a system, I want to evaluate submissions using Claude, so that I can generate draft findings.

**Release:** r1 · Rule Application and AI Evaluation (weeks 3–4)
**Owner:** System
**Blocked by:** STORY-003

## The requirement this satisfies

- **REQ-005** (Functional, must) — Claude must evaluate submissions against loaded rules, returning structured draft findings with rule ID, status, severity, evidence, reason, and confidence score.

## How to build it

Integrate Claude via Anthropic API, ensuring structured findings are returned for ST0 evaluations.

## Failure paths you must handle

- Claude API is unreachable
- Submission data is incomplete
- Evaluation exceeds time limit

## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given a valid submission, When Claude evaluates it, Then structured draft findings are returned.
- [ ] Given an invalid submission, When Claude evaluates it, Then an error is returned.
- [ ] Trust: The system logs evaluation events with submission ID and rule ID.

When every box above is ticked, stop and show the demo.
