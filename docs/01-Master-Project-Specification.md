# Stress Test Review Application — Master Project Specification

*Full Workflow, Architecture & Project Creation Specification*
*Manager / Claude Project Creation Document — MVP starts with Stress Test 0 (ST0) and expands to ST0–ST5*

> Source of record: [docs/references/01-Master-Project-Specification.docx](references/01-Master-Project-Specification.docx). This Markdown file is a working copy for day-to-day reference; if the two ever diverge, the `.docx` wins.

---

## Executive Summary

The application is a single Stress Test Review platform. Students continue working in Basecamp. A normalized `##Critique##` marker becomes the machine trigger. The application creates a review item, identifies the project and Stress Test, identifies the exact submission/version, loads the correct rule module, retrieves the required Basecamp material, generates an AI draft review, and presents it to a human critiquer. Only the human reviewer can finalize the review. Final feedback is posted back to Basecamp and the completed review becomes structured historical knowledge for future retrieval.

## 1. Business Objectives

- Reduce manual effort required to review Stress Tests while keeping human approval as the final control.
- Apply the correct rules consistently for each Stress Test instead of asking AI for generic critique.
- Create one central Review Queue for all projects and all Stress Tests.
- Preserve every submission/version, AI finding, reviewer edit, final feedback, and decision for audit and learning.
- Retrieve only a small set of relevant historical cases instead of sending the entire historical database to Claude.
- Start with ST0 and allow ST1–ST5 to be added as configurable modules without rebuilding the application.

## 2. Complete Student-to-Reviewer Journey

| Step | Process | Requirement |
|---|---|---|
| 1 | Student works in Basecamp | Student creates or updates the Stress Test submission in the existing Basecamp project. |
| 2 | Student adds `##Critique##` | Marker indicates the current submission/version is ready for review. |
| 3 | Application detects marker | Application monitors Basecamp activity and identifies a valid normalized critique marker. |
| 4 | Review Queue item is created | Create Pending review tied to the exact submission/version. |
| 5 | Project + Stress Test identified | Determine project, student, Stress Test, version and reviewer; never guess if ambiguous. |
| 6 | Correct rules loaded | Load only the rule module for the identified Stress Test. |
| 7 | Submission retrieved | Retrieve written content, comments, screenshots, attachments, files and relevant links required for review. |
| 8 | AI reviews against rules | Claude evaluates the current submission against the loaded rules only. |
| 9 | Draft feedback generated | Return rule ID, status, severity, evidence, reason, suggested feedback and confidence. |
| 10 | Human reviewer reviews | Reviewer can approve, edit, reject or add findings. Human review is mandatory. |
| 11 | Final feedback posted | Post only approved final feedback to the correct Basecamp location. |
| 12 | Review becomes Completed | Completed means human review and final feedback are complete. |

## 3. One Application, Six Stress Test Modules

| Module | Role | MVP status |
|---|---|---|
| Review Queue | Central list of submissions awaiting/undergoing review | Build first |
| ST0 | Dataset, source, collection, problems, artifacts; structural validation | Build first |
| ST1 | Data preparation / modeling rules | Future |
| ST2 | Dashboard / KPI rules | Future |
| ST3 | Insights / analysis rules | Future |
| ST4 | Reporting / strategy rules | Future |
| ST5 | Final presentation / evaluation rules | Future |
| History / Learning | Searchable completed reviews and reviewer decisions | Design now; expand over time |

The common platform owns Basecamp integration, marker detection, queue management, submission retrieval, reviewer workflow, audit history, and historical retrieval. Each Stress Test module owns its rules, validation logic, required artifacts, review stages and feedback guidance.

## 4. Critique Marker Detection and Version Handling

### 4.1 Authoritative detection approach

The new application should read the underlying Basecamp comment data directly rather than relying solely on the existing `proc_AllStressTestData` procedure. The current procedure uses exact `LIKE` matching for `##Critique##`, `##FeedbackGiven##` and `##Approved##` and therefore should not be treated as the authoritative detector for reasonable marker variations.

