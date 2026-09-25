"""Read-only inspection of the SQL Server objects the ST history queries use.

Confirms, before any extraction: the server version and whether Full-Text
Search is installed (Master Spec §25 open questions), whether this login can
write to the comments table (it should not: least privilege, Master Spec §18),
that every table and column the stored queries reference exists, and that
CommentId/MessageId are integer types (the BasecampComment contract).
Returns metadata only; never reads row data.
"""
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

EXPECTED_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "ADF_CCS_BasecampProjects": (
        "BCP_ID", "UserID", "BCP_Name", "COE_ID", "PTP_ID", "ProjectNumber", "ProjectSD",
        "LastUpdated", "ProjectID", "IsActive",
    ),
    "ADF_CCS_BasecampProjects_Details": (
        "ID", "BCP_ID", "PQ_ProjectID", "StepName", "StepHTML", "PQ_Order", "StepType", "DueDate",
        "ProjectID", "ListGroupID", "ListID", "ListURL", "TaskID", "TaskURL", "MessageBoardID",
        "MessageBoardURL", "StartDate", "LastUpdated", "LastUpdatedBy", "TaskCompleted",
        "TaskCompleteDate", "TaskDueDate",
    ),
    "ADF_CCS_CentersOfExcellence": ("coe_id", "COE_Name"),
    "Basecamp_MessageBoards_MessageComments": (
        "Id", "MessageId", "CommentId", "Status", "Title", "CreatedDate", "UpdatedDate",
        "CreatorName", "CreatorEmail", "Comment", "IsSubmitted",
    ),
    "ADF_BasecampStressTestCritiquer": ("BasecampStressTestCritiquerId", "MessageId", "Critiquer", "CreatedDate"),
}
# CommentId must be an integer type (the version key, BasecampComment contract).
# MessageId / MessageBoardID may be text: every stored query joins them via
# TRY_CAST(... AS bigint), so a text type is reported as a note, not a problem.
STRICT_INTEGER_COLUMNS = (("Basecamp_MessageBoards_MessageComments", "CommentId"),)
CAST_ID_COLUMNS = (
    ("Basecamp_MessageBoards_MessageComments", "MessageId"),
    ("ADF_CCS_BasecampProjects_Details", "MessageBoardID"),
)
INTEGER_TYPES = {"int", "bigint"}

_SERVER_SQL = (
    "SELECT CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(128)), "
    "CAST(SERVERPROPERTY('Edition') AS nvarchar(128)), "
    "FULLTEXTSERVICEPROPERTY('IsFullTextInstalled')"
)
_WRITE_SQL = "SELECT HAS_PERMS_BY_NAME('dbo.Basecamp_MessageBoards_MessageComments', 'OBJECT', 'INSERT')"
_COLUMNS_SQL = (
    "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE "
    "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME IN ({}) "
    "ORDER BY TABLE_NAME, ORDINAL_POSITION"
).format(", ".join("?" for _ in EXPECTED_COLUMNS))


class ColumnInfo(BaseModel):
    table: str
    column: str
    data_type: str
    max_length: Optional[int] = None
    nullable: bool


class DatabaseReport(BaseModel):
    product_version: Optional[str] = None
    edition: Optional[str] = None
    full_text_installed: Optional[bool] = None
    login_can_insert_comments: Optional[bool] = None
    columns: List[ColumnInfo]
    missing_tables: List[str]
    missing_columns: List[str]
    id_column_problems: List[str]
    id_column_notes: List[str] = []

    @property
    def ok(self) -> bool:
        return not (self.missing_tables or self.missing_columns or self.id_column_problems)


def inspect_database(conn) -> DatabaseReport:
    cursor = conn.cursor()
    try:
        version, edition, full_text = cursor.execute(_SERVER_SQL).fetchone()
        (can_insert,) = cursor.execute(_WRITE_SQL).fetchone()
        rows = cursor.execute(_COLUMNS_SQL, *EXPECTED_COLUMNS.keys()).fetchall()
    finally:
        cursor.close()

    columns = [
        ColumnInfo(table=r[0], column=r[1], data_type=r[2], max_length=r[3], nullable=(r[4] == "YES"))
        for r in rows
    ]
    # SQL Server identifiers are usually case-insensitive; compare that way.
    found = {(c.table.lower(), c.column.lower()): c for c in columns}
    found_tables = {c.table.lower() for c in columns}
    missing_tables = [t for t in EXPECTED_COLUMNS if t.lower() not in found_tables]
    missing_columns = [
        f"{t}.{col}" for t, cols in EXPECTED_COLUMNS.items() if t.lower() in found_tables
        for col in cols if (t.lower(), col.lower()) not in found
    ]
    id_problems = []
    for table, column in STRICT_INTEGER_COLUMNS:
        info = found.get((table.lower(), column.lower()))
        if info is not None and info.data_type.lower() not in INTEGER_TYPES:
            id_problems.append(f"{table}.{column} is {info.data_type}, expected int or bigint")
    id_notes = []
    for table, column in CAST_ID_COLUMNS:
        info = found.get((table.lower(), column.lower()))
        if info is not None and info.data_type.lower() not in INTEGER_TYPES:
            id_notes.append(f"{table}.{column} is {info.data_type}; queries compare it via TRY_CAST(... AS bigint)")

    return DatabaseReport(
        product_version=version,
        edition=edition,
        full_text_installed=None if full_text is None else bool(full_text),
        login_can_insert_comments=None if can_insert is None else bool(can_insert),
        columns=columns,
        missing_tables=missing_tables,
        missing_columns=missing_columns,
        id_column_problems=id_problems,
        id_column_notes=id_notes,
    )
