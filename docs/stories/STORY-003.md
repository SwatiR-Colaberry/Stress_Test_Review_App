# STORY-003 — Load ST0 Rule Module

As a system, I want to load the ST0 rule module, so that I can evaluate submissions correctly.

**Release:** r1 · Rule Application and AI Evaluation (weeks 3–4)
**Owner:** System
**Blocked by:** STORY-001

## The requirement this satisfies

- **REQ-003** (Functional, must) — The system must load only the rule module for the identified Stress Test (ST0) and never apply generic or incorrect rules.

## How to build it

Implement rule loading logic for ST0, ensuring correct module is loaded based on submission data.

## Failure paths you must handle

- Rule module not found
- Incorrect rule version loaded
- Rule loading timeout

## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given a submission for ST0, When the system loads rules, Then only ST0 rules are loaded.
- [ ] Given a submission for an unknown Stress Test, When the system loads rules, Then it routes to manual resolution.
- [ ] Trust: The system logs rule loading events with rule version.

When every box above is ticked, stop and show the demo.
