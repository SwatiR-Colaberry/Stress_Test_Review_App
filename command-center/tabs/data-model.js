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
      ["rule_module_id", "uuid", "fk → RuleModule"],
      ["status", "enum", "Pending | Completed"],
      ["created_at", "timestamp", ""],
      ["completed_at", "timestamp", "nullable"],
    ],
    relates: ["belongs to Submission", "has many Finding", "has many ReviewHistoryEntry"],
  },
  {
    name: "RuleModule",
    reqs: ["REQ-003", "REQ-017"],
    note: "One rule set per Stress Test id, loaded as configuration — new ST modules add a row, not a rebuild.",
    fields: [
      ["id", "uuid", "primary key"],
      ["stress_test_id", "string", "ST0, ST1, … ST5"],
      ["version", "string", ""],
      ["rules_config", "json", "the loaded rule definitions"],
    ],
    relates: ["has many ReviewItem"],
  },
  {
    name: "Finding",
    reqs: ["REQ-005", "REQ-006"],
    note: "One structured finding — AI draft or human edit — with the fields REQ-005 requires.",
    fields: [
      ["id", "uuid", "primary key"],
      ["review_item_id", "uuid", "fk → ReviewItem"],
      ["rule_id", "string", ""],
      ["status", "string", ""],
      ["severity", "string", ""],
      ["evidence", "text", ""],
      ["reason", "text", ""],
      ["confidence_score", "float", "nullable — human-added findings have none"],
      ["source", "enum", "ai_draft | human_edit"],
      ["created_by", "uuid", "fk → Reviewer, nullable for ai_draft"],
      ["created_at", "timestamp", ""],
    ],
    relates: ["belongs to ReviewItem", "optionally created by Reviewer"],
  },
  {
    name: "ReviewHistoryEntry",
    reqs: ["REQ-008", "REQ-011"],
    note: "The audit trail: every AI draft and human edit, preserved rather than overwritten.",
    fields: [
      ["id", "uuid", "primary key"],
      ["review_item_id", "uuid", "fk → ReviewItem"],
      ["actor_type", "enum", "system | human"],
      ["actor_id", "uuid", "fk → Reviewer, nullable for system"],
      ["action", "string", "created | edited | approved | rejected | posted"],
      ["prior_value", "json", "nullable"],
      ["new_value", "json", ""],
      ["occurred_at", "timestamp", ""],
    ],
    relates: ["belongs to ReviewItem", "optionally actor Reviewer"],
  },
  {
    name: "AuditEvent",
    reqs: ["REQ-011", "REQ-016"],
    note: "Built (STORY-011): one append-only record per action taken on a submission. Stored as a git-ignored JSON Lines file (data/audit/audit_trail.jsonl), not a SQL Server table — existing tables and procedures must not change. Ids and outcomes only; no free text, so no comment bodies or secrets.",
    fields: [
      ["event_id", "uuid", "primary key"],
      ["recorded_at", "timestamp", ""],
      ["action", "enum", "review_created | review_already_queued | comment_no_marker | comment_rejected_malformed | finalize_allowed | finalize_blocked"],
      ["actor_id", "string", "\"system\" for intake; reviewer id for finalize; \"unidentified\" if none named"],
      ["outcome", "enum", "success | blocked | failure"],
      ["correlation_id", "string", "X-Correlation-ID or generated"],
      ["comment_id", "bigint", "nullable — Basecamp comment (exact version)"],
      ["message_id", "bigint", "nullable — Basecamp thread"],
      ["review_id", "string", "nullable — fk → ReviewItem"],
      ["reason_code", "string", "nullable — e.g. AI_CANNOT_APPROVE"],
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
    reqs: ["REQ-006", "REQ-011", "REQ-018"],
    note: "A human account using the web UI — reviewer, human reviewer, or system administrator.",
    fields: [
      ["id", "uuid", "primary key"],
      ["basecamp_account_id", "string", ""],
      ["display_name", "string", ""],
      ["role", "enum", "reviewer | human_reviewer | system_administrator"],
    ],
    relates: ["has many Finding, ReviewHistoryEntry, OAuthGrant"],
  },
  {
    name: "OAuthGrant",
    reqs: ["REQ-012", "REQ-016"],
    note: "Session/authorization metadata only — the token value itself lives in the env/secrets layer, never this table or source control.",
    fields: [
      ["id", "uuid", "primary key"],
      ["reviewer_id", "uuid", "fk → Reviewer"],
      ["basecamp_account_id", "string", ""],
      ["scope", "string", ""],
      ["token_expires_at", "timestamp", ""],
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
