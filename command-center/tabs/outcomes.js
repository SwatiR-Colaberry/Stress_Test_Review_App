// Outcomes — the numbers this project has to move. plan.derived.measures
// carries the target statement only; it never carries the measured value,
// because that comes from the running system, not the plan. Every card
// reads "not measured yet" rather than a zero, which would read as a result.

import { renderCrumb, sampleTag } from "../chrome.js";
import { navigate } from "../router.js";

export function renderOutcomes(container, ctx, detail) {
  const { plan, mode } = ctx;
  const measures = plan.derived?.measures || [];

  const h1 = document.createElement("h1");
  h1.className = "tab-title";
  h1.textContent = "Outcomes";
  const p = document.createElement("p");
  p.className = "tab-desc";
  p.textContent =
    "The numbers this project committed to moving. This project's files know the target, never the measurement — that comes from the running system, once it exists.";
  container.append(h1, p);

  if (detail) {
    renderDetail(container, ctx, detail[0]);
    return;
  }

  if (measures.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<h2>No measures defined</h2><p>plan.derived.measures is empty for this project.</p>";
    container.appendChild(empty);
    return;
  }

  const grid = document.createElement("div");
  grid.className = "card-grid";
  measures.forEach((m) => {
    const card = document.createElement("button");
    card.className = "card";
    card.innerHTML = `<span class="card-label">${m.id}</span><span class="card-value" style="font-size:16px;">Not measured yet</span><span class="card-sub">${escapeShort(m.statement)}</span>`;
    if (mode === "sample") card.appendChild(sampleTag());
    card.onclick = () => navigate(`/outcomes/${m.id}`);
    grid.appendChild(card);
  });
  container.appendChild(grid);
}

function escapeShort(text) {
  return text.length > 90 ? text.slice(0, 87) + "…" : text;
}

function renderDetail(container, ctx, measureId) {
  const { plan, progress } = ctx;
  renderCrumb(container, { label: measureId, onBack: () => navigate("/outcomes") });

  const measure = (plan.derived?.measures || []).find((m) => m.id === measureId);
  if (!measure) {
    container.innerHTML += `<div class="empty-state"><h2>Not found</h2></div>`;
    return;
  }
  const req = (plan.requirements || []).find((r) => r.id === measureId);
  const progById = new Map((progress.stories || []).map((s) => [s.id, s]));

  const section = document.createElement("div");
  section.className = "detail-section";
  section.innerHTML = `
    <h2>${measure.id}</h2>
    <p>${measure.statement}</p>
    <p class="tab-desc"><strong>Current value:</strong> not measured yet — this file only records the target, not a live measurement.</p>
  `;
  container.appendChild(section);

  if (req) {
    const stories = req.fulfilled_by || [];
    const h2 = document.createElement("h2");
    h2.textContent = "Fulfilled by";
    container.appendChild(h2);
    if (stories.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.innerHTML = "<h2>No story fulfils this yet</h2>";
      container.appendChild(empty);
    } else {
      const list = document.createElement("ul");
      list.className = "list-plain";
      list.innerHTML = stories
        .map((id) => `<li>${id} — ${progById.get(id)?.verification?.state ?? "not_started"}</li>`)
        .join("");
      container.appendChild(list);
    }
  }
}
