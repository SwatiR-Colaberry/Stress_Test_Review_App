// Review Queue page (STORY-012, REQ-018). Talks to GET /queue-ui/reviews and
// GET /queue-ui/reviews/{id}; the server audits every load with the reviewer
// id and time. Reviewing itself happens on the STORY-005 page (/reviewer/).
//
// Failure handling: every request has a timeout; a failure shows a banner
// (Retry only where it may help) and never leaves old data looking current.
// Status freshness: the list and the open review reload when the tab becomes
// visible again (e.g. after approving on the reviewer page) and on Refresh.
"use strict";

const TIMEOUT_MS = 15000;
const $ = (id) => document.getElementById(id);
let rows = [];
let filter = "All";
let selected = new URLSearchParams(location.search).get("review");
let latestDetailRequest = 0; // a slow answer for an earlier click is ignored

// ---- helpers ---------------------------------------------------------------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "text") node.textContent = value; // never innerHTML: names and text come from Basecamp
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
    console.warn("reviewer id not remembered:", err.name); // private window: just not remembered
  }
  return "";
}

// One GET with a timeout. Resolves {ok, status, body, message}; never throws.
async function get(path) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(path, {
      signal: controller.signal,
      headers: { "X-Reviewer-Id": $("reviewer-id").value.trim() },
    });
    const data = await response.json().catch(() => null);
    return { ok: response.ok, status: response.status, body: data, message: explainFailure(response.status, data) };
  } catch (err) {
    return { ok: false, status: 0, body: null, message: explainFailure(0, null, err.name === "AbortError") };
  } finally {
    clearTimeout(timer);
  }
}

function showBanner(message, onRetry) {
  $("banner").hidden = false;
  $("banner-text").textContent = message;
  $("banner-retry").hidden = !onRetry;
  $("banner-retry").onclick = onRetry;
}

function when(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

const cls = (status) => `s-${status.replace(/ /g, "-")}`;

function pill(status) {
  return el("span", { class: `pill ${cls(status)}`, text: status });
}

function initials(name) {
  const words = (name || "").split(/\s+/).filter((w) => /^\p{L}/u.test(w));
  return words.length ? (words[0][0] + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase() : "?";
}

const studentOf = (row) => row.student_name || "Student name not known";

// ---- queue list ------------------------------------------------------------

async function loadQueue() {
  $("queue-meta").textContent = "Loading…";
  const result = await get("/queue-ui/reviews");
  if (!result.ok) {
    rows = [];
    renderQueue();
    $("queue-meta").textContent = "Could not load the Review Queue.";
    // Never leave an older review looking current after a failed refresh.
    if (selected) $("detail").replaceChildren(el("p", { class: "sub", text: "Could not refresh this review; see the message above." }));
    showBanner(result.message, isRetryable(result.status) ? refresh : null);
    return false;
  }
  $("banner").hidden = true;
  rows = result.body;
  renderQueue();
  $("queue-meta").textContent = `${rows.length} review${rows.length === 1 ? "" : "s"} · updated ${new Date().toLocaleTimeString()}`;
  return true;
}

function renderQueue() {
  const counts = countByStatus(rows);
  $("tiles").replaceChildren(...["All", ...STATUSES].map((s) => el("button", {
    type: "button", class: `tile ${cls(s)}`, "aria-pressed": String(s === filter),
    onclick: () => { filter = s; renderQueue(); },
  }, el("span", { class: "n", text: String(counts[s]) }), el("span", { class: "label", text: s === "All" ? "All reviews" : s }))));

  const shown = searchRows(filterRows(rows, filter), $("search").value);
  const now = Date.now();
  $("rows").replaceChildren(...shown.map((row) => {
    const open = () => openReview(row.review_id);
    return el("li", {
      class: row.review_id === selected ? "selected" : "", tabindex: "0", role: "button",
      "aria-label": `${studentOf(row)}, ${row.status}`,
      onclick: open, onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } },
    },
      el("span", { class: `avatar ${cls(row.status)}`, text: initials(row.student_name) }),
      el("span", { class: "name", text: studentOf(row) }),
      pill(row.status),
      el("span", { class: "meta", text: [stressTestName(row.stress_test_id) || "Not evaluated yet",
        `added ${relativeTime(row.created_at, now)}`, `last activity ${relativeTime(row.last_activity_at, now)}`].join(" · ") }),
    );
  }));
  $("empty").hidden = shown.length > 0;
  $("empty").textContent = rows.length ? "No reviews match this filter." : "The Review Queue is empty.";
}

// ---- one review ------------------------------------------------------------

function openReview(reviewId) {
  selected = reviewId;
  history.replaceState(null, "", `?review=${encodeURIComponent(reviewId)}`);
  renderQueue();
  return loadDetail();
}

