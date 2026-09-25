from app.basecamp.content_extractor import extract_attachments_and_links

SUBMISSION_HTML = (
    '<div>My ST0 submission. Dataset: <a href="https://kaggle.com/d/sales">Sales data</a>'
    '<bc-attachment sgid="BAh7abc" content-type="application/pdf" filename="report.pdf"'
    ' url="https://3.basecamp.com/999/blobs/1/download/report.pdf"></bc-attachment>'
    '<bc-attachment sgid="BAh7img" content-type="image/png" filename="chart.png"'
    ' href="https://3.basecamp.com/999/blobs/2/download/chart.png"></bc-attachment>'
    ' cc <bc-attachment sgid="BAh7who" content-type="application/vnd.basecamp.mention"></bc-attachment>'
    '</div>'
)


def test_extracts_file_attachments_and_links_from_a_submission():
    attachments, links = extract_attachments_and_links(SUBMISSION_HTML)
    assert [a.filename for a in attachments] == ["report.pdf", "chart.png"]
    assert attachments[0].content_type == "application/pdf"
    assert attachments[0].url.endswith("report.pdf")
    assert attachments[1].url.endswith("chart.png")  # href used when url is absent
    assert [(link.url, link.text) for link in links] == [("https://kaggle.com/d/sales", "Sales data")]


def test_mentions_are_not_counted_as_attachments():
    attachments, _ = extract_attachments_and_links(SUBMISSION_HTML)
    assert all(a.content_type != "application/vnd.basecamp.mention" for a in attachments)


def test_unsafe_relative_and_empty_links_are_dropped():
    html = (
        '<a href="javascript:alert(1)">x</a><a href="mailto:a@b.c">m</a>'
        '<a href="/relative">r</a><a href="">e</a><a>none</a><a href="HTTPS://ok.example">ok</a>'
    )
    _, links = extract_attachments_and_links(html)
    assert [link.url for link in links] == ["HTTPS://ok.example"]


def test_duplicate_links_keep_first_occurrence_in_order():
    html = '<a href="https://a.example">A</a><a href="https://b.example">B</a><a href="https://a.example">A2</a>'
    _, links = extract_attachments_and_links(html)
    assert [(link.url, link.text) for link in links] == [("https://a.example", "A"), ("https://b.example", "B")]


def test_empty_none_and_plain_text_bodies_yield_nothing():
    for body in ["", None, 42, "just text, no markup"]:
        assert extract_attachments_and_links(body) == ([], [])


def test_malformed_html_does_not_raise():
    attachments, links = extract_attachments_and_links('<div><a href="https://x.example">unclosed <bc-attachment filename="f.txt"')
    assert [link.url for link in links] == ["https://x.example"]
    assert isinstance(attachments, list)


def test_same_body_twice_gives_identical_output():
    assert extract_attachments_and_links(SUBMISSION_HTML) == extract_attachments_and_links(SUBMISSION_HTML)
