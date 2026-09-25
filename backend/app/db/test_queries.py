import pytest

import json

import pyodbc

from app.db.queries import DatabaseQueryError, fetch_metrics, fetch_table, load_sql, with_bcp_id_filter


class _Cursor:
    description = (("metric",), ("value",))

    def __init__(self, rows):
        self.rows = rows
        self.closed = False
        self.params = None

    def execute(self, sql, *params):
        self.params = params
        return self

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


class _Conn:
    def __init__(self, rows):
        self.c = _Cursor(rows)

    def cursor(self):
        return self.c


def test_loads_a_stored_query():
    assert "COUNT_BIG" in load_sql("st_id_profile.sql")


@pytest.mark.parametrize("name", ["../../main.py", "st_id_profile.txt", "/etc/passwd"])
def test_refuses_anything_outside_the_sql_folder(name):
    with pytest.raises(ValueError):
        load_sql(name)


def test_fetch_metrics_returns_typed_rows_and_closes_the_cursor():
    conn = _Conn([("steps_total", 12), ("steps_board_null", 0)])
    metrics = fetch_metrics(conn, "SELECT ...")
    assert [(m.name, m.value) for m in metrics] == [("steps_total", 12), ("steps_board_null", 0)]
    assert conn.c.closed


def test_fetch_metrics_rejects_a_query_with_the_wrong_shape():
    with pytest.raises(ValueError):
        fetch_metrics(_Conn([("a", 1, "extra")]), "SELECT ...")


def test_fetch_table_returns_column_names_rows_and_passes_parameters():
    conn = _Conn([(101, 7), (102, 3)])
    columns, rows = fetch_table(conn, "SELECT ... WHERE x = ?", 5)
    assert columns == ["metric", "value"]
    assert rows == [(101, 7), (102, 3)]
    assert conn.c.params == (5,) and conn.c.closed


class _FailingCursor(_Cursor):
    def execute(self, sql, *params):
        raise pyodbc.OperationalError("HYT00", "[HYT00] Query timeout expired")


class _FailingConn:
    def __init__(self):
        self.c = _FailingCursor([])

    def cursor(self):
        return self.c


def test_a_failed_query_raises_a_classified_error_without_the_driver_message():
    conn = _FailingConn()
    for call in (lambda: fetch_metrics(conn, "SELECT ..."), lambda: fetch_table(conn, "SELECT ...")):
        with pytest.raises(DatabaseQueryError) as exc:
            call()
        assert (exc.value.error_class, exc.value.sqlstate) == ("TimeoutError", "HYT00")
        assert "Query timeout expired" not in str(exc.value)
    assert conn.c.closed


def test_bcp_id_filter_binds_ids_as_parameters():
    sql, params = with_bcp_id_filter(load_sql("st_history_comments.sql"), [2148, 2075, 2148])
    assert "AND p.BCP_ID IN (?, ?)" in sql and "2148" not in sql
    assert params == [2148, 2075]


def test_bcp_id_filter_none_removes_the_marker():
    sql, params = with_bcp_id_filter(load_sql("st_critiquer_assignments.sql"), None)
    assert "BCP_ID_FILTER" not in sql and params == []


@pytest.mark.parametrize("ids", [[], [0], [-1], ["2148"], [True], list(range(1, 102))])
def test_bcp_id_filter_rejects_bad_ids(ids):
    with pytest.raises(ValueError):
        with_bcp_id_filter(load_sql("st_history_comments.sql"), ids)


def test_bcp_id_filter_requires_the_marker():
    with pytest.raises(ValueError):
        with_bcp_id_filter("SELECT 1", [1])


def test_every_query_logs_label_duration_and_rows_but_never_sql_or_params(caplog):
    caplog.set_level("INFO", logger="stress_test_review.db")
    fetch_table(_Conn([(1, 2)]), "SELECT secret_column FROM t WHERE id = ?", 424242, label="st_history_comments.sql")
    [line] = [json.loads(r.getMessage()) for r in caplog.records if r.name == "stress_test_review.db"]
    assert (line["event"], line["label"], line["rows"], line["outcome"]) == ("db_query_completed", "st_history_comments.sql", 1, "success")
    assert "duration_ms" in line and "execute_ms" in line
    assert "secret_column" not in caplog.text and "424242" not in caplog.text


def test_a_failed_query_logs_its_error_class(caplog):
    caplog.set_level("INFO", logger="stress_test_review.db")
    with pytest.raises(DatabaseQueryError):
        fetch_table(_FailingConn(), "SELECT 1", label="x.sql")
    [line] = [json.loads(r.getMessage()) for r in caplog.records if r.name == "stress_test_review.db"]
    assert (line["event"], line["error_class"]) == ("db_query_failed", "TimeoutError")
