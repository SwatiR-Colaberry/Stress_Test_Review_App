# STORY-014 — Sign in with Basecamp as Reviewer or Admin

As a reviewer or admin, I want to sign in with my Basecamp account, so that every review action is tied to who I really am and I only see what my role allows.

**Release:** r2 · Human Review Workflow (weeks 5–6)
**Owner:** System
**Blocked by:** nothing — you can start this now

## The requirement this satisfies

- **REQ-020** (Functional, should) — The system must authenticate reviewers and admins through Basecamp sign-in and enforce their role on every review action.

## How to build it

Implement exactly what the acceptance lines describe for this story, and nothing that belongs to another one.

## Failure paths you must handle


## Acceptance — your stop condition

Tick each box as it genuinely passes. This file is yours — the platform reads
the same criteria out of `.colaberry/progress.json`, which Claude Code keeps in
step (see the managed block in CLAUDE.md). Ticking something you have not
actually met only misleads you.

- [x] Given a Basecamp user on the reviewer list, when they sign in with Basecamp, then they reach the Review Queue as a Reviewer
- [x] Given a Basecamp user on the admin list, when they sign in, then they can also add, remove and change the role of reviewers and admins
- [x] Given a Basecamp user on neither list, when they sign in, then access is refused with a clear message
- [x] Given no signed-in session, when any review page or API is opened, then the user is sent to sign in and nothing is shown or changed
- [x] Given a Reviewer, when they try an admin-only action, then it is refused
- [x] Given a signed-in user, when they sign out or 8 hours pass, then they must sign in again
- [x] Trust: every sign-in, refusal, sign-out and role change is logged with who and when, and no password or token appears in logs or the repo

When every box above is ticked, stop and show the demo.
