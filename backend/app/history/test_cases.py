"""STORY-013: which extract comments become historical cases."""
from app.history.cases import MAX_TEXT, cases_from_rows

STUDENT, REVIEWER = "student@example.org", "reviewer@example.org"
_ids = iter(range(1000, 9999))


def row(comment, author=STUDENT, message="10", stress_test="0", at="2026-01-01 10:00"):
    return {"StressTest": stress_test, "MessageId": message, "CommentId": str(next(_ids)),
            "CommentCreatedDate": at, "CreatorEmail": author, "Comment": comment}


def critique(text="<p>My dataset is X</p>", **kw):
    return row(f"<div>##Critique##</div>{text}", **kw)


def feedback(text="<p>Add the source link</p>", marker="FeedbackGiven", **kw):
    return row(f"<div>##{marker}##</div>{text}", author=kw.pop("author", REVIEWER), **kw)


def test_a_critique_answered_by_feedback_is_one_case():
    sub = critique(at="2026-01-01 10:00")
    cases, skipped = cases_from_rows([sub, feedback(at="2026-01-02 10:00")])
    assert [(c.case_id, c.stress_test_id) for c in cases] == [(sub["CommentId"], "ST0")]
    assert cases[0].submission_excerpt == "My dataset is X"  # plain text, marker removed
    assert cases[0].reviewer_feedback == "Add the source link"
    assert not skipped


def test_approved_counts_as_the_reviewer_answer():
    cases, _ = cases_from_rows([critique(at="1"), feedback("<p>Well done</p>", marker="Approved", at="2")])
    assert cases[0].reviewer_feedback == "Well done"


def test_every_round_in_a_thread_is_a_case_answered_by_its_own_feedback():
    first, second = critique("<p>v1</p>", at="1"), critique("<p>v2</p>", at="3")
    rows = [first, feedback("<p>fix A</p>", at="2"), second, feedback("<p>ok now</p>", marker="Approved", at="4")]
    cases, _ = cases_from_rows(rows)
    assert [(c.case_id, c.submission_excerpt, c.reviewer_feedback) for c in cases] == [
        (first["CommentId"], "v1", "fix A"), (second["CommentId"], "v2", "ok now")]


def test_the_last_critique_before_the_answer_is_the_one_reviewed():
    later = critique("<p>corrected</p>", at="2")
    cases, _ = cases_from_rows([critique("<p>typo</p>", at="1"), later, feedback(at="3")])
    assert [c.case_id for c in cases] == [later["CommentId"]]


def test_a_reviewer_reply_quoting_critique_is_not_a_submission():
    sub = critique(at="1")
    quoting = row("<div>##Critique## ##FeedbackGiven##</div><p>see above</p>", author=REVIEWER, at="2")
    cases, _ = cases_from_rows([sub, quoting])
    assert [(c.case_id, c.reviewer_feedback) for c in cases] == [(sub["CommentId"], "see above")]


def test_a_bare_critique_by_the_answering_reviewer_is_not_a_submission():
    cases, _ = cases_from_rows([critique(author=REVIEWER, at="1"), feedback(at="2")])
    assert cases == []


def test_a_critique_with_no_answer_yet_is_not_a_case():
    assert cases_from_rows([critique(at="1"), row("<p>thanks!</p>", at="2")])[0] == []


def test_threads_and_stress_tests_are_kept_apart():
    rows = [critique(message="1", stress_test="0", at="1"), feedback(message="2", stress_test="3", at="2")]
    assert cases_from_rows(rows)[0] == []
    rows += [feedback(message="1", stress_test="0", at="3"), critique(message="2", stress_test="3", at="1")]
    assert sorted(c.stress_test_id for c in cases_from_rows(rows)[0]) == ["ST0", "ST3"]


def test_an_empty_submission_is_skipped_and_counted():
    cases, skipped = cases_from_rows([critique("", at="1"), feedback(at="2")])
    assert cases == [] and skipped == {"ST0": 1}


def test_long_text_is_cut_to_the_cap():
    cases, _ = cases_from_rows([critique("<p>" + "a" * 5000 + "</p>", at="1"), feedback(at="2")])
    assert len(cases[0].submission_excerpt) == MAX_TEXT and cases[0].submission_excerpt.endswith("…")


def test_the_same_rows_twice_give_the_same_cases():
    rows = [critique(at="1"), feedback(at="2")]
    assert cases_from_rows(rows) == cases_from_rows(rows + rows)


def test_the_highlight_is_kept_and_nonstandard_markers_are_removed():
    sub = row("<div>## Please Critique ##</div><p><span style='background-color: rgb(250, 247, 133)'>Problem 3</span></p>",
              at="1")
    cases, _ = cases_from_rows([sub, feedback(at="2")])
    assert cases[0].submission_excerpt == "[SELECTED]Problem 3[/SELECTED]"
