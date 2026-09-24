// Shared chrome: header (title, data-as-of stamp, sample/real switch) + tab
// nav + the sample-mode banner. Every tab is mounted inside the element this
// returns, so the chrome (and its "Data as of" stamp) never has to be
// rebuilt per-tab.

import { navigate } from "./router.js";

export function renderChrome(root, ctx) {
  const { tabs, activeTabId, mode, onModeChange, projectName, repoName, freshness } = ctx;

  root.innerHTML = "";

  const header = document.createElement("div");
  header.className = "shell-header";

  const top = document.createElement("div");
  top.className = "shell-header-top";

  const title = document.createElement("div");
  title.className = "shell-title";
  title.innerHTML = `${escapeHtml(projectName || "Command Center")}<span class="repo-name">${escapeHtml(
    repoName || ""
  )}</span>`;

  const freshnessEl = document.createElement("div");
  freshnessEl.className = "freshness" + (freshness.stale ? " stale" : "");
  freshnessEl.innerHTML = freshness.stale
    ? `<span>Data as of ${freshness.absolute} (${freshness.relative})</span><span class="pill">⚠ over a week old — sync from the portal to refresh</span>`
    : `<span>Data as of ${freshness.absolute} (${freshness.relative})</span>`;

  const modeToggle = document.createElement("div");
  modeToggle.className = "mode-toggle";
  const sampleBtn = document.createElement("button");
  sampleBtn.textContent = "Sample";
  sampleBtn.className = mode === "sample" ? "active" : "";
  sampleBtn.onclick = () => onModeChange("sample");
  const realBtn = document.createElement("button");
  realBtn.textContent = "Real";
  realBtn.className = mode === "real" ? "active" : "";
  realBtn.onclick = () => onModeChange("real");
  modeToggle.append(sampleBtn, realBtn);

  const rightGroup = document.createElement("div");
  rightGroup.style.display = "flex";
  rightGroup.style.alignItems = "center";
  rightGroup.style.gap = "16px";
  rightGroup.append(freshnessEl, modeToggle);

  top.append(title, rightGroup);

  const nav = document.createElement("nav");
  nav.className = "tabs";
  tabs.forEach((tab) => {
    const btn = document.createElement("button");
    btn.textContent = tab.label;
    btn.className = tab.id === activeTabId ? "active" : "";
    btn.onclick = () => navigate(`/${tab.id}`);
    nav.appendChild(btn);
  });

  header.append(top, nav);

  if (mode === "sample") {
    const banner = document.createElement("div");
    banner.className = "sample-banner";
    banner.textContent = "SAMPLE DATA — every number and status below is fictional, for illustration only";
    header.appendChild(banner);
  }

  const main = document.createElement("main");
  main.className = "content";

  const footer = document.createElement("footer");
  footer.className = "shell-footer";
  footer.textContent =
    "“Live” means as of the last sync from the portal, not real-time. Read-only view of .colaberry/plan.json, progress.json and manifest.json.";

  root.append(header, main, footer);
  return main;
}

export function renderCrumb(container, { label, onBack }) {
  const crumb = document.createElement("div");
  crumb.className = "crumb";
  const back = document.createElement("button");
  back.textContent = "← Back";
  back.onclick = onBack;
  crumb.appendChild(back);
  if (label) {
    const span = document.createElement("span");
    span.textContent = `  /  ${label}`;
    crumb.appendChild(span);
  }
  container.appendChild(crumb);
}

export function sampleTag() {
  const span = document.createElement("span");
  span.className = "tag sample";
  span.textContent = "Sample";
  return span;
}

const STATE_TAG_CLASS = {
  verified: "ok",
  submitted: "warn",
  in_progress: "unknown",
  not_started: "unknown",
};

const STATE_LABEL = {
  verified: "Verified",
  submitted: "Submitted",
  in_progress: "In progress",
  not_started: "Not started",
};

export function stateTagHtml(state) {
  const cls = STATE_TAG_CLASS[state] || "unknown";
  const label = STATE_LABEL[state] || state || "Unknown";
  return `<span class="tag ${cls}">${label}</span>`;
}

export function statusDotHtml(kind, label) {
  const cls = kind === "ok" ? "ok" : kind === "warn" ? "warn" : kind === "danger" ? "danger" : "";
  return `<span><span class="status-dot ${cls}"></span>${escapeHtml(label)}</span>`;
}

export function escapeHtml(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
