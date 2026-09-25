-- Picks, SEPARATELY FOR EACH Stress Test (ST0-ST5), the 15 student projects
-- (BCP_ID) with the most recent review activity in that Stress Test, for
-- rule-building and historical retrieval. Up to 90 rows (6 x 15); a project
-- can appear under several Stress Tests. Returns ids, dates and counts only:
-- no names, emails, step names or comment text. Read-only.
-- See directives/ST-historical-comment-extraction.md ("Selecting projects").
--
-- A "review cycle" is one Stress Test thread in which a ##Critique## comment
-- is later followed by a ##FeedbackGiven## comment. Only COMPLETE reviews are
-- eligible: threads with a cycle that also reached ##Approved## (user
-- decision, 2026-09-25: in-progress reviews are not final examples for
-- rule-building or retrieval). Within each Stress Test
-- they are ranked by the latest comment in that Stress Test's cycle threads
-- (most recent first); ties broken by the higher BCP_ID so the order is
-- deterministic. Ids are not meaningful to the user, so recency is the rule
-- (user decision, 2026-09-25).
-- Marker matching here uses the same four spacing forms as the history
-- query; the extract is re-checked with the Python normalizer.
-- Comments are de-duplicated to one row per CommentId, exactly as in
-- st_history_comments.sql (header note 5), so snapshots are not re-counted.

WITH st_steps AS (
    SELECT
        p.BCP_ID,
        SUBSTRING(pd.StepName, 13, 1) AS StressTest,
        TRY_CAST(pd.MessageBoardID AS bigint) AS BoardId
    FROM dbo.ADF_CCS_BasecampProjects p
    INNER JOIN dbo.ADF_CCS_BasecampProjects_Details pd
        ON p.BCP_ID = pd.BCP_ID
    WHERE
        pd.StepName LIKE 'Stress Test 0%'
        OR pd.StepName LIKE 'Stress Test 1%'
        OR pd.StepName LIKE 'Stress Test 2%'
        OR pd.StepName LIKE 'Stress Test 3%'
        OR pd.StepName LIKE 'Stress Test 4%'
        OR pd.StepName LIKE 'Stress Test 5%'
),
marked AS (
    SELECT
        s.BCP_ID,
        s.StressTest,
        s.BoardId,
        mc.CreatedDate,
        CASE
            WHEN mc.Comment LIKE '%##Critique##%' OR mc.Comment LIKE '%## Critique##%'
              OR mc.Comment LIKE '%##Critique ##%' OR mc.Comment LIKE '%## Critique ##%'
            THEN 'Critique'
            WHEN mc.Comment LIKE '%##FeedbackGiven##%' OR mc.Comment LIKE '%## FeedbackGiven##%'
              OR mc.Comment LIKE '%##FeedbackGiven ##%' OR mc.Comment LIKE '%## FeedbackGiven ##%'
            THEN 'FeedbackGiven'
            WHEN mc.Comment LIKE '%##Approved##%' OR mc.Comment LIKE '%## Approved##%'
              OR mc.Comment LIKE '%##Approved ##%' OR mc.Comment LIKE '%## Approved ##%'
            THEN 'Approved'
        END AS MarkerType
    FROM st_steps s
    INNER JOIN (
        SELECT x.MessageId, x.CreatedDate, x.Comment,
            ROW_NUMBER() OVER (PARTITION BY x.CommentId ORDER BY x.UpdatedDate DESC, x.Id DESC) AS CopyRank
        FROM dbo.Basecamp_MessageBoards_MessageComments x
        WHERE x.CommentId IS NOT NULL
    ) mc
        ON TRY_CAST(mc.MessageId AS bigint) = s.BoardId
        AND mc.CopyRank = 1
    WHERE s.BoardId IS NOT NULL
),
threads AS (
    SELECT
        BCP_ID,
        StressTest,
        BoardId,
        COUNT(*) AS Comments,
        SUM(CASE WHEN MarkerType = 'Critique' THEN 1 ELSE 0 END) AS Critiques,
        SUM(CASE WHEN MarkerType = 'FeedbackGiven' THEN 1 ELSE 0 END) AS Feedbacks,
        SUM(CASE WHEN MarkerType = 'Approved' THEN 1 ELSE 0 END) AS Approvals,
        MIN(CASE WHEN MarkerType = 'Critique' THEN CreatedDate END) AS FirstCritique,
        MAX(CASE WHEN MarkerType = 'FeedbackGiven' THEN CreatedDate END) AS LastFeedback,
        MAX(CreatedDate) AS LastActivity
    FROM marked
    GROUP BY BCP_ID, StressTest, BoardId
),
cycle_threads AS (
    SELECT * FROM threads WHERE LastFeedback > FirstCritique AND Approvals > 0
),
per_test AS (
    SELECT
        StressTest,
        BCP_ID,
        COUNT(*) AS CycleThreads,
        SUM(CASE WHEN Approvals > 0 THEN 1 ELSE 0 END) AS ApprovedThreads,
        SUM(Comments) AS Comments,
        SUM(Critiques) AS Critiques,
        SUM(Feedbacks) AS Feedbacks,
        SUM(Approvals) AS Approvals,
        MAX(LastActivity) AS LastActivity
    FROM cycle_threads
    GROUP BY StressTest, BCP_ID
),
ranked AS (
    SELECT
        per_test.*,
        ROW_NUMBER() OVER (PARTITION BY StressTest ORDER BY LastActivity DESC, BCP_ID DESC) AS RecencyRank
    FROM per_test
)
SELECT
    StressTest,
    RecencyRank,
    BCP_ID,
    CycleThreads,
    ApprovedThreads,
    Comments,
    Critiques,
    Feedbacks,
    Approvals,
    CAST(LastActivity AS date) AS LastActivity
FROM ranked
WHERE RecencyRank <= 15
ORDER BY StressTest, RecencyRank;
