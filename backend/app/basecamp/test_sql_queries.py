"""Guards the invariants of the stored ST history queries (see
directives/ST-historical-comment-extraction.md) so a later edit can't
silently reintroduce duplicate comment rows or the IsSubmitted filter."""
import re
from pathlib import Path

SQL_DIR = Path(__file__).parent / "sql"


def _sql(name):
    text = (SQL_DIR / name).read_text()
    return re.sub(r"--[^\n]*", "", text)  # ignore comments, check real SQL only


def test_all_stored_queries_exist():
    for name in ["st_history_counts.sql", "st_history_comments.sql", "st_critiquer_assignments.sql",
                 "st_history_steps.sql", "st_history_selection.sql", "st_id_profile.sql"]:
        assert (SQL_DIR / name).is_file(), name


def test_comment_query_does_not_join_the_critiquer_table():
    assert "ADF_BasecampStressTestCritiquer" not in _sql("st_history_comments.sql")


def test_comment_query_keeps_the_version_and_thread_ids():
    sql = _sql("st_history_comments.sql")
    assert "mc.CommentId" in sql and "mc.MessageId" in sql


def test_comment_query_drops_steps_without_comments():
    assert "INNER JOIN (" in _sql("st_history_comments.sql").split("dbo.ADF_CCS_CentersOfExcellence", 1)[1]


def test_comment_query_leaves_step_html_to_the_steps_query():
    assert "StepHTML" not in _sql("st_history_comments.sql")
    assert "pd.StepHTML" in _sql("st_history_steps.sql")
    assert "pd.ID AS ProjectDetailID" in _sql("st_history_comments.sql")


def test_extraction_queries_carry_the_project_filter_marker_once():
    for name in ["st_history_comments.sql", "st_critiquer_assignments.sql", "st_history_steps.sql"]:
        assert (SQL_DIR / name).read_text().count("/*BCP_ID_FILTER*/") == 1, name


def test_comment_and_selection_queries_keep_one_row_per_comment_id():
    for name in ["st_history_comments.sql", "st_history_selection.sql"]:
        sql = _sql(name)
        assert "PARTITION BY x.CommentId ORDER BY x.UpdatedDate DESC, x.Id DESC" in sql, name
        assert "mc.CopyRank = 1" in sql, name
        assert "WHERE x.CommentId IS NOT NULL" in sql, name


def test_no_query_filters_on_is_submitted():
    for path in SQL_DIR.glob("*.sql"):
        assert not re.search(r"WHERE[\s\S]*IsSubmitted", _sql(path.name)), path.name


def test_no_query_filters_on_is_active():
    # No project has IsActive = 1, and the old procedure does not filter on it.
    for path in SQL_DIR.glob("*.sql"):
        assert not re.search(r"WHERE[\s\S]*IsActive", _sql(path.name)), path.name


def test_message_ids_are_joined_as_numbers():
    for name in ["st_history_counts.sql", "st_history_comments.sql", "st_history_selection.sql"]:
        assert "TRY_CAST(mc.MessageId AS bigint)" in _sql(name), name
    assert "TRY_CAST(pd.MessageBoardID AS bigint) = sc.MessageId" in _sql("st_critiquer_assignments.sql")


def test_selection_query_returns_no_personal_data():
    select_list = _sql("st_history_selection.sql").rsplit("SELECT\n    StressTest,", 1)[1].split("FROM", 1)[0]
    for column in ["CreatorName", "CreatorEmail", "Comment ", "StepName", "BCP_Name", "Critiquer"]:
        assert column not in select_list, column


def test_queries_are_read_only():
    for path in SQL_DIR.glob("*.sql"):
        sql = _sql(path.name).upper()
        for verb in ["INSERT", "UPDATE ", "DELETE", "MERGE", "DROP", "ALTER", "TRUNCATE", "EXEC"]:
            assert verb not in sql, f"{path.name} contains {verb}"


def test_selection_picks_15_per_stress_test_by_recency():
    sql = _sql("st_history_selection.sql")
    assert "PARTITION BY StressTest ORDER BY LastActivity DESC, BCP_ID DESC" in sql
    assert "WHERE RecencyRank <= 15" in sql
    assert "TOP (" not in sql  # a global TOP would cap the whole list, not each Stress Test


def test_selection_takes_only_complete_reviews():
    assert "WHERE LastFeedback > FirstCritique AND Approvals > 0" in _sql("st_history_selection.sql")
