# Stress Test 0 — Rules & Validation Specification (Architect & Reviewer)

> **Source:** `Stress_Test_0_Rules_and_Validation_Specification.docx` (provided by the user, 2026-09-25), transcribed without changes to its rules or wording. This is the ST0 rule source of truth for the MVP (§17). The machine-readable rule module built from it is `backend/app/rules/modules/ST0/v1.json` (STORY-003). Decisions that clarify how the rules are applied are recorded in that module, not here.

Official module specification for the Stress Test Review Application. Load this document alongside the Master Project Specification when implementing ST0.

## 1. Role and Purpose

ST0 guides students through the structural components required for Stress Test 0 and checks whether the required structural components and artifacts are present. It validates screenshot presence and reminds students to upload dataset file(s). It does not parse dataset files and does not evaluate modeling quality.

## 2. Scope Boundaries

- ST0 validates structure only.
- Do not evaluate modeling quality.
- Do not evaluate feature engineering.
- Do not evaluate model validation.
- Do not evaluate forecasting assessment.
- Do not perform dataset quality auditing.
- Do not perform feasibility analysis.
- Do not provide strategic critique.
- Do not act as a modeling assistant, coding tutor, dashboard builder, or approval authority.
- Final approval is manual.

## 3. Required ST0 Components

| Area | Requirement |
|---|---|
| Dataset | Dataset description: what the dataset contains |
| Dataset | Data collection explanation: how the dataset was collected/compiled |
| Dataset | Public dataset source link(s) |
| Dataset | Screenshot showing column headers and preview rows |
| Dataset | Dataset file(s) uploaded with final submission |
| Problems | 8–10 structured Data Science problems |
| Selection | One problem clearly selected |
| Problem fields | Problem, Solution, Model Type/s, Algorithm, Independent Variable/s, Dependent Variable, Target Audience, Future Capability/ies |

## 4. Important Dataset Concepts

- The dataset description and data collection explanation are separate concepts.
- What the dataset contains: describe what the data represents and the main information captured.
- How collected: explain how the data was collected, compiled, sourced or generated.
- At least one valid public source link must be provided.
- Dataset screenshot must show column headers and preview rows.
- Dataset files must be included with the final submission.

## 5. Problem Requirements

The submission must contain 8–10 structured Data Science problems. Each problem must include all required fields.

| Field | Required |
|---|---|
| Problem | Yes |
| Solution | Yes |
| Model Type/s | Yes |
| Algorithm | Yes |
| Independent Variable/s | Yes |
| Dependent Variable | Yes |
| Target Audience | Yes |
| Future Capability/ies | Yes |

Topic headers and descriptive text before a problem are allowed. The validator should identify problem sections based on meaning and required content rather than exact heading text.

## 6. Selected Problem Requirement

The submission must clearly identify exactly one selected problem, for example by stating 'Selected Problem: Problem #X' or an equivalent clear statement. The selected problem should be unambiguous.

## 7. ST0 Rule IDs

| Rule ID | Check | Failure feedback |
|---|---|---|
| ST0-001 | Dataset description is present | Please add a brief description of the dataset, including what the data represents and the main information captured in it. |
| ST0-002 | At least one valid public dataset source link is present | Please provide the public source link for the dataset. |
| ST0-003 | Data collection explanation is present and separate from dataset description | Please add a brief explanation of how the data was collected or compiled. |
| ST0-004 | Dataset screenshot shows column headers and preview rows | Please add a dataset screenshot showing the column headers and preview rows. |
| ST0-005 | Dataset file(s) are present in final submission | Please upload the dataset file(s) with the final Stress Test submission. |
| ST0-006 | Problem count is 8–10 | If fewer than 8, add enough problems to reach 8–10. If more than 10, reduce the list to 8–10. |
| ST0-007 | Every problem contains all required fields | Identify the exact problem number and missing required field(s). |
| ST0-008 | Exactly one selected problem is clearly identified | Please clearly identify one selected problem. |

## 8. Validation Tolerance

