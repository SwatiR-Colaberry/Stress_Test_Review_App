# Stress Test Rule Modules — how they are stored, loaded and added

**Serves:** STORY-003 (REQ-003: load only the rule module for the identified Stress Test, never generic or incorrect rules). Points at REQ-017 (add ST1–ST5 as configuration, without rebuilding the app) and STORY-010.

## What a rule module is

A rule module is **versioned configuration, not code**: one JSON file per Stress Test and version, built from that Stress Test's official *Rules & Validation Specification*.

| File | Role |
|---|---|
| `docs/stress-test-rules/ST0-rules-v1.md` | The official ST0 spec, transcribed. The source of truth for the module. |
| `backend/app/rules/modules/ST0/v1.json` | The ST0 rule module: rules, stages, required problem fields, tolerance, advisory guidance, guardrails, reviewer notes. |
| `backend/app/rules/modules/registry.json` | Which version of each Stress Test is active: `{"ST0": "v1"}`. |
| `backend/app/rules/module.py` | `RuleModule`: the typed contract every module file must pass. |
| `backend/app/rules/loader.py` | `load_rules(label, audit, …)`: identify, load, record. |

`RuleModule` rejects a file whose rule ids belong to another Stress Test, repeat, or are missing from the stages; stages must be numbered in order and an advisory stage can never block; unknown fields are rejected.

Only what the spec says goes into a module. Where the spec's wording needs a decision, the decision goes into the rule's `evaluation_notes` with its source (spec section or dated user decision). Something the reviewer should know that is **not** a rule failure goes into `reviewer_notes` (for ST0: `SPLIT_SUBMISSION`, when the submission is not all in one comment).

ST0 v1 decisions (2026-09-25): ST0-002 "valid" = the link opens without an error; ST0-003 severity is Required Fix (blocking in Stage 1), not the Master Spec §10 "Needs Attention"; a split submission is a reviewer note (`SPLIT_SUBMISSION`), not a failure; content given only as a screenshot, document or outside link is a reviewer note (`CONTENT_NOT_IN_TEXT`) whose `student_feedback` asks for the submission as text in the comment; for ST0-008 the human reviewer confirms the selected problem for now (hint: the yellow highlight is `background-color: rgb(250, 247, 133)` in the comment HTML). v1 was updated in place for the last three because no review had used it yet; from now on any change gets a new version.

## What the ST0 history showed (2026-09-25)

Read-only review of 211 ST0 comments from 29 projects (both history extracts; counts only, no personal data here). Projects receiving each kind of reviewer feedback:

| Rule | Projects | Pattern |
|---|---|---|
| ST0-008 one selected problem | 12 | nothing highlighted, several highlighted, or only the title highlighted |
| ST0-003 collection explanation | 11 | "how was the dataset populated?" |
| ST0-007 all problem fields | 9 | usually only the selected problem is complete |
| ST0-002 source link | 7 | 3 missing, 4 present but dead or pointing at a general Kaggle page |
| ST0-006 problem count | 3 | |
| ST0-004 screenshot / ST0-005 files | 2 / 1 | |

Asked for by reviewers but **not in the spec**: the whole submission in one comment (~6 projects; now the `SPLIT_SUBMISSION` reviewer note); content typed into the comment rather than screenshots, documents or outside links (3); the selected problem highlighted in yellow — stored by Basecamp as HTML background-colour styling (344 uses), so selection must be read from the HTML, not plain text; removing material that belongs to later Stress Tests (3). Reviewers also judge **dataset suitability** (sample datasets, datasets already used by others, fit to the chosen problem; 4 projects), which the spec leaves to the human reviewer.

An earlier AI reviewer ("SmartCritic AI") posted 7 ST0 reviews critiquing financial stress-testing concepts (VaR, Monte Carlo) instead of the ST0 rules; human reviewers then gave the real feedback. These must be excluded from historical examples (STORY-013). Students also used `##Please Critique##` (5 comments, 4 not detected at the time) and `#Critique#`. Since 2026-09-25 `##Please Critique##` counts, with a reminder note for the reviewer (see `docs/stories/STORY-001.md`); `#Critique#` still does not.

## How loading works

`load_rules(stress_test_label, audit, …)` is the only entry point:

1. **Identify** the Stress Test from the step or message title ("Stress Test 0 - …" → `ST0`). One- or two-digit numbers only; checked against all 179 real step names in the history extracts (all identified, no disagreements).
2. **Look up** the active version in the registry.
3. **Read** the module file: at most 3 attempts per file for temporary errors, 5 s each (worst case ≈ 30 s for registry + module). A missing or invalid file is not retried. Reads run on a daemon thread, so a hung read neither blocks the caller past the timeout nor keeps the process alive.
4. **Check** that the file's own `stress_test_id` and `version` are the ones asked for.
5. **Record** one audit event (and a JSON log line): `rules_loaded` with the Stress Test and rule version, or `rules_manual_resolution` with the reason code. If the audit write fails, `AuditWriteError` is raised and no rules are returned.

Anything uncertain goes to **manual resolution**, never a guess; `load_rules` does not raise for these:

| reason_code | When |
|---|---|
| `STRESS_TEST_NOT_IDENTIFIED` | No "Stress Test N" in the label |
| `STRESS_TEST_AMBIGUOUS` | Two different Stress Test numbers in the label |
| `NO_RULE_MODULE` | The Stress Test is not in the registry (ST1–ST5 today; unknown ones like "Stress Test 10") |
| `RULE_MODULE_NOT_FOUND` | The registry names a file that does not exist |
| `RULE_MODULE_INVALID` | The registry or module file fails validation |
| `RULE_VERSION_MISMATCH` | The file is not the Stress Test/version that was asked for |
| `RULE_LOAD_TIMEOUT` | Reading did not finish in time, after capped attempts |
| `RULE_LOAD_FAILED` | Reading failed for another reason, after capped attempts |

The full manual-resolution workflow (a queue a person works through) is STORY-008; today the loader returns the result and records it.

## Adding ST1 (or a new version of ST0)

1. Put the official spec in `docs/stress-test-rules/ST1-rules-v1.md` (a faithful transcription).
2. Create `backend/app/rules/modules/ST1/v1.json` from it, copying the ST0 file's structure. Use the spec's exact rule wording.
3. Add one line to `registry.json`: `"ST1": "v1"`. For a new ST0 version, add `ST0/v2.json` and change the registry to `"v2"`; keep `v1.json`, so old reviews can still be read against the rules active at the time (Master Spec §7).
4. Add a test like `backend/app/rules/test_module.py` that compares the module's rules with the spec's rule table word for word.

No application code changes.

## How success is verified

- `pytest backend/app/rules` passes (module contract, ST0 v1 matches the spec, every loader path, audit recording, hung-read regression).
- Live check: `AUDIT_TRAIL_PATH=/tmp/rules.jsonl .venv/bin/python -c "import sys; sys.path.insert(0,'backend'); from app.audit.dependencies import get_audit_trail; from app.rules.loader import load_rules; print(load_rules('Stress Test 0 - Dataset', get_audit_trail()).rule_version)"` prints `v1`, and the audit file gains one `rules_loaded` line with `"rule_version":"v1"`.
