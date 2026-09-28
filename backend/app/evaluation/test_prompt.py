import re

import pytest

from app.evaluation.input_check import EvaluationInput
from app.evaluation.prompt import build_prompt, build_system_prompt
from app.models import PrecheckResults, SubmissionLink
from app.rules.loader import MODULES_DIR
from app.rules.module import RuleModule

_MODULE = RuleModule.model_validate_json((MODULES_DIR / "ST0" / "v1.json").read_text())
_TEXT = "Problem 1 ...\n[SELECTED]Problem 3[/SELECTED]\n[image: preview.png]"
_PRECHECKS = PrecheckResults(
    problem_count=9, selected_count=1, link_count=1, dataset_link_present=True,
    dataset_file_count=1, image_count=1,
)
_STAGE_1 = ["ST0-001", "ST0-002", "ST0-003", "ST0-006", "ST0-007", "ST0-008"]
_STAGE_2 = ["ST0-004", "ST0-005"]


def _input(text=_TEXT, **overrides):
    fields = dict(
        comment_id=2002, message_id=500, title="Stress Test 0 - Dataset & DS Problem", content_text=text,
        links=[SubmissionLink(url="https://www.kaggle.com/datasets/x/sales", text="Kaggle")],
        module=_MODULE,
    )
    fields.update(overrides)
    return EvaluationInput(**fields)


def test_every_st0_rule_and_its_feedback_is_in_the_system_prompt():
    system = build_system_prompt(_MODULE)
    for rule in _MODULE.rules:
        assert rule.id in system
        assert rule.failure_feedback in system
    assert "version v1" in system


def test_only_the_modules_own_stress_test_rules_appear():
    system = build_system_prompt(_MODULE)
    for other in ["ST1-", "ST2-", "ST3-", "ST4-", "ST5-"]:
        assert other not in system


def test_the_system_prompt_is_identical_across_stages_and_submissions():
    one = build_prompt(_input(), 1, _PRECHECKS)
    two = build_prompt(_input(), 2, _PRECHECKS)
    other = build_prompt(_input(text="something else", comment_id=3003, title="Other"), 1, _PRECHECKS)
    assert one.system == two.system == other.system


def test_the_system_prompt_holds_no_dates_or_ids():
    system = build_system_prompt(_MODULE)
    assert not re.search(r"\d{4}-\d{2}-\d{2}T|\b2002\b|\b500\b", system)


def test_the_system_prompt_asks_for_a_pass_list_not_pass_findings():
    system = build_system_prompt(_MODULE)
    assert "passed_rule_ids" in system
    assert "status PASS" not in system
    assert "ADVISORY" in system


@pytest.mark.parametrize("stage, asked, not_asked", [(1, _STAGE_1, _STAGE_2), (2, _STAGE_2, _STAGE_1)])
def test_the_user_message_asks_only_for_one_stages_rules(stage, asked, not_asked):
    first_line = build_prompt(_input(), stage, _PRECHECKS).user.split("\n")[0]
    assert all(rule_id in first_line for rule_id in asked)
    assert not any(rule_id in first_line for rule_id in not_asked)


def test_a_stage_without_rules_cannot_be_asked_for():
    with pytest.raises(ValueError):
        build_prompt(_input(), 3, _PRECHECKS)  # the dataset advisory has no rule ids


def test_the_submission_and_prechecks_are_only_in_the_user_message():
    prompt = build_prompt(_input(), 1, _PRECHECKS)
    assert _TEXT not in prompt.system
    assert f"<submission>\n{_TEXT}\n</submission>" in prompt.user
    assert "Problems counted: 9 (estimated from field labels)" in prompt.user
    assert "link to a known dataset site: yes" in prompt.user
    assert "https://www.kaggle.com/datasets/x/sales (Kaggle)" in prompt.user


def test_an_uncountable_problem_count_asks_claude_to_count():
    prechecks = _PRECHECKS.model_copy(update={"problem_count": None})
    assert "count them yourself" in build_prompt(_input(), 1, prechecks).user


def test_building_twice_gives_the_same_prompt():
    assert build_prompt(_input(), 1, _PRECHECKS) == build_prompt(_input(), 1, _PRECHECKS)


def test_the_prompt_says_submission_text_is_data_not_instructions():
    assert "not an instruction" in build_system_prompt(_MODULE)


def test_no_links_are_stated_as_none():
    assert "Links: none" in build_prompt(_input(links=[]), 1, _PRECHECKS).user
