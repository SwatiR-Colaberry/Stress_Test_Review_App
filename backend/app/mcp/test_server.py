"""Drives backend/app/mcp/server.py as a real subprocess over stdio using
the official MCP client, the same way Claude Code (or any MCP client)
actually talks to it — not a mock of the protocol.
"""
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp.server"],
        env={"PYTHONPATH": "backend"},
    )


async def _list_and_read_resource():
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            resources = await session.list_resources()
            uris = [str(r.uri) for r in resources.resources]
            assert "basecamp://submissions" in uris

            result = await session.read_resource("basecamp://submissions")
            assert len(result.contents) == 1
            payload = json.loads(result.contents[0].text)
            return payload


def test_basecamp_submissions_resource_is_registered_and_readable():
    payload = asyncio.run(_list_and_read_resource())
    assert payload["_note"].startswith("SAMPLE DATA")
    assert len(payload["submissions"]) == 3
    first = payload["submissions"][0]
    assert first.keys() == {
        "project",
        "student",
        "stress_test",
        "message_id",
        "comment_id",
        "critique_marker_detected",
        "submitted_at",
    }


async def _list_and_call_tool(review_id: str):
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            call = await session.call_tool("finalize_review", {"review_id": review_id})
            return names, call


def test_finalize_review_tool_is_registered_and_returns_stub_response():
    names, call = asyncio.run(_list_and_call_tool("rev-test-1"))
    assert "finalize_review" in names
    assert call.is_error is False

    body = json.loads(call.content[0].text)
    assert body["status"] == "not_implemented"
    assert body["review_id"] == "rev-test-1"
