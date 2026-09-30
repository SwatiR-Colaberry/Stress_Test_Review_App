# STORY-020 — Check Problem Completeness and the Selected Problem

As a reviewer, I want each data science problem checked for its eight required fields, so that an incomplete problem is named precisely instead of the whole submission being called incomplete.

**Release:** r1 · Rule Application and AI Evaluation (weeks 3–4)
**Owner:** System
**Blocked by:** nothing — you can start this now

## The requirement this satisfies

- **REQ-026** (Functional, must) — The system must require 8 to 10 structured data science problems, each carrying all eight required fields, with exactly one clearly identified selected problem, detected by meaning rather than exact heading wording.

## How to build it

Build exactly what the acceptance lines describe, from the Master Project Specification section this story came from.

## Failure paths you must handle


## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given a submission, when the problems are counted, then between 8 and 10 structured problems are required and the actual count is reported.
- [ ] Given each problem, when it is checked, then Problem, Solution, Model Type/s, Algorithm, Independent Variable/s, Dependent Variable, Target Audience and Future Capability/ies are all required, and any missing field is named against that problem.
- [ ] Given headings that differ in capitalisation, punctuation, singular or plural, numbering or wording, when fields are detected, then detection is by meaning and those variations do not cause a failure.
- [ ] Given the submission, when the selected problem is checked, then exactly one clearly identified selected problem is required, and none or more than one is reported as a Required Fix.
- [ ] Trust: for each problem the fields found and the text they were read from are logged, so a reviewer can see why a field was judged missing.

When every box above is ticked, stop and show the demo.
