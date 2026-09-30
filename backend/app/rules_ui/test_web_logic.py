"""The Rules page's pure logic, run in Node (skipped where Node is absent;
GitHub's ubuntu runners include it)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

LOGIC = Path(__file__).parent / "web" / "rules_logic.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

RULE = {"id": "ST0-004", "check": "Dataset screenshot shows column headers and preview rows",
        "failure_feedback": "Please add a dataset screenshot.", "default_severity": "Required Fix",
        "evaluation_notes": ["headers + at least 3 rows"],
        "example": {"passes": "A spreadsheet image", "fails": "A chart only"}}


def _js(expression):
    script = f"const L = require({json.dumps(str(LOGIC))}); process.stdout.write(JSON.stringify({expression}));"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=10, check=True)
    return json.loads(out.stdout)


def test_search_looks_in_the_check_notes_and_examples_in_any_case():
    for text in ("SCREENSHOT", "st0-004", "3 rows", "chart only", ""):
        assert _js(f"L.ruleMatches({json.dumps(RULE)}, {json.dumps(text)})") is True, text
    assert _js(f"L.ruleMatches({json.dumps(RULE)}, 'problem count')") is False


def test_a_rule_without_notes_or_example_can_still_be_searched():
    bare = {"id": "ST1-001", "check": "Model is named"}
    assert _js(f"L.ruleMatches({json.dumps(bare)}, 'model')") is True


def test_a_rule_link_opens_its_stress_test_tab():
    assert _js("['ST0-002', 'ST3-010', 'ST0', '', 'junk'].map(L.stressTestOfRule)") == ["ST0", "ST3", None, None, None]