async function loadDetail() {
  if (!selected) return;
  const request = ++latestDetailRequest;
  const panel = $("detail");
  panel.replaceChildren(el("p", { class: "sub", text: "Loading review…" }));
  const result = await get(`/queue-ui/reviews/${encodeURIComponent(selected)}`);
  if (request !== latestDetailRequest) return; // the reviewer has clicked another review since
  if (!result.ok) {
    panel.replaceChildren(
      el("p", { class: "status bad", text: `Could not load this review. ${result.message}` }),
      isRetryable(result.status) ? el("button", { type: "button", text: "Retry", onclick: loadDetail }) : null,
    );
    return;
  }
  renderDetail(result.body);
}

function renderDetail(d) {
  const stage = stageIndex(d.status);
  const link = d.basecamp_url && /^https:\/\/([a-z0-9-]+\.)*basecamp\.com\//.test(d.basecamp_url)
    ? el("a", { class: "button", href: d.basecamp_url, target: "_blank", rel: "noopener noreferrer", text: "Open in Basecamp ↗" })
    : null;
  const review = canReview(d.status) && d.stress_test_id
    ? el("a", { class: "button primary", href: `/reviewer/?review=${encodeURIComponent(d.review_id)}`,
                text: d.status === "Pending" ? "Start review" : "Continue review" })
    : null;
  const facts = [
    ["Student", studentOf(d)],
    ["Stress Test", d.stress_test_id ? `${stressTestName(d.stress_test_id)} (rules ${d.rule_version})` : "No AI draft yet"],
    ["Added to queue", when(d.created_at)],
    ["Basecamp comment", String(d.comment_id)],
    ["Review id", d.review_id],
  ];
  if (d.marker_note) facts.push(["Marker note", d.marker_note]);

  $("detail").replaceChildren(
    el("div", { class: "detail-head" },
      el("h2", { text: studentOf(d) }), pill(d.status)),
    el("p", { class: "sub", text: d.stress_test_id ? stressTestName(d.stress_test_id) : "Waiting for the AI draft" }),
    el("ol", { class: `steps ${cls(d.status)}`, "aria-label": "Progress" }, STATUSES.map((s, i) =>
      el("li", { class: [i <= stage ? "done" : "", i === stage ? "current" : ""].join(" "), text: s }))),
    el("p", { class: "sub", text: STATUS_MEANINGS[d.status] }),
    el("div", { class: "actions" }, review, link),
    el("h3", { text: "Details" }),
    el("dl", {}, facts.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })])),
    findingsSection(d.findings),
    d.prepared ? el("div", {},
      el("h3", { text: "Prepared feedback" }),
      el("p", { class: "sub", text: `By ${d.prepared.reviewer_id}, ${when(d.prepared.prepared_at)}` }),
      el("pre", { class: "prepared", text: d.prepared.feedback_text })) : null,
    el("h3", { text: "History" }),
    el("ol", { class: "timeline" }, d.history.map((h) => el("li", { class: `k-${h.kind}` },
      el("time", { text: `${when(h.at)}${actorOf(h, d) ? ` · ${actorOf(h, d)}` : ""}` }),
      h.kind === "request_received" ? `${studentOf(d)} asked for a review · ${h.summary}` : h.summary))),
  );
}

// Who took a history step, as shown: the student for the request, "AI" for the draft.
function actorOf(h, d) {
  if (h.kind === "request_received") return d.student_name || "";
  if (h.actor === "ai") return "AI";
  return h.actor || "";
}

const DECISION_WORDS = { pending: "Needs decision", approved: "Approved", rejected: "Rejected" };

function findingsSection(findings) {
  if (!findings.length) return null;
  const decided = findings.filter((f) => f.decision !== "pending").length;
  return el("div", {},
    el("h3", { text: `Findings · ${decided} of ${findings.length} decided` }),
    findings.map((f) => el("div", { class: "finding" },
      el("div", { class: "head" }, el("strong", { text: f.rule_id || "Reviewer note" }),
        el("span", { class: `tag ${f.decision}`, text: DECISION_WORDS[f.decision] + (f.edited ? " · edited" : "") })),
      el("div", { text: f.feedback_text }),
      f.edited && f.ai_draft ? el("div", { class: "ai", text: `AI's original: ${f.ai_draft.suggested_feedback}` }) : null,
    )));
}

// ---- wiring ----------------------------------------------------------------

$("status-legend").replaceChildren(...STATUSES.map((s) =>
  el("li", {}, el("span", {}, pill(s)), el("span", { text: STATUS_MEANINGS[s] }))));
$("search").addEventListener("input", renderQueue);
$("refresh").addEventListener("click", refresh);

async function refresh() {
  if (await loadQueue()) await loadDetail();
}

$("reviewer-id").value = storage("get");
// Saved on every keystroke (kept even if the reviewer never leaves the box); reload on change.
$("reviewer-id").addEventListener("input", () => storage("set", $("reviewer-id").value.trim()));
$("reviewer-id").addEventListener("change", refresh);
// Coming back (tab switch, or Back from the reviewer page, which may show a stored copy of this
// page without rerunning it): take the id saved meanwhile and reload, so status and history are current.
function comeBack() {
  const stored = storage("get");
  if (stored) $("reviewer-id").value = stored;
  refresh();
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") comeBack(); });
window.addEventListener("pageshow", (e) => { if (e.persisted) comeBack(); });
refresh();
