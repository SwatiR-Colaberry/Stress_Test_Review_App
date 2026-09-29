// Reviewer page (STORY-005). Plain JavaScript, no build step.
//
// Failure paths handled:
// - the review cannot load (network, timeout, 404, 503) -> a visible banner
//   with the reason and a Retry button; nothing else is shown half-loaded.
// - an edit/decision is not saved (network, timeout, 503) -> the reviewer's
//   text stays in the box, the finding is marked "Not saved", and Retry
//   resends the SAME request (same action_id), which the server applies once.
// - a refused action (401/403/409) -> the reason in plain words.
// All student and reviewer text is inserted with textContent, never as HTML.
"use strict";

const TIMEOUT_MS = 10000;
const MAX_FINDING_CHARS = 2000;
const REASONS = {
  MISSING_REVIEWER_IDENTITY: "Enter your reviewer id at the top first.",
  AI_CANNOT_REVIEW: "That id belongs to an AI or system account. Only a human reviewer can review.",
  UNKNOWN_FINDING: "This finding no longer exists. Reload the page.",
  UNDECIDED_FINDINGS: "Every finding needs a decision (approve, edit or reject) first.",
  REVIEW_LOCKED: "Feedback for this review is already prepared, so it can no longer change.",
  ACTION_ID_REUSED: "This click was already used for a different change. Please try again.",
  EMPTY_FEEDBACK: "Nothing to send: approve at least one finding or add your own note.",
  FEEDBACK_TOO_LONG: "The feedback is over 10,000 characters. Please shorten some points.",
  REVIEW_NOT_FOUND: "This review is not in the Review Queue.",
  NO_AI_DRAFT: "This review has no AI draft yet.",
};

const reviewId = new URLSearchParams(location.search).get("review");
const $ = (id) => document.getElementById(id);
let view = null;
const unsaved = new Map(); // finding_id or "add" -> the action that failed to save

// ---- helpers ---------------------------------------------------------------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "text") node.textContent = value;
    else if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  children.flat().forEach((child) => child && node.append(child));
  return node;
}

function storage(action, value) {
  try {
    if (action === "get") return localStorage.getItem("reviewer-id") || "";
    localStorage.setItem("reviewer-id", value);
  } catch (err) {
    // Storage blocked (private window): the id just is not remembered.
    console.warn("reviewer id not remembered:", err.name);
  }
  return "";
}

