"""The Review Queue page's pure logic and serving (STORY-012). The logic runs
in Node (skipped where Node is absent; GitHub's ubuntu runners include it)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

LOGIC = Path(__file__).parent / "web" / "queue_logic.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

ROWS = [{"review_id": "r-1", "status": "Pending"}, {"review_id": "r-2", "status": "Completed"},
        {"review_id": "r-3", "status": "Pending"}]


def _js(expression):
    script = (f"const L = require({json.dumps(str(LOGIC))});"
              f"process.stdout.write(JSON.stringify({expression}));")
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=10, check=True)
    return json.loads(out.stdout)


@needs_node
def test_filtering_keeps_order_and_all_shows_everything():
    assert [r["review_id"] for r in _js(f"L.filterRows({json.dumps(ROWS)}, 'Pending')")] == ["r-1", "r-3"]
    assert len(_js(f"L.filterRows({json.dumps(ROWS)}, 'All')")) == 3
    assert _js("L.filterRows([], 'Completed')") == []


@needs_node
def test_counts_include_every_status_even_when_zero():
    assert _js(f"L.countByStatus({json.dumps(ROWS)})") == {
        "All": 3, "Pending": 2, "In Review": 0, "Feedback Generated": 0, "Completed": 1}


@needs_node
def test_every_status_has_a_plain_meaning():
    meanings = _js("L.STATUS_MEANINGS")
    assert list(meanings) == _js("L.STATUSES")
    assert all(len(text) > 40 for text in meanings.values())


@needs_node
def test_search_matches_name_or_id_in_any_case():
    rows = [{"review_id": "abc-1", "student_name": "Asha Verma"}, {"review_id": "xyz-2", "student_name": None}]
    assert [r["review_id"] for r in _js(f"L.searchRows({json.dumps(rows)}, ' asha ')")] == ["abc-1"]
    assert [r["review_id"] for r in _js(f"L.searchRows({json.dumps(rows)}, 'XYZ')")] == ["xyz-2"]
    assert len(_js(f"L.searchRows({json.dumps(rows)}, '')")) == 2


@needs_node
def test_relative_time_reads_naturally_and_never_goes_negative():
    now = "Date.parse('2026-09-30T12:00:00Z')"
    cases = {"2026-09-30T12:00:30Z": "just now", "2026-09-30T12:05:00Z": "just now",  # future: clock skew
             "2026-09-30T11:55:00Z": "5 min ago", "2026-09-30T09:00:00Z": "3 h ago",
             "2026-09-29T11:00:00Z": "1 day ago", "2026-09-27T12:00:00Z": "3 days ago", "not a date": ""}
    for iso, expected in cases.items():
        assert _js(f"L.relativeTime({json.dumps(iso)}, {now})") == expected, iso


@needs_node
def test_completed_reviews_are_read_only():
    assert _js("['Pending','In Review','Feedback Generated','Completed'].map(L.canReview)") == [
        True, True, True, False]


@needs_node
def test_failures_are_explained_and_only_passing_ones_offer_retry():
    assert "did not answer in time" in _js("L.explainFailure(0, null, true)")
    assert "not in the Review Queue" in _js("L.explainFailure(404, {detail: {reason_code: 'REVIEW_NOT_FOUND'}})")
    assert "Retry" in _js("L.explainFailure(503, null)")
    assert "newest AI draft" in _js("L.explainFailure(409, {detail: {reason_code: 'REVIEW_STATE_MISMATCH'}})")
    assert _js("[0, 401, 404, 503, 500].map(L.isRetryable)") == [True, False, False, True, False]


def test_the_queue_page_and_its_scripts_are_served():
    from app.auth.fake import signed_in_client
    client = signed_in_client(app)
    page = client.get("/queue/")
    assert page.status_code == 200 and "Review Queue" in page.text
    for asset in ("/queue/queue.js", "/queue/queue_logic.js", "/queue/queue.css", "/reviewer/reviewer.css"):
        assert client.get(asset).status_code == 200, asset
