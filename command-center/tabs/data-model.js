// Data model — a starting proposal, not the answer (per STORY-000: "show me
// the model before you create the tables"). Entities are named for this
// project's own domain (a submission, a review, a finding) rather than for
// the vendor it talks to. Each table cites the requirement(s) it comes from
// so the reasoning is checkable against docs/REQUIREMENTS.md.

import { renderCrumb } from "../chrome.js";
import { navigate } from "../router.js";

const ENTITIES = [
  {
    name: "Submission",
    reqs: ["REQ-001", "REQ-002", "REQ-003", "REQ-004", "REQ-009"],
    note: "One detected critique marker, tied to the exact Basecamp comment/version it was found on.",
    fields: [
      ["id", "uuid", "primary key"],
      ["basecamp_project_id", "string", ""],
      ["basecamp_message_id", "string", "exact message/version identity"],
      ["basecamp_comment_id", "string", "exact comment identity"],
      ["stress_test_id", "string", "e.g. ST0 — identified, not guessed"],
      ["identification_status", "enum", "identified | ambiguous"],
      ["submitted_at", "timestamp", ""],
    ],
    relates: ["has one ReviewItem", "may have AmbiguousResolutionTask"],
  },
  {
    name: "ReviewItem",
    reqs: ["REQ-002", "REQ-007"],
    note: "The Review Queue item created for a submission — Pending until human review and Basecamp posting are both done.",
    fields: [
      ["id", "uuid", "primary key"],
      ["submission_id", "uuid", "fk → Submission"],
      ["rule_module", "string", "Stress Test + rule version applied, e.g. ST0/v1 (→ RuleModule)"],
      ["status", "enum", "Pending | Completed — Completed is set only by the STORY-006 posting service, after Basecamp confirmed the feedback comment (built). The Review Queue page (STORY-012) shows a status worked out from the records: Pending → In Review (a reviewer action) → Feedback Generated (PreparedFeedback) → Completed (a posted PostingRecord)"],
      ["created_at", "timestamp", ""],
      ["completed_at", "timestamp", "nullable"],
      ["marker_note", "text", "nullable — set when the student wrote ##Please Critique##: remind them to use ##Critique## (built)"],
      ["author_name", "string", "nullable — the student's Basecamp display name, shown on the reviewer page only; never in the audit trail or logs (built, STORY-005)"],
      ["app_url", "string", "nullable — the comment's Basecamp link; https basecamp.com only (built, STORY-005)"],
      ["project_id", "bigint", "nullable — the Basecamp project (bucket) of the thread; where the final feedback is posted. Set by the Basecamp API source (built, STORY-006)"],
    ],
    relates: ["belongs to Submission", "has many Finding", "has many ReviewHistoryEntry", "has many PostingRecord"],
  },
  {
    name: "RuleModule",
    reqs: ["REQ-003", "REQ-017"],
    note: "Built (STORY-003) as versioned configuration files, not a table: backend/app/rules/modules/<ST>/<version>.json plus registry.json naming the active version. A new Stress Test is a new file and one registry line, not a rebuild. ST0 v1 is built from the official ST0 spec.",
    fields: [
      ["stress_test_id", "string", "ST0, ST1, … ST5"],
      ["version", "string", "v1, v2, … (active one named in registry.json)"],
      ["rules", "json", "rule id, check, failure feedback, severity, evaluation notes, optional example {passes, fails} (fictional, for the Rules page only; never sent to Claude — built, STORY-012)"],
      ["stages", "json", "ordered; structural and artifact block, advisory never blocks"],
      ["reviewer_notes", "json", "things to tell the reviewer that are not rule failures, e.g. SPLIT_SUBMISSION, CONTENT_NOT_IN_TEXT"],
    ],
    relates: ["has many ReviewItem"],
  },
  {
    name: "Finding",
    reqs: ["REQ-005", "REQ-006"],
    note: "One structured finding — AI draft or human edit — with the fields REQ-005 requires. AI-draft half built (STORY-004): DraftFinding inside an EvaluationResult, stored one result per (comment_id, rule_version) in the git-ignored data/evaluations/results.jsonl, not a SQL Server table (SQL Server stays read-only). Passes are a list of rule ids; only FAIL / ADVISORY are findings. Since rules ST0 v2 (2026-10-02) the result also lists the images Claude was shown for a rule that needs one (EvaluationResult.images: rule, part, file name, READ or why not); the images themselves are never stored. Human half built (STORY-005): a reviewer approves, edits (≤ 2,000 characters), rejects or adds a finding; the AI draft is never changed — the reviewer's version is rebuilt from the action log (ReviewHistoryEntry).",
    fields: [
      ["id", "uuid", "primary key (planned; today keyed by comment_id + rule_version + rule_id)"],
      ["review_item_id", "uuid", "fk → ReviewItem (planned; today comment_id + message_id)"],
      ["rule_id", "string", "e.g. ST0-003"],
      ["status", "enum", "FAIL | ADVISORY (a PASS is only a rule id in passed_rule_ids)"],
      ["severity", "enum", "Required Fix | Needs Attention | Improvement — taken from the rule module"],
      ["evidence", "text", "≤ 300 characters"],
      ["reason", "text", "≤ 300 characters"],
      ["suggested_feedback", "text", "≤ 400 characters"],
      ["confidence_score", "float", "0–1; nullable — human-added findings have none"],
      ["source", "enum", "ai_draft | human_edit"],
      ["created_by", "uuid", "fk → Reviewer, nullable for ai_draft"],
      ["created_at", "timestamp", ""],
    ],
    relates: ["belongs to ReviewItem", "optionally created by Reviewer"],
  },
  {
    name: "HistoricalCase",
    reqs: ["REQ-019"],
    note: "Built (STORY-013): one past review round — a student's ##Critique## submission and the reviewer's answer — in a vector index for similarity search. Stored in LanceDB files under the git-ignored data/vector_index/, not SQL Server (read-only). Retrieval filters to the same Stress Test, then ranks; the top 10 reach Claude as examples only, never as rules. What was found (or why not) is kept on the evaluation result as history.",
    fields: [
      ["case_id", "string", "primary key — the submission's Basecamp comment id; re-indexing replaces, never duplicates"],
      ["stress_test_id", "string", "e.g. ST0 — the retrieval filter"],
      ["submission_excerpt", "text", "plain text, review markers removed, ≤ 2,000 characters"],
      ["reviewer_feedback", "text", "the human reviewer's answer, ≤ 2,000 characters"],
      ["vector", "float[384]", "embedding of the submission (bge-small-en-v1.5, run locally)"],
    ],
    relates: ["examples for an AI draft Finding (EvaluationResult.history)", "later fed by completed reviews (STORY-007)"],
  },
  {
    name: "ReviewHistoryEntry",
    reqs: ["REQ-008", "REQ-011"],
    note: "Human edits built (STORY-005) as the reviewer action log: one append-only line per reviewer action in the git-ignored data/reviews/actions.jsonl (not SQL Server), kept beside the unchanged AI draft, so both are preserved. The prior value is the AI draft plus the earlier lines. Retrieval for an audit request and 'posted' are STORY-007 / STORY-006.",
    fields: [
      ["action_id", "string", "primary key — the reviewer page's idempotency key: a retried request is applied once"],
      ["review_id", "string", "fk → ReviewItem"],
      ["reviewer_id", "string", "the signed-in reviewer's Basecamp email (STORY-014); AI/system ids still refused"],
      ["kind", "enum", "approve_finding | edit_finding | reject_finding | add_finding"],
      ["finding_id", "string", "the rule id of an AI finding, or added-<n> for a reviewer's own; nullable on add"],
      ["text", "text", "nullable — the reviewer's wording, ≤ 2,000 characters (edit / add)"],
      ["recorded_at", "timestamp", ""],
    ],
    relates: ["belongs to ReviewItem", "optionally actor Reviewer"],
  },
  {
    name: "PreparedFeedback",
    reqs: ["REQ-006", "REQ-011"],
    note: "Built (STORY-005): the final feedback a human reviewer approved, saved once per review in the git-ignored data/reviews/prepared.jsonl. Only when every finding has a decision; passes the REQ-011 guardrail (named human approver, not empty). After it is saved the review is locked. STORY-006 posts it to Basecamp.",
    fields: [
      ["review_id", "string", "primary key — fk → ReviewItem; first write wins"],
      ["reviewer_id", "string", "who prepared it"],
      ["status", "enum", "ready_to_post"],
      ["feedback_text", "text", "numbered approved findings in the reviewer's wording, ≤ 10,000 characters"],
      ["included_finding_ids", "string[]", "approved findings"],
      ["rejected_finding_ids", "string[]", "left out of the feedback"],
      ["prepared_at", "timestamp", ""],
    ],
    relates: ["belongs to ReviewItem", "built from ReviewHistoryEntry + the AI draft Finding list", "posted as PostingRecord"],
  },
  {
    name: "PostingRecord",
    reqs: ["REQ-007", "REQ-010", "REQ-008"],
    note: "Built (STORY-006): one line per posting step in the git-ignored data/reviews/posted.jsonl, append-only. A review is posted once any record says \"posted\" (written only after Basecamp confirmed the comment); that is what marks its ReviewItem Completed. The posted comment ends with \"Review ref: <feedback_id>\" and ##FeedbackGiven##; the thread is searched for the ref before every attempt, so a retry never posts twice.",
    fields: [
      ["feedback_id", "string", "FB- + 12 hex, derived from review_id — the same for every attempt"],
      ["review_id", "string", "fk → ReviewItem"],
      ["status", "enum", "posting | posted | failed"],
      ["attempt", "integer", "1–3; 0 = refused before any Basecamp call"],
      ["basecamp_comment_id", "bigint", "nullable — the posted comment"],
      ["reason_code", "string", "nullable — refusal code (e.g. PROJECT_NOT_ALLOWED) or error class (e.g. UpstreamUnavailable, TimeLimitExceeded)"],
      ["recorded_at", "timestamp", ""],
    ],
    relates: ["belongs to ReviewItem", "posts PreparedFeedback"],
  },
  {
    name: "AuditEvent",
    reqs: ["REQ-011", "REQ-016", "REQ-003"],
    note: "Built (STORY-011; rule-loading events from STORY-003; evaluation events from STORY-004; reviewer events from STORY-005; posting events from STORY-006): one append-only record per action taken on a submission. Stored as a git-ignored JSON Lines file (data/audit/audit_trail.jsonl), not a SQL Server table — existing tables and procedures must not change. Ids and outcomes only; no free text, so no comment bodies or secrets.",
    fields: [
      ["event_id", "uuid", "primary key"],
      ["recorded_at", "timestamp", ""],
      ["action", "enum", "review_created | review_already_queued | comment_no_marker | comment_rejected_malformed | finalize_allowed | finalize_blocked | retrieval_started | retrieval_completed | retrieval_failed | rules_loaded | rules_manual_resolution | evaluation_started | evaluation_finding | evaluation_completed | evaluation_failed | evaluation_already_done | evaluation_manual_resolution | evaluation_image (one per image picked for Claude: READ or why not) | history_retrieved | reviewer_finding_approved | reviewer_finding_edited | reviewer_finding_rejected | reviewer_finding_added | reviewer_feedback_prepared | reviewer_action_blocked | feedback_post_refused | feedback_post_attempted | feedback_posted | feedback_post_failed | queue_viewed | review_detail_viewed | rules_viewed (STORY-012: every reviewer page load, with reviewer and time) | role_added | role_changed | role_removed | signed_in | sign_in_refused | signed_out | admin_action_refused (STORY-014)"],
      ["actor_id", "string", "\"system\" for intake; the signed-in Basecamp email for reviewer actions, views, posts, sign-ins and role changes (STORY-014); \"unidentified\" if none named"],
      ["outcome", "enum", "success | blocked | failure"],
      ["correlation_id", "string", "X-Correlation-ID or generated"],
      ["comment_id", "bigint", "nullable — Basecamp comment (exact version)"],
      ["message_id", "bigint", "nullable — Basecamp thread"],
      ["project_id", "bigint", "nullable — Basecamp project (retrieval and posting events)"],
      ["stress_test_id", "string", "nullable — e.g. ST0 (rule-loading events)"],
      ["rule_version", "string", "nullable — e.g. v1 (rule-loading and evaluation events)"],
      ["rule_id", "string", "nullable — e.g. ST0-003 (evaluation_finding events)"],
      ["review_id", "string", "nullable — fk → ReviewItem"],
      ["reason_code", "string", "nullable — e.g. AI_CANNOT_APPROVE, REVIEWER_FEEDBACK, PASS / FAIL / ADVISORY on evaluation_finding, found / none_found / error class on history_retrieved, refusal code or error class on feedback_post_*"],
      ["feedback_id", "string", "nullable — FB-… on the four feedback_post_* / feedback_posted events (STORY-006)"],
      ["subject_id", "string", "nullable — whose role changed, on role_* events (STORY-014)"],
      ["role", "enum", "nullable — reviewer | admin, on role_* and signed_in events (STORY-014)"],
    ],
    relates: ["optionally about ReviewItem"],
  },
  {
    name: "AmbiguousResolutionTask",
    reqs: ["REQ-009"],
    note: "Routed for manual resolution when project or Stress Test identification isn't certain — never guessed.",
    fields: [
      ["id", "uuid", "primary key"],
      ["submission_id", "uuid", "fk → Submission"],
      ["reason", "text", ""],
      ["status", "enum", "open | resolved"],
      ["resolved_by", "uuid", "fk → Reviewer, nullable"],
      ["resolution_notes", "text", "nullable"],
      ["created_at", "timestamp", ""],
      ["resolved_at", "timestamp", "nullable"],
    ],
    relates: ["belongs to Submission", "optionally resolved by Reviewer"],
  },
  {
    name: "ExternalCallLog",
    reqs: ["REQ-010", "REQ-012", "REQ-014"],
    note: "Every retried external call (Basecamp, Anthropic), so failures are visible rather than silent.",
    fields: [
      ["id", "uuid", "primary key"],
      ["service", "string", "Basecamp | Anthropic | SQL Server"],
      ["operation", "string", ""],
      ["attempt_number", "integer", "bounded — no unbounded retries"],
      ["status", "enum", "success | failure"],
      ["error_message", "text", "nullable, redacted of secrets"],
      ["reference_type", "string", "Submission | ReviewItem, nullable"],
      ["reference_id", "uuid", "nullable"],
      ["occurred_at", "timestamp", ""],
    ],
    relates: ["optionally references Submission or ReviewItem"],
  },
  {
    name: "Reviewer",
    reqs: ["REQ-006", "REQ-011", "REQ-018", "REQ-020"],
    note: "Built (STORY-014) as the role list: who may sign in with Basecamp, and as what. Stored in the git-ignored data/auth/roles.json (not SQL Server); fixed admins come from AUTH_BOOTSTRAP_ADMIN_EMAILS and are never in the file. Every change is an AuditEvent.",
    fields: [
      ["email", "string", "primary key — the Basecamp email, lower-cased; how a signed-in person is matched"],
      ["role", "enum", "reviewer | admin"],
      ["updated_by", "string", "the admin who made the last change"],
      ["updated_at", "timestamp", ""],
    ],
    relates: ["has many Finding, ReviewHistoryEntry, Session"],
  },
  {
    name: "Session",
    reqs: ["REQ-020", "REQ-016"],
    note: "Built (STORY-014): one Basecamp sign-in. Held in server memory only (a restart signs everyone out). The browser keeps a random token in an HttpOnly cookie; the server keeps only its SHA-256 hash. The person's Basecamp OAuth token is used once to learn who they are and never stored.",
    fields: [
      ["token_hash", "string", "primary key — SHA-256 of the cookie token"],
      ["email", "string", "fk → Reviewer"],
      ["name", "string", "from Basecamp, shown in the app bar"],
      ["signed_in_at", "timestamp", ""],
      ["expires_at", "timestamp", "signed_in_at + 8 hours; sign-out ends it earlier"],
    ],
    relates: ["belongs to Reviewer"],
  },
];

