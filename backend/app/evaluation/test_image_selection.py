import json
from pathlib import Path

import pytest

from app.basecamp.content_extractor import extract_attachments_and_links
from app.evaluation.image_selection import MAX_IMAGES, select_images
from app.evaluation.text import html_to_text
from app.rules.module import RuleModule

MODULES = Path(__file__).resolve().parents[1] / "rules" / "modules" / "ST0"
V2 = RuleModule.model_validate(json.loads((MODULES / "v2.json").read_text()))
V1 = RuleModule.model_validate(json.loads((MODULES / "v1.json").read_text()))


def img(name):
    return (f'<bc-attachment sgid="s-{name}" content-type="image/png" filename="{name}" '
            f'url="https://preview.3.basecamp.com/1/blobs/{name}/previews/full"></bc-attachment>')


def pick(html, module=V2):
    attachments, _ = extract_attachments_and_links(html)
    return [(p.attachment.filename, p.rule_id, p.part_label) for p in select_images(html_to_text(html), attachments, module)]


def test_the_screenshot_part_image_is_read():
    html = f"<div>Dataset Description: weekly sales</div><div>Dataset Screenshot:</div><div>{img('a.png')}</div>"
    assert pick(html) == [("a.png", "ST0-004", "Dataset Screenshot")]


def test_two_images_in_the_same_part_only_the_last_is_read():
    html = f"<div><strong>Screenshot of the dataset</strong></div>{img('first.png')}{img('second.png')}"
    assert pick(html) == [("second.png", "ST0-004", "Screenshot of the dataset")]


def test_images_under_other_rules_parts_or_before_any_label_are_not_read():
    html = (f"{img('top.png')}<div>Data Source: https://kaggle.com/x</div>{img('source.png')}"
            f"<div>Problem 3: churn</div>{img('problem.png')}<div>Dataset: sales</div>{img('nolabel-rule.png')}")
    assert pick(html) == []


def test_separate_screenshot_parts_each_give_their_last_image_in_order():
    html = (f"<div>Dataset Preview:</div>{img('p1.png')}{img('p2.png')}<div>Data Source: link</div>{img('s.png')}"
            f"<div>Snapshot of rows:</div>{img('q1.png')}")
    assert [name for name, _, _ in pick(html)] == ["p2.png", "q1.png"]


def test_never_more_than_five_images():
    html = "".join(f"<div>Screenshot {i}:</div>{img(f'{i}.png')}" for i in range(1, 8))
    assert [name for name, _, _ in pick(html)] == [f"{i}.png" for i in range(1, MAX_IMAGES + 1)]


def test_a_label_naming_the_screenshot_and_another_part_is_the_screenshot_part():
    html = f"<div>Dataset file &amp; screenshot:</div>{img('a.png')}<div>Data source and link</div>{img('b.png')}"
    assert pick(html) == [("a.png", "ST0-004", "Dataset file & screenshot")]


def test_otherwise_the_first_part_named_wins():
    html = f"<div>Selected problem screenshot:</div>{img('a.png')}<div>Selected problem:</div>{img('b.png')}"
    assert [name for name, _, _ in pick(html)] == ["a.png"]  # names the screenshot: read
    html = f"<div>Selected problem and data source:</div>{img('a.png')}"
    assert pick(html) == []  # selection part (named first), not an image rule


def test_label_on_the_same_line_as_the_image_and_numbered_or_bulleted_labels():
    html = f"<ol><li>Dataset Screenshot: {img('a.png')}</li></ol><div>2) Data Source:</div>{img('b.png')}"
    assert pick(html) == [("a.png", "ST0-004", "Dataset Screenshot")]


def test_a_sentence_mentioning_a_screenshot_does_not_start_a_part():
    html = (f"<div>Data Source: kaggle</div><div>Below is a screenshot of where I found the data on the site.</div>"
            f"{img('a.png')}")
    assert pick(html) == []  # still the source part: a long sentence is not a label


def test_files_and_mentions_are_ignored_and_a_module_without_image_rules_reads_nothing():
    pdf = '<bc-attachment content-type="application/pdf" filename="d.pdf" url="https://x.basecamp.com/d"></bc-attachment>'
    html = f"<div>Screenshot:</div>{pdf}{img('a.png')}"
    assert [name for name, _, _ in pick(html)] == ["a.png"]
    assert pick(html, V1) == []  # v1 has no rule that needs an image


def test_the_same_html_always_gives_the_same_picks():
    html = f"<div>Preview:</div>{img('a.png')}{img('b.png')}"
    assert pick(html) == pick(html)


@pytest.mark.parametrize("html", ["", "<div></div>", f"{img('a.png')}", "<div>Screenshot:</div>"])
def test_empty_or_partial_submissions_give_no_picks_and_never_fail(html):
    assert pick(html) == []
