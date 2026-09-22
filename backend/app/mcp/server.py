"""Local MCP server for the Stress Test Review App, built on the official
Model Context Protocol Python SDK (`mcp` on PyPI, mcp.server.mcpserver.MCPServer).

Exposes:
- One read-only resource, `basecamp://submissions` — required. Currently
  backed by sample data, honestly labeled as such: REQ-004 (retrieve
  submission data) and REQ-012 (Basecamp OAuth 2.0) aren't built yet, so
  there is no live Basecamp connection to read from. The resource's shape
  matches what a real submission record will carry once that connector
  exists (see backend/app/mcp/sample_data.py).
- One tool stub, `finalize_review` — deliberately unimplemented. REQ-007's
  real finalize/post-to-Basecamp path needs a database and Basecamp client
  that don't exist in this repo yet; this proves the tool registers and
  responds correctly without pretending to do the real thing.

Run directly for local smoke-testing:
    PYTHONPATH=backend .venv/bin/python3 -m app.mcp.server

Registered with Claude Code via .mcp.json at the repo root (stdio transport).
"""
from mcp.server.mcpserver import MCPServer

from app.mcp.sample_data import SAMPLE_SUBMISSIONS

mcp_server = MCPServer(
    name="stress-test-review-app",
    version="0.1.0",
    instructions=(
        "Local MCP server for the Stress Test Review App. "
        "basecamp://submissions is sample data only, not a live Basecamp connection — "
        "see REQ-004/REQ-012 in docs/ACCEPTANCE_CHECKLIST.md."
    ),
)


@mcp_server.resource(
    "basecamp://submissions",
    name="basecamp_submissions",
    title="Basecamp Stress Test submissions (sample)",
    description=(
        "Read-only list of Stress Test submissions. SAMPLE DATA ONLY — no live "
        "Basecamp connection exists yet (REQ-004/REQ-012 unbuilt; Master Spec "
        "Sec.27 OAuth credentials not provided). Shape matches what a real "
        "submission record will carry once the Basecamp client is built."
    ),
    mime_type="application/json",
)
def get_basecamp_submissions() -> dict:
    return {
        "_note": "SAMPLE DATA — no live Basecamp connection. See REQ-004/REQ-012 in docs/ACCEPTANCE_CHECKLIST.md.",
        "submissions": SAMPLE_SUBMISSIONS,
    }


@mcp_server.tool(
    description=(
        "STUB — not implemented. Intended to finalize a review (REQ-007) once "
        "human approval (REQ-011, already built — see "
        "backend/app/guardrails/review_finalization_guardrail.py) and a real "
        "Basecamp-posting path exist. Neither the review persistence layer nor "
        "the Basecamp client is built yet."
    )
)
def finalize_review(review_id: str) -> dict:
    return {
        "status": "not_implemented",
        "review_id": review_id,
        "reason": (
            "Stub only. REQ-007's finalize/post-to-Basecamp path needs a "
            "database and Basecamp client, neither of which is built yet."
        ),
    }


if __name__ == "__main__":
    mcp_server.run()
