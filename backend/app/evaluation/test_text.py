import pytest

from app.evaluation.text import html_to_text, without_markers

_YELLOW = 'style="background-color: rgb(250, 247, 133);"'


def test_block_tags_become_lines_and_list_items_become_bullets():
    html = "<div>Dataset</div><ul><li>Problem: churn</li><li>Solution: classify</li></ul><p>End</p>"
    assert html_to_text(html) == "Dataset\n\n- Problem: churn\n- Solution: classify\n\nEnd"


def test_br_breaks_a_line_and_inline_tags_do_not():
    assert html_to_text("<div><strong>Problem</strong>: churn<br>Next</div>") == "Problem: churn\nNext"


def test_entities_are_decoded_and_whitespace_collapsed():
    assert html_to_text("<div>A &amp; B\n   and   C</div>") == "A & B and C"


@pytest.mark.parametrize(
    "style",
    [
        "background-color: rgb(250, 247, 133);",
        "background-color:rgb(250,247,133)",
        "BACKGROUND-COLOR: RGB(250, 247, 133)",
        "background-color: var(--highlight-bg-1);",
        "color: black; background-color: #FAF785",
    ],
)
def test_the_yellow_highlight_becomes_a_selected_block(style):
    html = f'<div>Problem 2</div><div><span style="{style}">Problem 3: churn</span></div>'
    assert html_to_text(html) == "Problem 2\n\n[SELECTED]Problem 3: churn[/SELECTED]"


@pytest.mark.parametrize("style", ["background-color: rgb(238, 226, 215);", "color: var(--highlight-7);"])
def test_other_colours_are_not_selections(style):
    assert "[SELECTED]" not in html_to_text(f'<div><mark style="{style}">Problem 1</mark></div>')


def test_nested_highlights_open_one_block():
    html = f"<div><span {_YELLOW}><strong {_YELLOW}>Problem</strong>: churn</span></div>"
    assert html_to_text(html) == "[SELECTED]Problem: churn[/SELECTED]"


def test_adjacent_highlighted_runs_merge_into_one_block():
    html = f"<ul><li><strong {_YELLOW}>Problem:</strong></li><li><strong {_YELLOW}>Solution:</strong></li></ul>"
    text = html_to_text(html)
    assert text.count("[SELECTED]") == 1
    assert text == "- [SELECTED]Problem:\n- Solution:[/SELECTED]"


def test_an_unclosed_highlight_is_closed_at_the_end():
    assert html_to_text(f"<div><span {_YELLOW}>Problem 3") == "[SELECTED]Problem 3[/SELECTED]"


def test_attachments_become_inline_markers_and_mentions_are_dropped():
    html = (
        '<div>Preview:</div><bc-attachment content-type="image/png" filename="head.png"></bc-attachment>'
        '<bc-attachment content-type="text/csv" filename="sales.csv"></bc-attachment>'
        '<bc-attachment content-type="application/vnd.basecamp.mention" sgid="x">'
        "<figcaption>Ali</figcaption></bc-attachment>"
    )
    text = html_to_text(html)
    assert "[image: head.png]" in text
    assert "[file: sales.csv]" in text
    assert "mention" not in text


def test_without_markers_keeps_only_the_students_words():
    assert without_markers("[SELECTED]Problem[/SELECTED] [image: a.png]") == "Problem"
    assert without_markers("[image: a.png] [file: b.csv]") == ""


def test_converting_twice_gives_the_same_text():
    html = f"<div><span {_YELLOW}>Problem 3</span></div>"
    assert html_to_text(html) == html_to_text(html)
