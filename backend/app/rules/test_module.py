"""STORY-003: the ST0 v1 rule module is valid, holds exactly the ST0 rules
from the spec, and RuleModule rejects mixed-up or broken modules."""
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.rules.module import RuleModule

REPO_ROOT = Path(__file__).resolve().parents[3]
ST0_V1 = Path(__file__).parent / "modules" / "ST0" / "v1.json"
SPEC = REPO_ROOT / "docs" / "stress-test-rules" / "ST0-rules-v1.md"


def _st0():
    return RuleModule.model_validate_json(ST0_V1.read_text())


def _raw():
    return json.loads(ST0_V1.read_text())


def _spec_rule_table():
    """{rule_id: (check, failure_feedback)} from the spec's §7 table."""
    section = SPEC.read_text().split("## 7. ST0 Rule IDs", 1)[1].split("## 8.", 1)[0]
    rows = re.findall(r"^\| (ST0-\d{3}) \| (.+?) \| (.+?) \|$", section, flags=re.M)
    return {rule_id: (check, feedback) for rule_id, check, feedback in rows}


def test_st0_v1_is_a_valid_module_for_st0():
    module = _st0()
    assert (module.stress_test_id, module.version) == ("ST0", "v1")
    assert (REPO_ROOT / module.source_document).is_file()


def test_st0_v1_holds_exactly_the_eight_st0_rules():
    assert [rule.id for rule in _st0().rules] == [f"ST0-00{n}" for n in range(1, 9)]


def test_rule_checks_and_feedback_match_the_spec_word_for_word():
    spec = _spec_rule_table()
    assert len(spec) == 8
    for rule in _st0().rules:
        assert (rule.check, rule.failure_feedback) == spec[rule.id], rule.id


def test_stages_and_blocking_match_spec_sections_9_to_12():
    stages = _st0().stages
    assert [(s.number, s.name, s.kind, s.blocking) for s in stages] == [
        (1, "Structural Check", "structural", True),
        (2, "Artifact Check", "artifact", True),
        (3, "Dataset Advisory", "advisory", False),
    ]
    assert stages[0].rule_ids == ["ST0-001", "ST0-002", "ST0-003", "ST0-006", "ST0-007", "ST0-008"]
    assert stages[1].rule_ids == ["ST0-004", "ST0-005"]
    assert stages[2].rule_ids == []


def test_problem_fields_and_count_match_spec_section_5():
    module = _st0()
    assert module.required_problem_fields == [
        "Problem", "Solution", "Model Type/s", "Algorithm", "Independent Variable/s",
        "Dependent Variable", "Target Audience", "Future Capability/ies",
    ]
    assert (module.problem_count.min, module.problem_count.max) == (8, 10)


def test_user_decisions_are_recorded():
    module = _st0()
    assert any("opens without an error" in note for note in module.rule("ST0-002").evaluation_notes)
    notes = {note.id: note for note in module.reviewer_notes}
    assert set(notes) == {"SPLIT_SUBMISSION", "CONTENT_NOT_IN_TEXT"}
    assert "not a rule failure" in notes["SPLIT_SUBMISSION"].note
    assert "as text in the comment" in notes["CONTENT_NOT_IN_TEXT"].student_feedback
    assert any("rgb(250, 247, 133)" in n and "human reviewer" in n for n in module.rule("ST0-008").evaluation_notes)


# --- RuleModule rejects broken modules ---

def _broken(mutate):
    raw = _raw()
    mutate(raw)
    with pytest.raises(ValidationError):
        RuleModule.model_validate(raw)


def test_a_rule_from_another_stress_test_is_rejected():
    def add_st1_rule(raw):
        raw["rules"].append({**raw["rules"][0], "id": "ST1-001"})
        raw["stages"][0]["rule_ids"].append("ST1-001")
    _broken(add_st1_rule)


def test_a_duplicate_rule_id_is_rejected():
    _broken(lambda raw: raw["rules"].append(dict(raw["rules"][0])))


def test_a_rule_missing_from_every_stage_is_rejected():
    _broken(lambda raw: raw["stages"][1]["rule_ids"].remove("ST0-005"))


def test_a_stage_naming_an_unknown_rule_is_rejected():
    _broken(lambda raw: raw["stages"][1]["rule_ids"].append("ST0-099"))


def test_a_blocking_advisory_stage_is_rejected():
    _broken(lambda raw: raw["stages"][2].update(blocking=True))


def test_unknown_fields_and_bad_versions_are_rejected():
    _broken(lambda raw: raw.update(extra_setting=True))
    _broken(lambda raw: raw.update(version="1.0"))
    _broken(lambda raw: raw["rules"][0].update(default_severity="Critical"))


def test_every_blocking_rule_is_a_required_fix():
    # ST0-003 included: blocking in Stage 1, so Required Fix (user decision, 2026-09-25).
    module = _st0()
    blocking = {rule_id for stage in module.stages if stage.blocking for rule_id in stage.rule_ids}
    assert {rule.id for rule in module.rules if rule.default_severity == "Required Fix"} == blocking