- Recognize reasonable case/spacing variations: `##Critique##`, `## Critique##`, `##Critique ##`, `## Critique ##`.
- Do not trigger on plain `Critique`, `#Critique`, `##Review##`, or ordinary prose containing the word critique.
- Normalize the marker before evaluating it.
- Use `MessageId` to identify the overall Basecamp thread.
- Use `CommentId` to identify the exact submission/comment version.
- Do not use `IsSubmitted` as the submission/version identifier.
- A new critique marker on a later version creates a new review while preserving the previous review.

| Data element | Use |
|---|---|
| MessageId | Overall Basecamp message/thread identity |
| CommentId | Exact comment/submission/version identity |
| Critique marker | Machine trigger for a review |
| IsSubmitted | Not a reliable version identifier |
| Previous review | Preserve for history and revision context |

## 5. Existing SQL Server Procedure and New Application

| Component | Current / intended role | Decision |
|---|---|---|
| `proc_AllStressTestData` | Existing Critique List/intake support | Keep; not authoritative for new marker detection |
| `Basecamp_MessageBoards_MessageComments` | Underlying comment records | Primary source for app marker/version detection |
| `ADF_BasecampStressTestCritiquer` | Critiquer assignment/history | Use where appropriate |
| Basecamp API | Full review material and eventual feedback posting | Required |

The existing procedure can continue supporting the current Critique List. The new application should add its own normalization and review-intake layer rather than forcing all new behavior into the existing procedure.

## 6. Review Material Retrieval

- SQL Server identifies the candidate review and provides stored references/context.
- Basecamp retrieves the actual material needed for review.
- Review material can include written submission, images/screenshots, attachments/files and relevant links.
- Review engine must support multimodal input when a Stress Test requires visual evidence.
- If project, Stress Test or submission cannot be identified confidently, move the case to manual resolution rather than guessing.
- If Basecamp content cannot be retrieved, preserve the queue item and expose the integration error.

## 7. Stress Test Rule Architecture

Official Stress Test rules should be versioned configuration, not hard-coded into generic AI prompts. The platform loads the rule module that matches the identified Stress Test.

| Rule-module content | Purpose |
|---|---|
| Stress Test scope | Defines what AI is and is not allowed to evaluate |
| Rule IDs | Stable identifiers such as `ST0-001` |
| Requirement definitions | Requirement to validate |
| Validation logic | How evidence is interpreted |
| Required artifacts | Screenshots, files, links, etc. |
| Review stages | Order in which checks execute |
| Severity guidance | Required Fix / Needs Attention / Improvement |
| Feedback guidance | Expected concise/actionable wording |
| Advisory rules | Non-blocking guidance where applicable |
| Rule version | Allows historical reviews to be interpreted against rules active at that time |

Recommended organization: keep this Master Project Specification separate from individual Stress Test rule specifications. For Claude project creation, upload the Master Specification plus the rule document(s) for the modules being implemented.

## 8. ST0 Module — Scope

ST0 is structural validation only. It should not evaluate modeling quality, forecasting quality, dataset realism, strategic quality, feature engineering, algorithm selection or other later-stage analytical concerns. Final approval remains manual.

## 9. ST0 Review Sequence

- **Stage 1 — Structural Check.**
- **Stage 2 — Artifact Check.**
- **Stage 3 — Dataset Advisory.**

Rules:
- If Stage 1 fails, list all Stage 1 structural issues together and stop. Do not mix Stage 2 issues into the blocking result.
- Only after Stage 1 passes should Stage 2 run.
- The dataset advisory must not create a structural failure.
- The application must never auto-approve a submission.

## 10. ST0 Rule Summary

| Rule ID | Requirement | Expected result |
|---|---|---|
| ST0-001 | Dataset description is present | PASS / Required Fix |
| ST0-002 | At least one valid public dataset source link | PASS / Required Fix |
| ST0-003 | Data collection explanation is present and separate from dataset description | PASS / Needs Attention |
| ST0-004 | Dataset screenshot shows headers and preview rows | PASS / Required Fix |
| ST0-005 | Dataset file(s) are present in final submission | PASS / Required Fix |
| ST0-006 | 8–10 Data Science problems are provided | PASS / Required Fix |
| ST0-007 | Each problem contains all required fields | PASS / Required Fix |
| ST0-008 | Exactly one selected problem is clearly identified | PASS / Required Fix |

