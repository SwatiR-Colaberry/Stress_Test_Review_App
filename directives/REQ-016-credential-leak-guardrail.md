# REQ-016 — Credential Leak Guardrail (R4)

**Fulfils:** REQ-016 (Safety, must) — "The system must ensure that no credentials are stored in source code or shared documents." This is **R4**, per `.colaberry/plan.json` → `derived.guardrails[]` (the 4th SAFE requirement). Part of **STORY-011**, criterion 3: "Trust: The system ensures no credentials are stored in source code or shared documents."

## What "safe" means here

Per CLAUDE.md's Security Enforcement Layer: "No secrets in source code. No secrets in commit history. No secrets in logs. No secrets in error messages." Per the Master Project Specification §18: "Keep secrets in an approved secret manager or protected environment configuration. Never place API keys in source code, browser JavaScript, plain-text SQL tables or documents shared with reviewers."

An **unsafe result**, for R4, is defined precisely as: **a credential-shaped literal value — an API key, access key, private key, token, or password — committed anywhere in this repository's source code or shared documents, instead of being referenced via an environment variable or left out entirely.** This is a static, structural property of the repo, checkable without running the application (which doesn't exist as a running service yet — no backend/frontend scaffolding, per README's pre-implementation status).

## The check that enforces it

`backend/src/services/guardrails/credentialLeakGuardrail.js` exports:

- `scanTextForCredentials(content)` — pure function, returns an array of `{ pattern, line }` findings. Never includes the matched secret value itself, only the detector name and line number, so its own output can't become a fresh leak.
- `assertNoCredentialLeaks(content, sourceLabel)` — throws `CredentialLeakError` (`errorClass: 'ContractViolation'`) if any findings exist; otherwise returns `{ safe: true }`.

Detectors cover two classes:

| Class | Examples | Detection |
|---|---|---|
| Fixed-format secrets | AWS access key id, Anthropic/OpenAI-shaped API keys, GitHub tokens, Slack tokens, PEM private key blocks | Shape alone is enough to flag — these formats don't occur by accident |
| Assignment-shaped secrets | `password = "..."`, `client_secret: "..."`, `DB_PASSWORD=...` | Flagged only when the key name is secret-sounding **and** the value is a real-looking literal (≥8 chars, not a placeholder) |

Deliberately **not** flagged: `process.env.X` / `os.environ[...]` references (the correct pattern — see 12-Factor "Config separated from code" in CLAUDE.md), and placeholder values (`YOUR_API_KEY_HERE`, `<client-secret>`, `${DB_PASSWORD}`, `xxxx...`, `changeme`, etc.) — flagging those would make `.env.example`-style templates and this repo's own documentation unusable.

**`backend/src/scripts/scanForCredentials.js`** is the repo-wide enforcement check: it walks every text file in the repository (skipping `.git`, `node_modules`, binary file types, and `*.test.js` fixtures — which deliberately contain fake credential-shaped values to exercise the detectors), runs `scanTextForCredentials` on each, and exits non-zero if anything is found. Run it via `npm run scan:secrets`.

## Acceptance criterion (moves R4 UNMAPPED → PLANNED)

R4 is PLANNED when all of the following hold:

1. `assertNoCredentialLeaks()` / `scanTextForCredentials()` exist as the check that defines "no credentials in source" precisely and testably.
2. `backend/src/services/guardrails/credentialLeakGuardrail.test.js` passes and covers: the happy path (env-var references and safe prose), one failure case per fixed-format detector, a generic-assignment failure case, a "never leaks the raw secret in the error message" case, boundary cases (empty content, placeholder values, short values below the real-secret threshold, non-string input), and an idempotency check.
3. `backend/src/scripts/scanForCredentials.js` exists and, run today via `npm run scan:secrets`, exits 0 against the actual repository — i.e. the check doesn't just pass in theory, it currently passes for real.

Verified: `npm run scan:secrets` → `No credential-shaped content found across 36 text files.` (exit 0), and `npm test` → all tests pass.

R4 advances beyond PLANNED once this scan is wired into CI to run on every push/PR (tracked as a follow-up per CLAUDE.md's Continuous Integration section — introducing CI is itself a production-infrastructure change requiring sign-off) — that wiring is out of scope for PLANNED.

## Known limitation (logged, not solved here)

The generic assignment detector is pattern-based, not entropy-based: it will miss a genuinely random secret assigned to a key name it doesn't recognize (e.g. `DB_PWD = "..."` — abbreviated, not in the key list), and its 8-character minimum will miss very short real secrets. A production-grade scanner (e.g. gitleaks, trufflehog) with entropy analysis is the right long-term replacement; this hand-written version is scoped to be good enough to verify PLANNED status today without adding a new dependency.
