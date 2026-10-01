-- The newest Stress Test 0 thread that has a ##Critique## request, with all of
-- its comments in order. Read-only (SELECT only). Used by
-- backend/scripts/live_trial.py to bring one real request into the app.
--
-- Comments are de-duplicated as in st_history_comments.sql (one row per
-- CommentId, the latest snapshot). The marker LIKEs are a hint only: the
-- request itself is picked in Python (app/review_queue/live_request.py) with
-- the real marker detector, so a reviewer's feedback that quotes
-- "##Critique##" is never taken for the student's request.

WITH mc AS (
    SELECT x.Id, x.MessageId, x.CommentId, x.CreatedDate, x.CreatorName, x.CreatorEmail, x.Comment,
        ROW_NUMBER() OVER (PARTITION BY x.CommentId ORDER BY x.UpdatedDate DESC, x.Id DESC) AS CopyRank
    FROM dbo.Basecamp_MessageBoards_MessageComments x
    WHERE x.CommentId IS NOT NULL
),
newest AS (
    SELECT TOP (1)
        p.BCP_ID, pd.StepName, pd.MessageBoardURL,
        TRY_CAST(pd.MessageBoardID AS bigint) AS ThreadId
    FROM dbo.ADF_CCS_BasecampProjects p
    INNER JOIN dbo.ADF_CCS_BasecampProjects_Details pd
        ON p.BCP_ID = pd.BCP_ID
    INNER JOIN mc
        ON TRY_CAST(mc.MessageId AS bigint) = TRY_CAST(pd.MessageBoardID AS bigint)
        AND mc.CopyRank = 1
    WHERE pd.StepName LIKE 'Stress Test 0%'
      AND (   mc.Comment LIKE '%##Critique##%'
           OR mc.Comment LIKE '%## Critique##%'
           OR mc.Comment LIKE '%##Critique ##%'
           OR mc.Comment LIKE '%## Critique ##%')
    ORDER BY mc.CreatedDate DESC, mc.CommentId DESC
)
SELECT
    newest.BCP_ID,
    newest.StepName,
    newest.MessageBoardURL,
    mc.MessageId,
    mc.CommentId,
    mc.CreatedDate AS CommentCreatedDate,
    mc.CreatorName,
    mc.CreatorEmail,
    mc.Comment
FROM newest
INNER JOIN mc
    ON TRY_CAST(mc.MessageId AS bigint) = newest.ThreadId
    AND mc.CopyRank = 1
ORDER BY mc.CreatedDate, mc.CommentId;
