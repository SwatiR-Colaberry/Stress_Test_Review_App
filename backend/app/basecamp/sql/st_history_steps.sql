-- One row per ST0-ST5 step (a project's Stress Test assignment), including
-- its full StepHTML. Companion to st_history_comments.sql, which leaves
-- StepHTML out so the same page is not repeated on every comment (header
-- note 6 there); join the two on ProjectDetailID. Read-only.
-- See directives/ST-historical-comment-extraction.md.

SELECT
    p.BCP_ID,
    pd.ID AS ProjectDetailID,
    pd.StepName,
    pd.StepType,
    pd.PQ_Order,
    TRY_CAST(pd.MessageBoardID AS bigint) AS MessageBoardID,
    pd.MessageBoardURL,
    pd.LastUpdated AS StepLastUpdated,
    pd.StepHTML
FROM dbo.ADF_CCS_BasecampProjects p
INNER JOIN dbo.ADF_CCS_BasecampProjects_Details pd
    ON p.BCP_ID = pd.BCP_ID
WHERE
    (
        pd.StepName LIKE 'Stress Test 0%'
        OR pd.StepName LIKE 'Stress Test 1%'
        OR pd.StepName LIKE 'Stress Test 2%'
        OR pd.StepName LIKE 'Stress Test 3%'
        OR pd.StepName LIKE 'Stress Test 4%'
        OR pd.StepName LIKE 'Stress Test 5%'
    )
    /*BCP_ID_FILTER*/  -- optional project filter, filled with ? placeholders by app.db.queries.with_bcp_id_filter

ORDER BY
    p.BCP_ID,
    pd.StepName,
    pd.ID;
