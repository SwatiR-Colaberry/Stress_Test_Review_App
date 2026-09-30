"""The reviewer page's pure logic, run in Node (skipped where Node is absent;
GitHub's ubuntu runners include it)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

LOGIC = Path(__file__).parent / "web" / "review_logic.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _add_action(failed, raw_text, rule=""):
    script = (
        f"const {{ addFindingAction }} = require({json.dumps(str(LOGIC))});"
        f"let n = 0; const next = () => `new-${{++n}}`;"
        f"process.stdout.write(JSON.stringify(addFindingAction({json.dumps(failed)}, "
        f"{json.dumps(raw_text)}, {json.dumps(rule)}, next)));"
    )
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=10, check=True)
    return json.loads(out.stdout)


def test_retrying_a_failed_add_with_a_trailing_newline_reuses_its_action_id():
    # The bug: the failed action kept the raw text, the retry compared trimmed
    # text, so a note ending in a newline got a new id and was added twice.
    first = _add_action(None, "Nice dataset choice.\n")
    assert first == {"action_id": "new-1", "kind": "add_finding", "text": "Nice dataset choice."}
    retry = _add_action({"action": first}, "Nice dataset choice.\n")
    assert retry["action_id"] == "new-1"


def test_changed_text_after_a_failure_is_a_new_add():
    first = _add_action(None, "Nice dataset choice.")
    assert _add_action({"action": first}, "A different note.")["action_id"] == "new-1"  # fresh counter: a new id
    assert _add_action({"action": first}, "A different note.")["text"] == "A different note."


def test_an_optional_rule_id_is_sent_only_when_given():
    assert "rule_id" not in _add_action(None, "Note.", "  ")
    assert _add_action(None, "Note.", " ST0-003 ")["rule_id"] == "ST0-003"


def test_stress_test_codes_read_as_words_in_headings():
    script = (f"const {{ stressTestName }} = require({json.dumps(str(LOGIC))});"
              "process.stdout.write(JSON.stringify(['ST0', 'ST5', 'ST12', 'Other', '', null].map(stressTestName)));")
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=10, check=True)
    assert json.loads(out.stdout) == ["Stress Test 0", "Stress Test 5", "Stress Test 12", "Other", "", ""]
