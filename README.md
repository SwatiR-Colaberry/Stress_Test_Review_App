# Stress Test Review App

A controlled review platform for Basecamp Stress Test submissions: students trigger review with a `##Critique##` marker, Claude drafts structured findings against versioned Stress Test rule modules, and a human reviewer approves/edits before final feedback is posted back to Basecamp.

MVP scope is the Review Queue + ST0 (structural validation) module; ST1–ST5 follow as configurable rule modules without rebuilding the core platform.

## Docs

- [docs/01-Master-Project-Specification.md](docs/01-Master-Project-Specification.md) — architecture, workflow, database, UI, integrations, security, acceptance criteria. Start here.
- [docs/references/](docs/references/) — original source documents (e.g. the `.docx` the Markdown spec was generated from).
- [docs/stress-test-rules/](docs/stress-test-rules/) — per-module rule specs (ST0 first; ST1–ST5 added as they're implemented).

## Status

Early implementation. Real Basecamp/SQL-Server/Claude integration is still blocked on "Development Inputs Required Before Coding" (§27) in the Master Project Specification, but a handful of dependency-free pieces (safety guardrails, marker detection) are built and tested — see [docs/ACCEPTANCE_CHECKLIST.md](docs/ACCEPTANCE_CHECKLIST.md) for what's actually done vs. still open, checked against the canonical `.colaberry/plan.json` requirements.

## Local development

Backend is Python + FastAPI + Pydantic (Python 3.10+ required — pinned to 3.12 in `.python-version`, needed for the `mcp` SDK).

```
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

Then:

```
pytest                                                    # run the test suite
uvicorn app.main:app --app-dir backend --reload           # FastAPI app on localhost
PYTHONPATH=backend python3 -m app.mcp.server               # local MCP server over stdio (see backend/app/mcp/)
python3 backend/scripts/scan_for_credentials.py            # repo-wide credential scan (skips git-ignored files)
```

SQL Server (read-only; needs Microsoft ODBC Driver 18 — `brew install msodbcsql18` — and a local `.env` copied from `.env.example`). Full procedure, safety rules and verification: [directives/ST-historical-comment-extraction.md](directives/ST-historical-comment-extraction.md).

```
.venv/bin/python backend/scripts/check_db_connection.py    # connect + check the schema the queries rely on
.venv/bin/python backend/scripts/profile_st_ids.py         # ID/join-quality counts
.venv/bin/python backend/scripts/select_st_projects.py     # candidate projects for history extraction (ids + counts)
.venv/bin/python backend/scripts/extract_st_history.py --bcp-ids 2148,2075,...   # extract to data/extracts/ (git-ignored, personal data)
```

## Repo conventions

`CLAUDE.md` in this folder was copied from the SupplyMind_AI repo as a starting governance template — it originally described a Node/TypeScript backend+frontend layout; the backend-specific parts of that were corrected once the stack was decided (Python/FastAPI/Pydantic, 2026-09-16), but Colaberry-specific integrations inherited from that template (Mandrill, openclaw, Cory-briefing content, etc.) that don't apply to this project at all still remain and haven't been cleaned up. Treat it as a draft: prune sections that don't fit, rather than following it literally where it conflicts with this project's reality.
