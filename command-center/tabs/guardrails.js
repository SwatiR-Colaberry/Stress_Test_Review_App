// Guardrails — the SAFE requirements this project must never violate.
// Enforcement is derived: follow requirement.fulfilled_by to story ids, then
// read those stories' verification.state. Not verified = promised, not kept.

import { renderCrumb, sampleTag, stateTagHtml } from "../chrome.js";
import { navigate } from "../router.js";
import { requirementStoryStates, progressById } from "../data.js";

export function renderGuardrails(container, ctx, detail) {
  const { plan, progress, mode } = ctx;
  const guardrails = plan.derived?.guardrails || [];
  const progById = progressById(progress);

  const h1 = document.createElement("h1");
  h1.className = "tab-title";
  h1.textContent = "Guardrails";
  const p = document.createElement("p");
  p.className = "tab-desc";
  p.textContent = "The promises this project makes about what must never happen, and whether the build currently enforces each one.";
  container.append(h1, p);

  if (guardrails.length === 0) {
    container.innerHTML += `<div class="empty-state"><h2>No SAFE requirements in the plan</h2><p>This is worth fixing — a controlled review platform with human-in-the-loop approval should have guardrails defined.</p></div>`;
    return;
  }

  if (detail) {
    renderDetail(container, ctx, detail[0], progById);
    return;
  }

  const grid = document.createElement("div");
  grid.className = "card-grid";
  guardrails.forEach((g) => {
    const req = (plan.requirements || []).find((r) => r.id === g.id);
    const states = req ? requirementStoryStates(req, progById) : [];
    const allVerified = states.length > 0 && states.every((s) => s.state === "verified");
    const card = document.createElement("button");
    card.className = "card";
    card.innerHTML = `<span class="card-label">${g.id}</span><span class="card-value" style="font-size:15px;">${escapeShort(g.statement)}</span><span class="card-sub">${allVerified ? "Enforced" : "Not yet enforced"}</span>`;
    if (mode === "sample") card.appendChild(sampleTag());
    card.onclick = () => navigate(`/guardrails/${g.id}`);
    grid.appendChild(card);
  });
  container.appendChild(grid);
}

function escapeShort(text) {
  return text.length > 100 ? text.slice(0, 97) + "…" : text;
}

function renderDetail(container, ctx, reqId, progById) {
  const { plan } = ctx;
  renderCrumb(container, { label: reqId, onBack: () => navigate("/guardrails") });

  const req = (plan.requirements || []).find((r) => r.id === reqId);
  if (!req) {
    container.innerHTML += `<div class="empty-state"><h2>Not found</h2></div>`;
    return;
  }

  const h2 = document.createElement("h2");
  h2.textContent = req.id;
  const p = document.createElement("p");
  p.textContent = req.statement;
  container.append(h2, p);

  const states = requirementStoryStates(req, progById);
  const h3 = document.createElement("h2");
  h3.textContent = "Enforced by";
  container.appendChild(h3);

  if (states.length === 0) {
    container.innerHTML += `<div class="empty-state"><h2>No story fulfils this requirement yet</h2><p>This is a promise this project has made and not yet started keeping.</p></div>`;
    return;
  }

  const allVerified = states.every((s) => s.state === "verified");
  const banner = document.createElement("p");
  banner.className = "tab-desc";
  banner.innerHTML = allVerified
    ? "<strong>Enforced</strong> — every story that fulfils this requirement is verified."
    : "<strong>Not yet enforced</strong> — a promise this project has made and not yet kept.";
  container.appendChild(banner);

  const list = document.createElement("ul");
  list.className = "list-plain";
  list.innerHTML = states.map((s) => `<li><strong>${s.id}</strong> ${stateTagHtml(s.state)}</li>`).join("");
  container.appendChild(list);
}