function newActionId() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return `a-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// One request with a timeout. Resolves {ok, status, body, message}; never throws.
async function call(method, path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(path, {
      method,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", "X-Reviewer-Id": $("reviewer-id").value.trim() },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response.json().catch(() => null);
    return { ok: response.ok, status: response.status, body: data, message: explain(response.status, data) };
  } catch (err) {
    const message = err.name === "AbortError"
      ? "The server did not answer in time. Your work is kept here; retry."
      : "Could not reach the server (network problem). Your work is kept here; retry.";
    return { ok: false, status: 0, body: null, message };
  } finally {
    clearTimeout(timer);
  }
}

function explain(status, data) {
  const detail = data && data.detail;
  if (detail && detail.reason_code && REASONS[detail.reason_code]) return REASONS[detail.reason_code];
  if (status === 503) return "Not saved: storage or the audit trail is unavailable. Retry; it is safe.";
  if (status === 422) return "That change is not valid (check the text length and fields).";
  if (detail && detail.message) return detail.message;
  return `Unexpected answer from the server (${status}).`;
}

function retryable(result) {
  return result.status === 0 || result.status === 503;
}

// ---- loading ---------------------------------------------------------------

function showBanner(message, onRetry) {
  $("banner").hidden = false;
  $("banner-text").textContent = message;
  $("banner-retry").hidden = !onRetry;
  $("banner-retry").onclick = onRetry;
}

async function load() {
  if (!reviewId) {
    showBanner("No review chosen. Open this page as /reviewer/?review=<review id>.");
    $("review-meta").textContent = "";
    return;
  }
  $("review-meta").textContent = "Loading…";
  const result = await call("GET", `/reviews/${encodeURIComponent(reviewId)}/findings`);
  if (!result.ok) {
    $("review-meta").textContent = "Could not load this review.";
    showBanner(result.message, retryable(result) ? load : null);
    return;
  }
  $("banner").hidden = true;
  render(result.body);
}

// ---- rendering -------------------------------------------------------------

function render(next) {
  view = next;
  const locked = Boolean(view.prepared);
  renderTitle();
  $("findings").replaceChildren(...view.findings.map((f) => findingCard(f, locked)));
  if (!view.findings.length) {
    $("findings").append(el("p", { class: "sub", text: "The AI raised no findings. Add your own note below." }));
  }
  $("add").hidden = locked;
  renderPrepare(locked);
}

// Top line: "ST0 · Student name · Open in Basecamp". The link is only made
// for an https basecamp.com address (the server checks this too).
function renderTitle() {
  const parts = [el("strong", { text: view.stress_test_id }), view.student_name || "Student name not available"];
  if (view.basecamp_url && /^https:\/\/([a-z0-9-]+\.)*basecamp\.com\//.test(view.basecamp_url)) {
    parts.push(el("a", { href: view.basecamp_url, target: "_blank", rel: "noopener noreferrer", text: "Open in Basecamp ↗" }));
  }
  $("title").replaceChildren(...parts.flatMap((part, i) => (i ? [" · ", part] : [part])));
  $("review-meta").replaceChildren(el("details", {},
    el("summary", { text: "Show details" }),
    el("span", { text: `Review ${view.review_id} · comment ${view.comment_id} · rules ${view.rule_version}` })));
}

function findingCard(f, locked) {
  const failed = unsaved.get(f.finding_id);
  const box = el("textarea", { rows: "3", maxlength: String(MAX_FINDING_CHARS), "aria-label": `Feedback for ${f.finding_id}` });
  box.value = failed && failed.text ? failed.text : f.feedback_text;
  box.disabled = locked;
  const count = el("span", { class: "count", text: `${box.value.length} / ${MAX_FINDING_CHARS}` });
  const status = el("p", { class: failed ? "status bad" : "status", text: failed ? `Not saved. ${failed.message}` : "" });
  box.addEventListener("input", () => { count.textContent = `${box.value.length} / ${MAX_FINDING_CHARS}`; });

  const act = (kind) => send(f.finding_id, { action_id: newActionId(), kind, finding_id: f.finding_id,
                                              ...(kind === "edit_finding" ? { text: box.value } : {}) }, status);
  const buttons = locked ? [] : [
    el("button", { type: "button", text: "Approve", onclick: () => act("approve_finding") }),
    el("button", { type: "button", text: "Save edit", onclick: () => act("edit_finding") }),
    el("button", { type: "button", text: "Reject", onclick: () => act("reject_finding") }),
    failed ? el("button", { type: "button", class: "primary", text: "Retry", onclick: () => send(f.finding_id, failed.action, status) }) : null,
  ];

  // Compact: the rule in plain words, severity, decision, the text and the
  // buttons. Codes, evidence and who/when are one click away in "Show details".
  const ai = f.ai_draft;
  const title = (f.rule_id && view.rule_names[f.rule_id]) || f.rule_id || "Your note";
  return el("article", { class: `card ${f.decision}` },
    el("div", { class: "head" },
      el("strong", { text: title }),
      el("span", { class: "tag", text: ai ? ai.severity : "Added by reviewer" }),
      el("span", { class: `tag ${f.decision}`, text: DECISIONS[f.decision] + (f.edited ? " · edited" : "") })),
    box,
    el("div", { class: "row" }, count, ...buttons),
    status,
    findingDetails(f, ai));
}

const DECISIONS = { pending: "Needs decision", approved: "Approved", rejected: "Rejected" };

function findingDetails(f, ai) {
  const rows = [];
  const add = (label, value) => rows.push(el("dt", { text: label }), el("dd", { text: value }));
  if (f.rule_id) add("Rule", f.rule_id);
  if (ai) {
    add("AI result", ai.status === "ADVISORY" ? "Advisory: check this yourself" : "Fail");
    add("Evidence", ai.evidence);
    add("Why", ai.reason);
    add("AI confidence", `${Math.round(ai.confidence * 100)}%`);
    if (f.edited) add("AI's original wording", ai.suggested_feedback);
  }
  if (f.decided_by) add("Decided", `by ${f.decided_by}, ${new Date(f.decided_at).toLocaleString()}`);
  return el("details", {}, el("summary", { text: "Show details" }), el("dl", {}, ...rows));
}

function renderPrepare(locked) {
  $("prepare").hidden = false;
  const pending = view.findings.filter((f) => f.decision === "pending").length;
  $("prepare-button").hidden = locked;
  $("prepare-button").disabled = pending > 0;
  $("prepare-hint").textContent = locked
    ? `Prepared by ${view.prepared.reviewer_id} at ${new Date(view.prepared.prepared_at).toLocaleString()}. Ready to post to Basecamp.`
    : pending ? `${pending} finding${pending > 1 ? "s" : ""} still need${pending > 1 ? "" : "s"} a decision.`
              : "Every finding has a decision. Approved findings become the feedback; rejected ones are left out.";
  $("prepared-text").hidden = !locked;
  $("prepared-text").textContent = locked ? view.prepared.feedback_text : "";
}

// ---- actions ---------------------------------------------------------------

async function send(key, action, status) {
  status.className = "status";
  status.textContent = "Saving…";
  const result = await call("POST", `/reviews/${encodeURIComponent(reviewId)}/actions`, action);
  if (result.ok) {
    unsaved.delete(key);
    render(result.body);
    return true;
  }
  if (retryable(result)) {
    // Keep the request so Retry resends it unchanged (same action_id).
    unsaved.set(key, { action, text: action.text, message: result.message });
    if (key !== "add") { render(view); return false; } // the card now shows "Not saved" + Retry
  }
  // Refused, or the add box: show the reason in place; the typed text stays.
  status.className = "status bad";
  status.textContent = retryable(result) ? `Not saved. ${result.message}` : result.message;
  return false;
}

async function addFinding() {
  const failed = unsaved.get("add");
  const text = $("add-text").value;
  const rule = $("add-rule").value.trim();
  // Same text as the failed attempt -> resend it with the same action_id.
  const action = failed && failed.text === text.trim() ? failed.action
    : { action_id: newActionId(), kind: "add_finding", text, ...(rule ? { rule_id: rule } : {}) };
  if (await send("add", action, $("add-status"))) {
    $("add-text").value = "";
    $("add-rule").value = "";
    $("add-count").textContent = `0 / ${MAX_FINDING_CHARS}`;
  } else if (unsaved.has("add")) {
    $("add-button").textContent = "Retry add";
  }
}

async function prepare() {
  const status = $("prepare-status");
  status.className = "status";
  status.textContent = "Preparing…";
  const result = await call("POST", `/reviews/${encodeURIComponent(reviewId)}/prepare`);
  if (!result.ok) {
    status.className = "status bad";
    status.textContent = result.message;
    return;
  }
  status.className = "status ok";
  status.textContent = "Prepared. It will be posted to Basecamp by the posting step.";
  await load();
}

// ---- start -----------------------------------------------------------------

$("reviewer-id").value = storage("get");
$("reviewer-id").addEventListener("change", (e) => storage("set", e.target.value.trim()));
$("add-text").addEventListener("input", (e) => {
  $("add-count").textContent = `${e.target.value.length} / ${MAX_FINDING_CHARS}`;
  $("add-button").textContent = "Add finding";
});
$("add-button").addEventListener("click", addFinding);
$("prepare-button").addEventListener("click", prepare);
load();
