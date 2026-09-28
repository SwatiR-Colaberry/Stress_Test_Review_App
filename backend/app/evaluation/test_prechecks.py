import pytest

from app.evaluation.input_check import EvaluationInput
from app.evaluation.prechecks import count_numbered_problems, estimate_problem_count, run_prechecks
from app.models import SubmissionAttachment, SubmissionLink
from app.rules.loader import MODULES_DIR
from app.rules.module import RuleModule

_MODULE = RuleModule.model_validate_json((MODULES_DIR / "ST0" / "v1.json").read_text())
_FIELDS = _MODULE.required_problem_fields


def _problem(n: int, numbered: bool = False) -> str:
    head = f"Problem {n}: churn" if numbered else "- Problem: churn"
    return "\n".join([
        head, "- Solution: classify", "- Model Types: supervised", "- Algorithm: XGBoost",
        "- Independent Variables: tenure", "- Dependent Variable: churned",
        "- Target Audience: marketing", "- Future Capabilities: retention",
    ])


def test_unnumbered_problems_are_counted_by_their_field_labels():
    text = "Dataset description...\n\n" + "\n\n".join(_problem(n) for n in range(1, 10))
    assert estimate_problem_count(text, _FIELDS) == 9


def test_numbered_problems_are_counted():
    text = "\n\n".join(_problem(n, numbered=True) for n in range(1, 11))
    assert estimate_problem_count(text, _FIELDS) == 10


def test_one_missing_field_label_does_not_change_the_count():
    problems = [_problem(n) for n in range(1, 9)]
    problems[3] = problems[3].replace("- Algorithm: XGBoost\n", "")
    assert estimate_problem_count("\n\n".join(problems), _FIELDS) == 8


@pytest.mark.parametrize(
    "label",
    ["3. Problem: churn", "1️⃣ Problem: churn", "[SELECTED]Problem: churn", "* PROBLEM STATEMENT: churn", "Problem 3 - churn"],
)
def test_label_variants_at_line_start_are_recognised(label):
    assert estimate_problem_count(label, ["Problem"]) == 1


def test_a_word_mid_sentence_is_not_a_label():
    assert estimate_problem_count("The problem: nobody knows the solution.", _FIELDS) is None


def test_text_without_any_labels_is_not_countable_rather_than_zero():
    assert estimate_problem_count("Please ##Critique## my dataset.", _FIELDS) is None


def test_selected_problem_does_not_add_a_numbered_problem():
    assert count_numbered_problems("Problem 1\nProblem 2\nSelected Problem: Problem #2") == 2


def _input(text="- Problem: churn", attachments=(), links=()):
    return EvaluationInput(
        comment_id=2002, message_id=500, title="Stress Test 0", content_text=text,
        attachments=list(attachments), links=list(links), module=_MODULE,
    )


def test_prechecks_count_links_files_images_and_selections():
    result = run_prechecks(_input(
        text="[SELECTED]Problem: churn[/SELECTED]",
        attachments=[
            SubmissionAttachment(filename="sales.csv", content_type="text/csv"),
            SubmissionAttachment(filename="data.xlsx", content_type=None),
            SubmissionAttachment(filename="preview.png", content_type="image/png"),
            SubmissionAttachment(filename="notes.docx", content_type="application/msword"),
        ],
        links=[SubmissionLink(url="https://www.kaggle.com/datasets/x/sales")],
    ))
    assert (result.dataset_file_count, result.image_count, result.selected_count) == (2, 1, 1)
    assert (result.link_count, result.dataset_link_present, result.problem_count) == (1, True, 1)


def test_nothing_attached_or_linked_gives_zeros():
    result = run_prechecks(_input())
    assert (result.link_count, result.dataset_file_count, result.image_count, result.selected_count) == (0, 0, 0, 0)
    assert result.dataset_link_present is False


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.kaggle.com/datasets/a/b", True),
        ("https://catalog.data.gov/dataset/x", True),
        ("https://huggingface.co/datasets/x", True),
        ("https://huggingface.co/models/x", False),
        ("https://notkaggle.com/x", False),
        ("https://docs.google.com/spreadsheets/x", False),
    ],
)
def test_dataset_link_recognition(url, expected):
    assert run_prechecks(_input(links=[SubmissionLink(url=url)])).dataset_link_present is expected


def test_bare_urls_in_the_text_count_as_links_once():
    result = run_prechecks(_input(
        text="Source: https://www.kaggle.com/datasets/x/sales. Also https://example.com/a",
        links=[SubmissionLink(url="https://www.kaggle.com/datasets/x/sales")],  # same URL as an anchor
    ))
    assert (result.link_count, result.dataset_link_present) == (2, True)
