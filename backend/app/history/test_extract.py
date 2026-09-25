import csv
from datetime import datetime

import pytest

from app.history.extract import annotate_markers, attach_critiquers, stress_test_of, summarise, to_rows, write_csv


def _dt(day):
    return datetime(2026, 1, day, 12, 0)


def _comment(comment_id, body, marker_type=None, message_id="500", day=10, bcp=2148, step="Stress Test 2 - Project X",
             detail_id=77):
    return {"CommentId": comment_id, "MessageId": message_id, "Comment": body, "MarkerType": marker_type,
            "CommentCreatedDate": _dt(day), "BCP_ID": bcp, "StepName": step, "ProjectDetailID": detail_id}


_STEPS = [{"ProjectDetailID": 77}]


def _assignment(aid, message_id, critiquer, day):
    return {"BasecampStressTestCritiquerId": aid, "MessageId": message_id, "Critiquer": critiquer,
            "CritiquerAssignedDate": _dt(day)}


def test_stress_test_number_comes_from_the_step_name():
    assert stress_test_of("Stress Test 0 - Dataset & DS Problem - X") == "0"
    assert stress_test_of("1.\tStress Test 1 - ...") is None
    assert stress_test_of(None) is None


def test_markers_are_recomputed_and_compared_with_the_sql_hint():
    rows = [
        _comment(1, "V2 ##Critique##", "Critique"),
        _comment(2, "## feedbackgiven ##", None),          # SQL LIKE missed the lower-case variant
        _comment(3, "##FeedbackGiven## ##Approved##", "FeedbackGiven"),
        _comment(4, "thanks", None),
    ]
    annotate_markers(rows)
    assert [r["PyMarkers"] for r in rows] == ["Critique", "FeedbackGiven", "FeedbackGiven|Approved", ""]
    assert [r["MarkerAgrees"] for r in rows] == [True, False, True, True]
    assert rows[0]["StressTest"] == "2"


def test_critiquer_is_the_latest_assignment_at_or_before_the_comment():
    comments = [_comment(1, "a", day=5), _comment(2, "b", day=15), _comment(3, "c", message_id="999")]
    assignments = [_assignment(10, 500, "Reviewer A", 1), _assignment(11, 500, "Reviewer B", 12)]
    attach_critiquers(comments, assignments)
    assert [c["AssignedCritiquer"] for c in comments] == ["Reviewer A", "Reviewer B", None]
    assert [c["ThreadCritiquer"] for c in comments] == ["Reviewer B", "Reviewer B", None]


def test_a_comment_before_any_assignment_has_no_assigned_but_a_thread_critiquer():
    comments = [_comment(1, "a", day=1)]
    attach_critiquers(comments, [_assignment(10, 500, "Reviewer A", 3)])
    assert (comments[0]["AssignedCritiquer"], comments[0]["ThreadCritiquer"]) == (None, "Reviewer A")


def test_summary_counts_and_flags_duplicates_and_missing_projects():
    rows = [_comment(1, "##Critique##", "Critique"), _comment(1, "##Critique##", "Critique"),
            _comment(2, "ok", None, step="Stress Test 0 - Y")]
    annotate_markers(rows)
    attach_critiquers(rows, [])
    summary = summarise(rows, [], _STEPS, requested_bcp_ids=[2148, 1272])
    assert summary.duplicate_comment_ids == 1
    assert summary.projects_missing == [1272]
    assert summary.comments_per_stress_test == {"0": 1, "2": 2}
    assert summary.python_markers == {"(none)": 1, "Critique": 2}
    assert not summary.ok


def test_summary_contains_no_comment_text_or_names():
    rows = [_comment(1, "secret student text ##Critique##", "Critique")]
    annotate_markers(rows)
    attach_critiquers(rows, [_assignment(10, 500, "Reviewer A", 1)])
    dumped = summarise(rows, [], _STEPS, [2148]).model_dump_json()
    assert "secret student text" not in dumped and "Reviewer A" not in dumped


def test_write_csv_is_atomic_and_rerunnable(tmp_path):
    path = tmp_path / "out" / "comments.csv"
    rows = to_rows(["CommentId", "CommentCreatedDate"], [(1, _dt(2)), (2, _dt(3))])
    write_csv(path, rows, ["CommentId", "CommentCreatedDate"])
    write_csv(path, rows, ["CommentId", "CommentCreatedDate"])  # re-run overwrites, same content
    with path.open() as handle:
        assert list(csv.DictReader(handle)) == [
            {"CommentId": "1", "CommentCreatedDate": "2026-01-02 12:00:00"},
            {"CommentId": "2", "CommentCreatedDate": "2026-01-03 12:00:00"},
        ]
    assert [p.name for p in path.parent.iterdir()] == ["comments.csv"]


def test_write_csv_leaves_no_temp_file_and_keeps_the_old_file_on_failure(tmp_path):
    path = tmp_path / "comments.csv"
    write_csv(path, [{"CommentId": 1}], ["CommentId"])

    class Unwritable:
        def __str__(self):
            raise RuntimeError("cannot serialise")

    with pytest.raises(RuntimeError):
        write_csv(path, [{"CommentId": 2}, {"CommentId": Unwritable()}], ["CommentId"])
    assert [p.name for p in tmp_path.iterdir()] == ["comments.csv"]
    assert path.read_text().splitlines() == ["CommentId", "1"]


def test_a_comment_whose_step_was_not_extracted_fails_verification():
    rows = [_comment(1, "##Critique##", "Critique", detail_id=99)]
    annotate_markers(rows)
    attach_critiquers(rows, [])
    summary = summarise(rows, [], _STEPS, [2148])
    assert summary.comments_without_step_row == 1 and not summary.ok


def test_a_clean_extract_passes_verification():
    rows = [_comment(1, "##Critique##", "Critique")]
    annotate_markers(rows)
    attach_critiquers(rows, [])
    assert summarise(rows, [], _STEPS, [2148]).ok