export function renderDataModel(container, ctx, detail) {
  const h1 = document.createElement("h1");
  h1.className = "tab-title";
  h1.textContent = "Data model";
  const p = document.createElement("p");
  p.className = "tab-desc";
  p.textContent =
    "A starting proposal, derived from this project's own requirements — not the answer. Each table cites the requirement(s) it comes from; nothing here has been created in a real database yet.";
  container.append(h1, p);

  if (detail) {
    renderEntityDetail(container, ctx, detail[0]);
    return;
  }

  const grid = document.createElement("div");
  grid.className = "card-grid";
  ENTITIES.forEach((e) => {
    const card = document.createElement("button");
    card.className = "card";
    card.innerHTML = `<span class="card-label">${e.fields.length} fields</span><span class="card-value" style="font-size:17px;">${e.name}</span><span class="card-sub">${e.note}</span>`;
    card.onclick = () => navigate(`/data-model/${e.name}`);
    grid.appendChild(card);
  });
  container.appendChild(grid);
}

function renderEntityDetail(container, ctx, name) {
  renderCrumb(container, { label: name, onBack: () => navigate("/data-model") });
  const entity = ENTITIES.find((e) => e.name === name);
  if (!entity) {
    container.innerHTML += `<div class="empty-state"><h2>Not found</h2></div>`;
    return;
  }

  const h2 = document.createElement("h2");
  h2.textContent = entity.name;
  const note = document.createElement("p");
  note.textContent = entity.note;
  const reqs = document.createElement("p");
  reqs.className = "tab-desc";
  reqs.innerHTML = `Derived from: ${entity.reqs.map((r) => {
    const real = (ctx.plan.requirements || []).find((rq) => rq.id === r);
    return `<span title="${real ? escapeAttr(real.statement) : ""}">${r}</span>`;
  }).join(", ")}`;
  container.append(h2, note, reqs);

  const table = document.createElement("table");
  table.className = "data-table";
  table.innerHTML = `<thead><tr><th>Field</th><th>Type</th><th>Notes</th></tr></thead>`;
  const tbody = document.createElement("tbody");
  entity.fields.forEach(([field, type, notes]) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${field}</td><td>${type}</td><td>${notes}</td>`;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.appendChild(table);

  const h3 = document.createElement("h2");
  h3.textContent = "Relationships";
  const list = document.createElement("ul");
  list.className = "list-plain";
  list.innerHTML = entity.relates.map((r) => `<li>${r}</li>`).join("");
  container.append(h3, list);
}

function escapeAttr(str) {
  return String(str).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}
