// Minimal hash router: #/<tabId>/<...detailPath>

export function parseHash() {
  const raw = (window.location.hash || "").replace(/^#\/?/, "");
  const parts = raw.split("/").filter(Boolean);
  return { tabId: parts[0] || null, detail: parts.slice(1) };
}

export function navigate(path) {
  window.location.hash = path.startsWith("/") ? path : `/${path}`;
}

export function onRouteChange(handler) {
  window.addEventListener("hashchange", handler);
}
