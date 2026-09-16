# STORY-008 — Handle Ambiguous Identifications

As a system, I want to handle ambiguous project or Stress Test identifications, so that I can route them to manual resolution.

**Release:** r3 · Audit and History (weeks 7–8)
**Owner:** System
**Blocked by:** STORY-006

## The requirement this satisfies

- **REQ-009** (Functional, must) — The system must route ambiguous project or Stress Test identifications to manual resolution rather than guessing.

## How to build it

Implement logic to detect and route ambiguous identifications to a manual resolution queue.

## Failure paths you must handle

- Ambiguity detection fails
- Manual resolution queue is full
- Routing logic is incorrect

## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given an ambiguous project ID, When the system processes it, Then it routes to manual resolution.
- [ ] Given an ambiguous Stress Test ID, When the system processes it, Then it routes to manual resolution.
- [ ] Trust: The system logs all manual resolution events with details.

When every box above is ticked, stop and show the demo.