This table is a summary only. The detailed ST0 Rules & Validation Specification should be maintained separately (see [`docs/stress-test-rules/`](stress-test-rules/)) and used by the review engine.

## 11. ST0 Problem Completeness

Each of the 8–10 structured Data Science problems must contain:

- Problem
- Solution
- Model Type/s
- Algorithm
- Independent Variable/s
- Dependent Variable
- Target Audience
- Future Capability/ies

Topic headers and descriptive text before a problem are allowed. Detection should be based on required section presence and meaning, not exact heading wording. Minor capitalization, punctuation, singular/plural, numbering and wording variations should not cause failure.

## 12. ST0 Dataset Advisory — Power BI Readiness

This is advisory context, not a blocking structural rule. Prefer datasets with multiple meaningful categorical dimensions, several numerical columns and at least one date/time field. Numeric identifiers such as `Store_ID`, `Dept_ID` and `Product_ID` are weak dimensions. A dataset with no categorical dimensions, or only one, may limit meaningful dashboard analysis.

## 13. AI Finding Structure and Feedback Style

| Field | Purpose |
|---|---|
| `rule_id` | Connect finding to official Stress Test rule |
| `status` | PASS / FAIL / ADVISORY |
| `severity` | Required Fix / Needs Attention / Improvement |
| `evidence` | Specific evidence in current submission |
| `reason` | Why evidence passes/fails rule |
| `suggested_feedback` | Concise, specific, actionable feedback |
| `confidence` | AI confidence |
| `historical_support` | Optional relevant prior cases |

Prioritize blocking and unclear issues. The AI must not invent requirements, substitute another Stress Test's rules or make final approval decisions.

## 14. Historical Retrieval — Fast Path

| Retrieval layer | Purpose | Example |
|---|---|---|
| 1. SQL filters | Reduce search space | `Stress Test = ST0 AND review = Completed` |
| 2. Rule matching | Find same requirement/issue | `rule_id = ST0-004` |
| 3. Domain/objective matching | Find similar project context | Retail / e-commerce / similar objective |
| 4. Full-text search | Find related wording/concepts | SQL Server Full-Text Search |
| 5. Vector similarity | Find semantic matches | Embedding similarity; optional/advanced |
| 6. Top-k selection | Send only useful examples | Top 5–10 cases |

Claude should receive the current case plus a small, relevant set of historical cases. It should never receive every project and every Stress Test.

## 15. How New Reviews Become Historical Knowledge

- No manual AI retraining is required after every review.
- When a review is completed, store final feedback, reviewer edits, rule IDs, findings and decision.
- Index the completed case for future retrieval.
- A future submission can retrieve the completed case when relevant.
- Historical examples never override official current Stress Test rules.

## 16. Technical Architecture

| Layer | Responsibility |
|---|---|
| Frontend web application | Review Queue, Review Detail, AI Findings, Feedback Editor, History |
| Backend application/API | Queue processing, orchestration, Basecamp integration, rule engine, Claude calls, reviewer APIs |
| Integration services | Basecamp API/OAuth/webhooks and Claude/AI access |
| Review engine | ST0–ST5 rule loading, validation, finding generation, historical retrieval, prompting |
| SQL Server | System of record for reviews, versions, rules, findings, history, reviewer decisions and audit |
| Background worker | Webhook processing, submission retrieval, AI review and historical indexing |
| Logging/monitoring | API errors, processing failures, latency and integration health |
| Authentication/SSO | Reviewer access and identity |
| Secret management | API keys, OAuth secrets and DB credentials; never hard-code |

## 17. Technology / Tools Required

| Component | Required? | Purpose / notes |
|---|---|---|
| Microsoft SQL Server | Yes — already available | Primary application database and system of record |
| Basecamp API | Yes | Read projects/submissions/comments/attachments as permitted and post final feedback |
| Basecamp OAuth 2.0 | Yes | Authenticate application access |
| Basecamp webhooks | Recommended | Near-real-time relevant activity notification |
| Claude API / approved Claude route | Yes if Claude selected | AI review and structured draft feedback |
| Anthropic credentials or AWS/Bedrock credentials | One of these | Approved enterprise Claude access |
| SQL Server Full-Text Search | Recommended | Initial historical retrieval |
| Embedding model/service | Optional for MVP; recommended later | Semantic historical retrieval |
| Vector search | Optional | Evaluate approved SQL Server 2025 or dedicated vector layer |
| Backend application/API | Yes | Orchestration and review services |
| Frontend web application | Yes | Reviewer experience |
| Background job/worker | Recommended | Asynchronous processing |
| Logging/monitoring | Yes | Operational visibility |
| Authentication / SSO | Recommended | Reviewer identity and access |

