// Knowledge base — requirements-to-stories traceability, a local search
// panel over this project's own data (not a hosted LLM — this page is
// static and cannot hold an API key), and free-text notes that persist only
// in this browser.

import { stateTagHtml } from "../chrome.js";
import { isRequirementBuilt, progressById } from "../data.js";

const NOTES_KEY = "ccKnowledgeNotes";

export function renderKnowledgeBase(container, ctx) {
  const { plan, progress } = ctx;
  const progById = progressById(progress);

  const h1 = document.createElement("h1");
  h1.className = "tab-title";
  h1.textContent = "Knowledge base";
  const p = document.createElement("p");
  p.className = "tab-desc";
  p.textContent = "Everything this project knows about itself: requirements, stories, traceability, and notes you add as you go.";
  container.append(h1, p);

  container.appendChild(renderSearchPanel(plan, progress));
  container.appendChild(renderTraceability(plan, progById));
  container.appendChild(renderNotes());
}

function renderTraceability(plan, progById) {
  const wrap = document.createElement("div");
  wrap.className = "detail-section";
  const h2 = document.createElement("h2");
  h2.textContent = "Requirements traceability";
  wrap.appendChild(h2);

  const table = document.createElement("table");
  table.className = "data-table";
  table.innerHTML = `<thead><tr><th>Requirement</th><th>Kind</th><th>Priority</th><th>Fulfilled by</th><th>Built?</th></tr></thead>`;
  const tbody = document.createElement("tbody");
  (plan.requirements || []).forEach((r) => {
    const built = isRequirementBuilt(r, progById);
    const gap = (r.fulfilled_by || []).length === 0;
    const tr = document.createElement("tr");
    if (gap && r.priority === "must") tr.style.background = "var(--danger-weak)";
    tr.innerHTML = `
      <td><strong>${r.id}</strong><div class="card-sub" style="margin-top:2px;">${r.statement}</div></td>
      <td>${r.kind}</td>
      <td>${r.priority}</td>
      <td>${
        gap
          ? '<span class="tag danger">No story yet</span>'
          : r.fulfilled_by.map((id) => `${id} ${stateTagHtml(progById.get(id)?.verification?.state ?? "not_started")}`).join("<br/>")
      }</td>
      <td>${built ? '<span class="tag ok">Yes</span>' : '<span class="tag unknown">Not yet</span>'}</td>
    `;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function searchProjectData(plan, progress, query) {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const results = [];

  (plan.requirements || []).forEach((r) => {
    if (r.id.toLowerCase() === q || r.statement.toLowerCase().includes(q)) {
      results.push({ tab: "Knowledge base", text: `${r.id} — ${r.statement}` });
    }
  });
  (plan.stories || []).forEach((s) => {
    if (s.id.toLowerCase() === q || (s.narrative || "").toLowerCase().includes(q) || (s.title || "").toLowerCase().includes(q)) {
      results.push({ tab: "Project management", text: `${s.id} — ${s.title}: ${s.narrative}` });
    }
  });
  (plan.derived?.guardrails || []).forEach((g) => {
    if (g.statement.toLowerCase().includes(q) || g.id.toLowerCase() === q) {
      results.push({ tab: "Guardrails", text: `${g.id} — ${g.statement}` });
    }
  });
  (plan.derived?.measures || []).forEach((m) => {
    if (m.statement.toLowerCase().includes(q) || m.id.toLowerCase() === q) {
      results.push({ tab: "Outcomes", text: `${m.id} — ${m.statement}` });
    }
  });
  (plan.derived?.systems || []).forEach((sys) => {
    if (sys.toLowerCase().includes(q)) {
      results.push({ tab: "Systems", text: sys });
    }
  });
  (plan.derived?.roles || []).forEach((role) => {
    if (role.toLowerCase().includes(q)) {
      results.push({ tab: "Users & use case", text: role });
    }
  });

  return results.slice(0, 8);
}

function renderSearchPanel(plan, progress) {
  const wrap = document.createElement("div");
  wrap.className = "detail-section card";

  const h2 = document.createElement("h2");
  h2.textContent = "Ask about this project";
  const note = document.createElement("p");
  note.className = "card-sub";
  note.textContent = "Local search over this page's own data — not a hosted AI. A static page can't hold an API key, so this looks for keyword matches and says so plainly when it finds none.";

  const form = document.createElement("div");
  form.style.display = "flex";
  form.style.gap = "8px";
  form.style.margin = "10px 0";
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "e.g. credentials, Basecamp, human review";
  input.style.flex = "1";
  input.style.padding = "8px 10px";
  input.style.border = "1px solid var(--border)";
  input.style.borderRadius = "6px";
  input.style.background = "var(--surface)";
  input.style.color = "var(--text)";
  const button = document.createElement("button");
  button.textContent = "Ask";
  button.style.padding = "8px 16px";
  button.style.border = "none";
  button.style.borderRadius = "6px";
  button.style.background = "var(--accent)";
  button.style.color = "#fff";
  button.style.fontWeight = "600";
  form.append(input, button);

  const results = document.createElement("div");
  results.style.marginTop = "8px";

  function runSearch() {
    const matches = searchProjectData(plan, progress, input.value);
    if (!input.value.trim()) {
      results.innerHTML = "";
      return;
    }
    if (matches.length === 0) {
      results.innerHTML = `<div class="empty-state"><h2>Can't answer that from this project's data</h2><p>No requirement, story, guardrail, measure, system or role matched "${escapeHtml(
        input.value
      )}".</p></div>`;
      return;
    }
    results.innerHTML = `<ul class="list-plain">${matches
      .map((m) => `<li><span class="tag unknown">${m.tab}</span> ${escapeHtml(m.text)}</li>`)
      .join("")}</ul>`;
  }

  button.onclick = runSearch;
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSearch();
  });

  wrap.append(h2, note, form, results);
  return wrap;
}

function escapeHtml(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function loadNotes() {
  try {
    return JSON.parse(localStorage.getItem(NOTES_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveNotes(notes) {
  try {
    localStorage.setItem(NOTES_KEY, JSON.stringify(notes));
  } catch {
    /* private-browsing or storage disabled — notes just won't persist */
  }
}

function renderNotes() {
  const wrap = document.createElement("div");
  wrap.className = "detail-section";
  const h2 = document.createElement("h2");
  h2.textContent = "Notes";
  const note = document.createElement("p");
  note.className = "card-sub";
  note.textContent = "Saved only in this browser (localStorage) — not synced to your repo or shared with anyone else viewing this page.";
  wrap.append(h2, note);

  const form = document.createElement("div");
  form.style.display = "flex";
  form.style.gap = "8px";
  form.style.margin = "10px 0";
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Add a note…";
  input.style.flex = "1";
  input.style.padding = "8px 10px";
  input.style.border = "1px solid var(--border)";
  input.style.borderRadius = "6px";
  input.style.background = "var(--surface)";
  input.style.color = "var(--text)";
  const button = document.createElement("button");
  button.textContent = "Add";
  button.style.padding = "8px 16px";
  button.style.border = "none";
  button.style.borderRadius = "6px";
  button.style.background = "var(--accent)";
  button.style.color = "#fff";
  button.style.fontWeight = "600";
  form.append(input, button);
  wrap.appendChild(form);

  const list = document.createElement("ul");
  list.className = "list-plain";
  wrap.appendChild(list);

  function renderList() {
    const notes = loadNotes();
    list.innerHTML = notes.length
      ? notes.map((n) => `<li>${escapeHtml(n.text)} <span class="card-sub">— ${new Date(n.at).toLocaleString()}</span></li>`).join("")
      : `<li class="card-sub">No notes yet.</li>`;
  }

  button.onclick = () => {
    const text = input.value.trim();
    if (!text) return;
    const notes = loadNotes();
    notes.push({ text, at: new Date().toISOString() });
    saveNotes(notes);
    input.value = "";
    renderList();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") button.onclick();
  });

  renderList();
  return wrap;
}
