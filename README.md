# Stress Test Review App

A controlled review platform for Basecamp Stress Test submissions: students trigger review with a `##Critique##` marker, Claude drafts structured findings against versioned Stress Test rule modules, and a human reviewer approves/edits before final feedback is posted back to Basecamp.

MVP scope is the Review Queue + ST0 (structural validation) module; ST1–ST5 follow as configurable rule modules without rebuilding the core platform.

## Docs

- [docs/01-Master-Project-Specification.md](docs/01-Master-Project-Specification.md) — architecture, workflow, database, UI, integrations, security, acceptance criteria. Start here.
- [docs/references/](docs/references/) — original source documents (e.g. the `.docx` the Markdown spec was generated from).
- [docs/stress-test-rules/](docs/stress-test-rules/) — per-module rule specs (ST0 first; ST1–ST5 added as they're implemented).

## Status

Pre-implementation. See "Development Inputs Required Before Coding" (§27) and "Implementation Phases" (§25) in the Master Project Specification for what's needed before Phase 1 starts.

## Repo conventions

`CLAUDE.md` in this folder was copied from the SupplyMind_AI repo as a starting governance template — it currently describes a Node/TypeScript backend+frontend layout and Colaberry-specific integrations (Mandrill, Basecamp automation, etc.) that don't all apply here yet. Treat it as a draft: prune sections that don't fit once the actual tech stack (per §17 and §29 of the spec) is decided, rather than following it literally where it conflicts with this project's reality.