## 18. Credentials and Security

| Credential | Source | Use |
|---|---|---|
| Anthropic API key | Anthropic / organization | Direct Claude API |
| AWS credentials / IAM role + Bedrock access | AWS / organization | Claude through Bedrock |
| Basecamp OAuth client ID / secret | Basecamp app registration | OAuth authorization |
| Basecamp authorization/token information | Authorized Basecamp user | Basecamp API |
| SQL Server service account / connection credentials | Internal IT / DBA | Database access |
| Embedding API credential | Chosen provider | Only if vector retrieval is implemented |
| Application secret / SSO configuration | Internal security team | Reviewer authentication/session security |

Keep secrets in an approved secret manager or protected environment configuration. Never place API keys in source code, browser JavaScript, plain-text SQL tables or documents shared with reviewers.

## 19. Database Design

| Table / entity | Purpose |
|---|---|
| `stress_test_reviews` | One review instance per project/submission/version; status, reviewer, timestamps, final feedback |
| `stress_test_rules` | Versioned ST0–ST5 rule definitions and validation guidance |
| `review_findings` | AI findings with rule ID, status, severity, evidence, reason, confidence and reviewer decision |
| `submissions` / `submission_versions` | Exact Basecamp submission/version reviewed |
| `projects` | Basecamp project identity and metadata |
| `historical_reviews` | Searchable completed reviews / normalized historical context |
| `reviewer_edits` | What the human changed, rejected, approved or added |
| `review_audit_log` | Who did what, when and against which version |
| `integration_events` | Incoming webhook/API events and processing status |

## 20. Review Queue

| Visible field | Meaning |
|---|---|
| COE | Center / organizational context |
| Critique List / Project | Project and Stress Test submission requiring review |
| Last Submitted | Most recent submission/version timestamp |
| Critiquer | Assigned human reviewer |
| Status | Pending / In Review / Feedback Generated / Completed internally; Pending/Completed may remain visible |
| Action | Open review / Continue / Complete |

## 21. Review Detail Screen

- Submission summary: project, student, Stress Test, submission version and trigger timestamp.
- Current submission content and required artifacts.
- AI findings grouped by Required Fix, Needs Attention and Improvement.
- Evidence and rule ID for every finding.
- Relevant historical examples used by AI.
- Editable final feedback area.
- Approve / Edit / Reject / Add Finding controls.
- Audit/history showing AI draft and final human version.

## 22. Status Model

| Status | Meaning |
|---|---|
| Pending | `##Critique##` detected and review created |
| In Review | Reviewer has opened/started the case |
| Feedback Generated | AI draft exists |
| Completed | Human reviewer finalized review and final feedback was posted/stored |

Completed must never mean "AI finished." It means human review is finished and final feedback has been accepted/delivered.

## 23. Error Handling

| Condition | Required behavior |
|---|---|
| Project cannot be identified | Manual resolution; do not critique |
| Stress Test number cannot be identified | Manual resolution; do not guess |
| Submission cannot be retrieved | Preserve queue item and show integration error |
| Unsupported Stress Test | Do not apply another module's rules |
| Duplicate critique event | Idempotency check prevents duplicate review records |
| New critique on later version | Create new review/version and preserve previous review |
| Claude/API failure | Retry safely; retain queue item and error state |
| Basecamp posting failure | Do not mark Completed until final feedback delivery is resolved |

## 24. Security, Audit and Governance

- Use least-privilege access for Basecamp and SQL Server.
- Keep API credentials outside source code.
- Record the exact submission/version reviewed.
- Preserve original AI output before human edits.
- Store final human feedback separately from AI feedback.
- Record reviewer identity and completion timestamp.
- Version Stress Test rules so old reviews can be interpreted against the rules active at that time.
- Define retention/access policies for student submissions and reviewer history.
- Prevent AI from directly changing final review status or posting final feedback without human approval.

