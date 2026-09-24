// Shared "not built yet" renderer for the 8 tabs beyond Overview. Reachable
// and un-gated by design (per STORY-000: "must not look locked, greyed out,
// or gated" while the build is paused for review) — the card still drills
// down one level, to a detail view that repeats the same honest state.

import { renderCrumb } from "../chrome.js";
import { navigate } from "../router.js";

export function renderPlaceholder(container, { tabId, label, blurb }, detail) {
  const h1 = document.createElement("h1");
  h1.className = "tab-title";
  h1.textContent = label;
  container.appendChild(h1);

  const p = document.createElement("p");
  p.className = "tab-desc";
  p.textContent = blurb;
  container.appendChild(p);

  if (detail) {
    renderCrumb(container, { label: "Not built yet", onBack: () => navigate(`/${tabId}`) });
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = `<h2>Not built yet</h2><p>Say <strong>build the rest</strong> when Overview looks right, and this tab gets built next.</p>`;
    container.appendChild(empty);
    return;
  }

  const grid = document.createElement("div");
  grid.className = "card-grid";
  const card = document.createElement("button");
  card.className = "card";
  card.innerHTML = `<span class="card-label">Status</span><span class="card-value" style="font-size:16px;">Not built yet</span><span class="card-sub">Say "build the rest" when Overview looks right</span>`;
  card.onclick = () => navigate(`/${tabId}/coming-soon`);
  grid.appendChild(card);
  container.appendChild(grid);
}
