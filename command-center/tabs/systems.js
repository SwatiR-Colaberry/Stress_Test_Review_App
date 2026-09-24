// Systems — plan.derived.systems is a list of names extracted from
// requirement text. That is ALL these files know. Nothing here can prove a
// system is actually connected, so every indicator starts grey and stays
// grey until this project's own running system reports otherwise.

import { renderCrumb, sampleTag } from "../chrome.js";
import { navigate } from "../router.js";

export function renderSystems(container, ctx, detail) {
  const { plan, mode } = ctx;
  const systems = plan.derived?.systems || [];

  const h1 = document.createElement("h1");
  h1.className = "tab-title";
  h1.textContent = "Systems";
  const p = document.createElement("p");
  p.className = "tab-desc";
  p.textContent =
    "What this project's requirements name as external systems. Whether any one of them is actually connected right now is a fact about the running system, not this repo — so every indicator reads “not checked from here” until the app itself reports a status.";
  container.append(h1, p);

  if (detail) {
    renderDetail(container, ctx, decodeURIComponent(detail[0]));
    return;
  }

  if (systems.length === 0) {
    container.innerHTML += `<div class="empty-state"><h2>No systems named</h2></div>`;
    return;
  }

  const table = document.createElement("table");
  table.className = "data-table";
  table.innerHTML = `<thead><tr><th>System</th><th>Status</th><th>Last checked</th><th></th></tr></thead>`;
  const tbody = document.createElement("tbody");
  systems.forEach((name) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${name}</td>
      <td><span class="status-dot"></span>Not checked from here</td>
      <td>Never</td>
      <td><button class="link-btn">Details →</button></td>
    `;
    tr.querySelector("button").onclick = () => navigate(`/systems/${encodeURIComponent(name)}`);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.appendChild(table);

  if (mode === "sample") {
    const note = document.createElement("p");
    note.className = "tab-desc";
    note.style.marginTop = "12px";
    note.appendChild(sampleTag());
    note.append(" Even in Sample mode, connection status is never faked — this is a fact only the running system can report.");
    container.appendChild(note);
  }
}

function renderDetail(container, ctx, name) {
  const { plan } = ctx;
  renderCrumb(container, { label: name, onBack: () => navigate("/systems") });

  const h2 = document.createElement("h2");
  h2.textContent = name;
  container.appendChild(h2);

  const status = document.createElement("p");
  status.innerHTML = `<span class="status-dot"></span> Not checked from here — this page has no live connection to test.`;
  container.appendChild(status);

  const related = (plan.requirements || []).filter((r) =>
    (r.statement || "").toLowerCase().includes(name.toLowerCase())
  );

  const h3 = document.createElement("h2");
  h3.textContent = "Named in";
  container.appendChild(h3);

  if (related.length === 0) {
    container.innerHTML += `<div class="empty-state"><h2>No requirement text matches this name</h2></div>`;
    return;
  }

  const list = document.createElement("ul");
  list.className = "list-plain";
  list.innerHTML = related.map((r) => `<li><strong>${r.id}</strong> — ${r.statement}</li>`).join("");
  container.appendChild(list);
}