## 25. Implementation Phases

| Phase | Scope | Outcome |
|---|---|---|
| 1 | Basecamp connection + critique detection + Review Queue | Real submission can enter system |
| 2 | ST0 rule engine + validation | Application identifies structural ST0 issues |
| 3 | Claude integration + structured findings | AI generates draft ST0 feedback |
| 4 | Human workflow + Basecamp posting | End-to-end ST0 review operational |
| 5 | Historical retrieval | Relevant prior reviews surfaced automatically |
| 6 | Learning / reviewer decision analytics | Reviewer edits and decisions improve future retrieval/prompting |
| 7 | ST1–ST5 modules | Additional Stress Tests added without rebuilding core platform |

## 26. MVP Acceptance Criteria

- `##Critique##` creates exactly one review record per submission version.
- Correctly identifies ST0 and loads only ST0 rules.
- Detects all required missing structural items.
- Identifies exact problem number/field when a required field is missing.
- Runs Stage 1 before Stage 2, then advisory checks.
- Dataset advisory does not become a structural failure.
- AI feedback is concise, specific and actionable.
- Human reviewer can approve, edit, reject or add feedback.
- Review is marked Completed only after human review.
- New critique on a new version creates a new review while preserving previous history.
- AI never final-approves a submission.
- Historical retrieval never overrides current Stress Test rules.

## 27. Development Inputs Required Before Coding

- Confirm exact Basecamp environment and projects/COEs the application must access.
- Register Basecamp integration and obtain OAuth credentials.
- Confirm webhook availability and exact trigger strategy.
- Confirm installed SQL Server version and Full-Text Search availability.
- Confirm whether SQL Server 2025 vector functionality is available/approved.
- Obtain approved Claude access path: direct Anthropic API or Amazon Bedrock/AWS.
- Confirm security requirements for student data, API calls, logging and retention.
- Define reviewer authentication/SSO requirements.
- Provide representative historical ST0 reviews for retrieval testing.
- Confirm exact Basecamp location for final feedback posting.
- Define reviewer assignment/reassignment permissions and completion permissions.

## 28. Recommended Document Set for Claude Project Creation

| Document | Purpose | When used |
|---|---|---|
| 01 — Master Project Specification | Architecture, workflow, database, UI, integrations, security and acceptance criteria | Always |
| 02 — ST0 Rules & Validation Specification | Detailed official ST0 scope, rules, stages, validation logic and feedback guidance | ST0 implementation |
| 03 — ST1 Rules & Validation Specification | Official ST1 rules | When ST1 is implemented |
| 04 — ST2 Rules & Validation Specification | Official ST2 rules | When ST2 is implemented |
| 05 — ST3 Rules & Validation Specification | Official ST3 rules | When ST3 is implemented |
| 06 — ST4 Rules & Validation Specification | Official ST4 rules | When ST4 is implemented |
| 07 — ST5 Rules & Validation Specification | Official ST5 rules | When ST5 is implemented |
| Historical Review Data / Examples | Approved completed cases for retrieval/testing | As needed |

This separation is intentional. The Master Specification tells Claude how to build the platform. The Stress Test rule documents tell Claude what each module must validate. A rule change can therefore be made without rewriting the core architecture specification.

## 29. Recommended MVP Technology Decision

Keep Microsoft SQL Server as the system of record. Use a backend service for integrations and orchestration, a web frontend for reviewers, Claude through the approved enterprise route, and SQL Server Full-Text Search as the initial historical retrieval mechanism. If the installed SQL Server environment supports approved vector functionality, evaluate native vector storage/search; otherwise add a dedicated vector layer only when semantic retrieval is proven necessary.

## 30. Bottom Line

The proposed platform is a controlled review system, not an AI bot sitting on top of Basecamp. Basecamp supplies the submission. The application identifies the correct Stress Test and rules. Historical retrieval supplies relevant precedent. Claude creates a draft. A human reviewer makes the final decision. Final feedback is posted to Basecamp. The completed review becomes structured historical knowledge for the next case.

*Prepared as a detailed project-creation specification for implementation in Claude.*
