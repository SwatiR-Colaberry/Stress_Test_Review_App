# Stress Test Review Application — Stories

12 stories across 5 releases, walking-skeleton first:
the earliest release proves the thinnest end-to-end path including the trust
spine, and later releases stack features on top of something already working.

## Before the releases — start here

- **[STORY-000](stories/STORY-000.md)** — Build your Command Center

The first thing you build, on day one, before any part of the system itself. It is
the page you keep open for the rest of the programme and demo from. It belongs to no
release and fulfils none of your requirements, because it is the window onto your
system rather than a part of it.

## r0 · Initial Integration and Detection — weeks 1–2

**Goal:** Establish Basecamp integration and critique marker detection.
**Done when you can show:** A critique marker in Basecamp creates a pending review item in the system.

- **[STORY-001](stories/STORY-001.md)** — Detect Critique Marker in Basecamp
- **[STORY-002](stories/STORY-002.md)** — Retrieve Submission Data from Basecamp
- **[STORY-011](stories/STORY-011.md)** — Implement Trust Spine for Submission Processing

## r1 · Rule Application and AI Evaluation — weeks 3–4

**Goal:** Implement rule loading and AI evaluation for ST0.
**Done when you can show:** A submission is evaluated by Claude against ST0 rules, producing structured draft findings.

- **[STORY-003](stories/STORY-003.md)** — Load ST0 Rule Module _(waits on STORY-001)_
- **[STORY-004](stories/STORY-004.md)** — Evaluate Submission with Claude _(waits on STORY-003)_

## r2 · Human Review Workflow — weeks 5–6

**Goal:** Enable human reviewers to approve, edit, or reject AI findings.
**Done when you can show:** A reviewer edits and approves AI findings, and feedback is posted to Basecamp.

- **[STORY-005](stories/STORY-005.md)** — Human Review of AI Findings _(waits on STORY-004)_
- **[STORY-006](stories/STORY-006.md)** — Post Final Feedback to Basecamp _(waits on STORY-005)_
- **[STORY-012](stories/STORY-012.md)** — Web UI for Review Queue Management _(waits on STORY-005)_

## r3 · Audit and History — weeks 7–8

**Goal:** Implement audit logging and historical review preservation.
**Done when you can show:** Review history shows AI drafts and human edits for completed reviews.

- **[STORY-007](stories/STORY-007.md)** — Preserve Review History _(waits on STORY-006)_
- **[STORY-008](stories/STORY-008.md)** — Handle Ambiguous Identifications _(waits on STORY-006)_

## r4 · Error Handling and Extensibility — weeks 9–10

**Goal:** Enhance error handling and prepare for future Stress Test modules.
**Done when you can show:** System handles errors gracefully and supports adding new Stress Test modules.

- **[STORY-009](stories/STORY-009.md)** — Implement Error Handling for External Calls _(waits on STORY-007)_
- **[STORY-010](stories/STORY-010.md)** — Prepare for Future Stress Test Modules _(waits on STORY-007)_
