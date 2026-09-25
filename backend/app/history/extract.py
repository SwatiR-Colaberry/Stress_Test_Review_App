"""Post-processing for the ST0-ST5 history extraction (see
directives/ST-historical-comment-extraction.md, Steps 5-6).

Takes the rows returned by st_history_comments.sql and
st_critiquer_assignments.sql and:
- adds the Stress Test number and the Python-detected review markers
  (authoritative, Master Spec §4.1), flagging disagreement with the SQL hint;
- matches each comment to a critiquer: the latest assignment on its thread at
  or before the comment (AssignedCritiquer) and the latest overall
  (ThreadCritiquer);
- in per-Stress-Test mode, keeps only the selected (project, Stress Test)
  pairs, so a project picked for ST2 does not bring its other Stress Tests;
- verifies the extract and summarises it in counts only (no personal data),
  which is safe to print and to store next to the extract.
Files are written atomically (temp file, then rename), so a re-run overwrites
cleanly and a failed run never leaves a half-written file.
"""
import csv
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel

from app.basecamp.critique_marker_detector import detect_review_markers

Row = Dict[str, Any]
# (BCP_ID, Stress Test number as text, e.g. (2353, "0")), as st_history_selection.sql returns them.
Pair = Tuple[int, str]


class ExtractSummary(BaseModel):
    comment_rows: int
    distinct_comment_ids: int
    duplicate_comment_ids: int
    projects_requested: int
    projects_found: int
    projects_missing: List[int]
    threads: int
    comments_per_stress_test: Dict[str, int]
    python_markers: Dict[str, int]
    sql_marker_hints: Dict[str, int]
    marker_disagreements: int
    comments_with_several_markers: int
    critiquer_assignment_rows: int
    comments_with_assigned_critiquer: int
    comments_with_thread_critiquer: int
    step_rows: int
    comments_without_step_row: int
    # Per-Stress-Test mode only; empty when extracting whole projects.
    pairs_requested: int = 0
    pairs_missing: List[str] = []
    projects_per_stress_test: Dict[str, int] = {}

    @property
    def ok(self) -> bool:
        return (
            self.duplicate_comment_ids == 0
            and not self.projects_missing
            and self.comments_without_step_row == 0
            and not self.pairs_missing
        )


def to_rows(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> List[Row]:
    return [dict(zip(columns, row)) for row in rows]


def stress_test_of(step_name: Optional[str]) -> Optional[str]:
    """'Stress Test 2 - ...' -> '2'. Mirrors SUBSTRING(StepName, 13, 1) in SQL."""
    if isinstance(step_name, str) and step_name.startswith("Stress Test ") and len(step_name) > 12:
        return step_name[12]
    return None


def annotate_markers(comments: List[Row]) -> None:
    for row in comments:
        markers = detect_review_markers(row.get("Comment"))
        row["StressTest"] = stress_test_of(row.get("StepName"))
        row["PyMarkers"] = "|".join(markers)
        # The SQL CASE reports only the first match, in the same order.
        row["MarkerAgrees"] = (markers[0] if markers else None) == row.get("MarkerType")


def keep_selected_pairs(
    comments: List[Row], steps: List[Row], assignments: List[Row], pairs: Set[Pair]
) -> Tuple[List[Row], List[Row], List[Row]]:
    """Drops every row outside the selected (project, Stress Test) pairs.
    Run after annotate_markers (comments need StressTest). Critiquer
    assignments are kept for the threads (MessageId) of the kept comments
    and steps, since they carry no project or Stress Test of their own."""
    kept_comments = [r for r in comments if (r["BCP_ID"], r["StressTest"]) in pairs]
    kept_steps = [r for r in steps if (r["BCP_ID"], stress_test_of(r.get("StepName"))) in pairs]
    threads = {int(r["MessageId"]) for r in kept_comments}
    threads |= {int(r["MessageBoardID"]) for r in kept_steps if str(r.get("MessageBoardID") or "").strip().isdigit()}
    kept_assignments = [a for a in assignments if int(a["MessageId"]) in threads]
    return kept_comments, kept_steps, kept_assignments


def attach_critiquers(comments: List[Row], assignments: List[Row]) -> None:
    by_thread: Dict[int, List[Row]] = defaultdict(list)
    for a in assignments:
        by_thread[int(a["MessageId"])].append(a)
    for rows in by_thread.values():
        rows.sort(key=lambda a: (a["CritiquerAssignedDate"], a["BasecampStressTestCritiquerId"]))
    for row in comments:
        thread = by_thread.get(int(row["MessageId"]), [])
        created = row.get("CommentCreatedDate")
        before = [a for a in thread if created is not None and a["CritiquerAssignedDate"] <= created]
        row["AssignedCritiquer"] = before[-1]["Critiquer"] if before else None
        row["ThreadCritiquer"] = thread[-1]["Critiquer"] if thread else None


def summarise(
    comments: List[Row],
    assignments: List[Row],
    steps: List[Row],
    requested_bcp_ids: Sequence[int],
    pairs: Optional[Set[Pair]] = None,
) -> ExtractSummary:
    ids = Counter(row["CommentId"] for row in comments)
    step_ids = {row["ProjectDetailID"] for row in steps}
    found = {row["BCP_ID"] for row in comments}
    python_markers: Counter = Counter()
    for row in comments:
        python_markers.update(row["PyMarkers"].split("|") if row["PyMarkers"] else ["(none)"])
    return ExtractSummary(
        comment_rows=len(comments),
        distinct_comment_ids=len(ids),
        duplicate_comment_ids=sum(1 for n in ids.values() if n > 1),
        projects_requested=len(set(requested_bcp_ids)),
        projects_found=len(found),
        projects_missing=sorted(set(requested_bcp_ids) - found),
        threads=len({row["MessageId"] for row in comments}),
        comments_per_stress_test=dict(sorted(Counter(str(row["StressTest"]) for row in comments).items())),
        python_markers=dict(sorted(python_markers.items())),
        sql_marker_hints=dict(sorted(Counter(str(row.get("MarkerType") or "(none)") for row in comments).items())),
        marker_disagreements=sum(1 for row in comments if not row["MarkerAgrees"]),
        comments_with_several_markers=sum(1 for row in comments if "|" in row["PyMarkers"]),
        critiquer_assignment_rows=len(assignments),
        comments_with_assigned_critiquer=sum(1 for row in comments if row["AssignedCritiquer"]),
        comments_with_thread_critiquer=sum(1 for row in comments if row["ThreadCritiquer"]),
        step_rows=len(steps),
        comments_without_step_row=sum(1 for row in comments if row.get("ProjectDetailID") not in step_ids),
        **_pair_coverage(comments, pairs),
    )


def _pair_coverage(comments: List[Row], pairs: Optional[Set[Pair]]) -> Dict[str, Any]:
    if not pairs:
        return {}
    found = {(row["BCP_ID"], row["StressTest"]) for row in comments}
    return {
        "pairs_requested": len(pairs),
        "pairs_missing": [f"{bcp_id}/ST{test}" for bcp_id, test in sorted(pairs - found)],
        "projects_per_stress_test": dict(sorted(Counter(test for _bcp_id, test in found).items())),
    }


def write_csv(path: Path, rows: List[Row], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: _csv_value(row.get(k)) for k in columns})
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _csv_value(value: Any) -> Any:
    return value.isoformat(sep=" ") if isinstance(value, datetime) else value
