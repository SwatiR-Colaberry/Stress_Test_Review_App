-- Picks the 15 student projects (BCP_ID) with the richest ST0-ST5 review
-- history, for rule-building. Returns ids and counts only: no names, emails,
-- step names or comment text. Read-only.
-- See directives/ST-historical-comment-extraction.md ("Selecting projects").
--
-- A "review cycle" is one Stress Test thread in which a ##Critique## comment
-- is later followed by a ##FeedbackGiven## comment. Ranking:
--   1. number of different Stress Tests (0-5) with at least one cycle,
--      so the selection spreads across ST0-ST5;
--   2. number of those threads that also reached ##Approved##;
--   3. most recent activity.
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
    SELECT * FROM threads WHERE LastFeedback > FirstCritique
),
project_tests AS (
    SELECT DISTINCT BCP_ID, StressTest FROM cycle_threads
),
tests_list AS (
    SELECT BCP_ID, STRING_AGG(StressTest, ',') WITHIN GROUP (ORDER BY StressTest) AS StressTests
    FROM project_tests
    GROUP BY BCP_ID
)
SELECT TOP (15)
    c.BCP_ID,
    t.StressTests,
    COUNT(DISTINCT c.StressTest) AS StressTestsWithCycle,
    COUNT(*) AS CycleThreads,
    SUM(CASE WHEN c.Approvals > 0 THEN 1 ELSE 0 END) AS ApprovedThreads,
    SUM(c.Comments) AS Comments,
    SUM(c.Critiques) AS Critiques,
    SUM(c.Feedbacks) AS Feedbacks,
    SUM(c.Approvals) AS Approvals,
    CAST(MAX(c.LastActivity) AS date) AS LastActivity
FROM cycle_threads c
INNER JOIN tests_list t ON t.BCP_ID = c.BCP_ID
GROUP BY c.BCP_ID, t.StressTests
ORDER BY StressTestsWithCycle DESC, ApprovedThreads DESC, MAX(c.LastActivity) DESC;