- Case-insensitive labels.
- Minor wording variations are allowed.
- Topic headers are allowed.
- Singular/plural differences are allowed.
- Numbering and punctuation differences are allowed.
- Validate meaning/content, not exact heading text.
- Do not fail solely because a heading differs slightly from the expected label.

## 9. Review Sequence

- Stage 1 — Structural Check.
- Stage 2 — Artifact Check.
- Stage 3 — Dataset Advisory.
- If Stage 1 fails, list all Stage 1 structural issues together and stop.
- Do not mix Stage 2 issues into a Stage 1 blocking result.
- Only if Stage 1 passes should Stage 2 run.
- If Stage 2 passes, state that no structural issues were detected and continue to advisory checks.
- The dataset advisory must not create a structural failure.
- Never auto-approve.

## 10. Stage 1 — Structural Check

| Check | Pass condition | Blocking? |
|---|---|---|
| ST0-001 | Dataset description present | Yes |
| ST0-002 | At least one valid public source link | Yes |
| ST0-003 | Collection explanation present and distinct | Yes |
| ST0-006 | 8–10 problems | Yes |
| ST0-007 | Every problem has all required fields | Yes |
| ST0-008 | Exactly one selected problem clearly identified | Yes |

## 11. Stage 2 — Artifact Check

| Artifact | Pass condition | Blocking? |
|---|---|---|
| ST0-004 Dataset screenshot | Screenshot shows headers + preview rows | Yes |
| ST0-005 Dataset files | Dataset file(s) present with final submission | Yes |
| Dataset preview if required by project format | Headers + at least 3 rows where applicable | Yes when required |

Do not require the student to upload the dataset file in chat. The final submission should be checked for the required uploaded dataset file(s).

## 12. Stage 3 — Dataset Advisory

- ST0 datasets are later used for Power BI dashboards. Prefer multiple meaningful categorical dimensions, several numerical columns and at least one date/time column.
- Numeric identifiers such as Store_ID, Dept_ID and Product_ID are weak dimensions.
- No categorical dimensions, or only one categorical column, may limit meaningful dashboard analysis.
- This advisory does not block structural validation.
- It may influence the human reviewer's final approval decision.

## 13. Finding Format

| Field | Allowed / expected |
|---|---|
| rule_id | ST0-001 through ST0-008 |
| status | PASS / FAIL / ADVISORY |
| severity | Required Fix / Needs Attention / Improvement |
| evidence | Specific current-submission evidence |
| reason | Rule-based explanation |
| suggested_feedback | Concise actionable feedback |
| confidence | AI confidence |
| historical_support | Optional relevant historical case(s) |

## 14. Feedback Guidance

Feedback should be concise, specific and actionable. Prioritize required fixes. When a required problem field is missing, identify the exact problem number and missing field. Do not introduce requirements that are not defined in this specification.

## 15. ST0 AI Review Guardrails

- Use only the ST0 rules loaded by the application.
- Do not apply ST1–ST5 rules.
- Do not invent requirements.
- Do not evaluate modeling quality or algorithm quality.
- Do not treat the dataset advisory as a structural failure.
- Do not approve automatically.
- Human reviewer remains the final authority.

## 16. Revision / Historical Context

Historical completed reviews may be retrieved to provide precedent and context. Historical examples do not override the current ST0 rules. The current rule version and current submission evidence always take priority.

## 17. Implementation Notes for Claude

Implement ST0 as a versioned rule module that can be loaded by the common Stress Test Review Engine. Do not hard-code ST0-only assumptions into the core application architecture. The rule engine should accept a Stress Test identifier and rule version, execute the required review stages in order, return structured findings, and preserve the human review decision.

This document is the detailed ST0 rule source of truth for the MVP.

**Figure (ST0 Review Sequence):** Stage 1 — Structural Check → if fail: report all structural issues + stop → Stage 2 — Artifact Check → if fail: report artifact issues → Stage 3 — Dataset Advisory → Human review / final approval. *No automatic approval.*
