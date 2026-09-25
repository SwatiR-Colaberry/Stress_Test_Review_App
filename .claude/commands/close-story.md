---
description: Close out a finished story - review, test, update every artifact and the Build Notes page, commit and push
argument-hint: STORY-nnn
---

The story I just finished is $ARGUMENTS. If no story id was given, stop and ask me which story.

Close it out in this order. Stop and ask me before anything that changes SQL Server (it is read-only: no changes to tables or procs), edits `.colaberry/plan.json` by hand, or touches another story's files.

## 1. Review, test, debug

- Review every file changed for this story (`git diff` against the last pushed commit) for correctness bugs, missing failure paths, unbounded waits, swallowed errors and secrets. Prove each suspected bug (a failing test or a reproduction) before fixing it.
- Fix what you find, adding a test for each fix. Run the full suite (`.venv/bin/python -m pytest backend`) and `backend/scripts/scan_for_credentials.py`; both must pass.
- Run a short demo of the acceptance criteria. Anything that writes the audit trail goes to a scratch `AUDIT_TRAIL_PATH`, not `data/audit/`.

## 2. Update the repo artifacts

- `.colaberry/progress.json`: this story's `passed` flags (only what truly passes), evidence, `files_touched`, `tests_added`, notes. Don't touch the `verification` block.
- `docs/stories/$ARGUMENTS.md`: tick the criteria that pass.
- `docs/ACCEPTANCE_CHECKLIST.md`: the lines for this story's requirements.
- Any directive the story changes or needs (`directives/*.md`), including how to verify.
- `command-center/tabs/data-model.js`, if the data model changed.
- `.colaberry/enrichment/$ARGUMENTS.json`: facts, decisions and limits, each with evidence that is a file in the repo (not a git-ignored file); `projectTruthBaseRevision` from `manifest.json`.
- `PROGRESS.md`: one entry tagged with this session's ID, with verification evidence. Re-read the tail first.

## 3. Update the Build Notes artifact at https://claude.ai/artifact/8jG1ktHc4zqczETSXeL6hE

- Read the whole current version first (Artifact `read`), and keep its design and patterns.
- Header: acceptance count (checked lines in `docs/ACCEPTANCE_CHECKLIST.md`), test count, each story's status (repo claim and portal state from `progress.json`), current phase, and the "newest" banner.
- Add or update this story in ALL six tabs:
  - Business: summary card and story panel
  - How it works: flow diagram, steps, proof panel with demo output
  - Files created: file table
  - Errors made: every bug found and fixed
  - Reliability: fails when / retries / recovery / not handled
  - Architecture: new design questions
- Update any earlier section this story made out of date. Update the footer commit and date.
- Check the HTML is balanced, then republish to the same URL (pass `url`).

## 4. Commit and push

- Stage explicit paths only; no `data/` files. Commit as `$ARGUMENTS: <what was done>` with `Story: $ARGUMENTS` on its own line. Push to origin main. The enrichment file may carry `sourceCommitSha: null`.

## 5. Report back

- What was fixed in the review.
- Test count and scan result.
- Which artifacts changed.
- The commit sha.
- Your confidence (%) that the story is complete, and what would raise it.
- Anything that needs my decision or a change in the portal.
- End with the PROGRESS.md audit line for this session.
