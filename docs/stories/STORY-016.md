# STORY-016 — AI Polish of Reviewer Feedback

As a reviewer, I want Claude to suggest cleaner wording for my feedback, so that I can send clear feedback faster while keeping the final say

**Release:** r4 · Error Handling and Extensibility (weeks 9–10)
**Owner:** System
**Blocked by:** nothing — you can start this now

## The requirement this satisfies

- **REQ-022** (Functional, should) — AI Polish of Reviewer Feedback

## How to build it

Implement exactly what the acceptance lines describe for this story, and nothing that belongs to another one.

## Failure paths you must handle


## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [ ] Given my feedback, when I click Polish, then a rewritten suggestion is shown next to my text and my text is unchanged
- [ ] Given a suggestion, when I accept it, then it is saved as my edit, and when I discard it, nothing changes
- [ ] Given text that was already polished, when I click Polish again, then the saved suggestion is shown and Claude is not called again
- [ ] Given Claude is unavailable or the daily token limit is reached, when I click Polish, then I see a clear message and can keep working with my own text
- [ ] Trust: the AI suggestion and my accept or discard are both kept in the review history with who and when, and a suggestion never reaches the student unless I accepted it

When every box above is ticked, stop and show the demo.
