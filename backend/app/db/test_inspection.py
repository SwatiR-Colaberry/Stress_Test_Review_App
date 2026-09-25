from app.db.inspection import EXPECTED_COLUMNS, inspect_database


def _all_columns(overrides=None, drop_table=None, drop_column=None):
    rows = []
    for table, cols in EXPECTED_COLUMNS.items():
        if table == drop_table:
            continue
        for col in cols:
            if (table, col) == drop_column:
                continue
            data_type = (overrides or {}).get((table, col), "int")
            rows.append((table, col, data_type, None, "NO"))
    return rows


class _FakeCursor:
    def __init__(self, columns, can_insert=0, full_text=1):
        self.columns = columns
        self.can_insert = can_insert
        self.full_text = full_text
        self.executed = []
        self.closed = False
        self._result = None

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        if "SERVERPROPERTY" in sql:
            self._result = [("16.0.4135.4", "Standard Edition (64-bit)", self.full_text)]
        elif "HAS_PERMS_BY_NAME" in sql:
            self._result = [(self.can_insert,)]
        else:
            self._result = self.columns
        return self

    def fetchone(self):
        return self._result[0]

    def fetchall(self):
        return self._result

    def close(self):
        self.closed = True


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_a_complete_schema_passes_and_reports_server_facts():
    cursor = _FakeCursor(_all_columns())
    report = inspect_database(_FakeConn(cursor))
    assert report.ok
    assert report.product_version == "16.0.4135.4"
    assert report.full_text_installed is True
    assert report.login_can_insert_comments is False
    assert cursor.closed


def test_table_names_are_passed_as_parameters_not_interpolated():
    cursor = _FakeCursor(_all_columns())
    inspect_database(_FakeConn(cursor))
    sql, params = cursor.executed[-1]
    assert params == tuple(EXPECTED_COLUMNS.keys())
    assert "Basecamp_MessageBoards_MessageComments" not in sql


def test_missing_table_and_column_are_reported():
    rows = _all_columns(drop_table="ADF_BasecampStressTestCritiquer",
                        drop_column=("Basecamp_MessageBoards_MessageComments", "IsSubmitted"))
    report = inspect_database(_FakeConn(_FakeCursor(rows)))
    assert not report.ok
    assert report.missing_tables == ["ADF_BasecampStressTestCritiquer"]
    assert report.missing_columns == ["Basecamp_MessageBoards_MessageComments.IsSubmitted"]


def test_text_message_ids_are_a_note_not_a_problem():
    rows = _all_columns(overrides={("Basecamp_MessageBoards_MessageComments", "MessageId"): "nvarchar",
                                   ("ADF_CCS_BasecampProjects_Details", "MessageBoardID"): "varchar"})
    report = inspect_database(_FakeConn(_FakeCursor(rows)))
    assert report.ok and report.id_column_problems == []
    assert len(report.id_column_notes) == 2


def test_non_integer_comment_id_is_flagged():
    rows = _all_columns(overrides={("Basecamp_MessageBoards_MessageComments", "CommentId"): "nvarchar"})
    report = inspect_database(_FakeConn(_FakeCursor(rows)))
    assert report.id_column_problems == ["Basecamp_MessageBoards_MessageComments.CommentId is nvarchar, expected int or bigint"]


def test_column_names_match_case_insensitively():
    rows = [(t.upper(), c.lower(), "bigint", None, "YES") for t, cols in EXPECTED_COLUMNS.items() for c in cols]
    assert inspect_database(_FakeConn(_FakeCursor(rows))).ok


def test_a_login_that_can_insert_is_reported():
    report = inspect_database(_FakeConn(_FakeCursor(_all_columns(), can_insert=1)))
    assert report.login_can_insert_comments is True
