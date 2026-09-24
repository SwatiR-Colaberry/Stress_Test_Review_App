// Fetches and joins the three files the platform writes, plus the profile
// file that is yours to edit. See docs/DATA_CONTRACT.md for the field-by-field
// spec this module follows.

async function fetchJson(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return res.json();
}

export async function loadRealData() {
  const [plan, progress, manifest, profile] = await Promise.all([
    fetchJson(".colaberry/plan.json"),
    fetchJson(".colaberry/progress.json"),
    fetchJson(".colaberry/manifest.json"),
    fetchJson(".colaberry/profile.json").catch(() => null),
  ]);
  return { plan, progress, manifest, profile };
}

// Story state comes from progress, never from plan — see DATA_CONTRACT.md.
export function joinStories(plan, progress) {
  const progressById = new Map((progress.stories || []).map((s) => [s.id, s]));
  return (plan.stories || []).map((story) => {
    const p = progressById.get(story.id);
    const verification = p?.verification ?? null;
    return {
      ...story,
      progress: p ?? null,
      state: verification?.state ?? "not_started",
      criteriaPassed: verification?.criteria_passed ?? 0,
      criteriaTotal: verification?.criteria_total ?? (story.acceptance || []).length,
      pointsAwarded: verification?.points_awarded ?? null,
    };
  });
}

export function progressById(progress) {
  return new Map((progress.stories || []).map((s) => [s.id, s]));
}

// A requirement is "built" when every story that fulfils it is verified.
// Derived, never stored — there is no `built` field in plan.json by design.
export function isRequirementBuilt(req, progById) {
  const fulfilledBy = req.fulfilled_by || [];
  if (fulfilledBy.length === 0) return false;
  return fulfilledBy.every((id) => progById.get(id)?.verification?.state === "verified");
}

export function requirementStoryStates(req, progById) {
  return (req.fulfilled_by || []).map((id) => ({
    id,
    state: progById.get(id)?.verification?.state ?? "not_started",
  }));
}

// --- Freshness ("Data as of ...") ---

const DAY_MS = 24 * 60 * 60 * 1000;

export function computeFreshness(generatedAtIso, now = new Date()) {
  const generatedAt = new Date(generatedAtIso);
  const ageMs = now.getTime() - generatedAt.getTime();
  const ageDays = Math.floor(ageMs / DAY_MS);
  // Compare exact elapsed time, not the floored day count — data that is
  // 7 days and 21 hours old is already "over a week", even though it
  // hasn't reached a floored ageDays of 8 yet.
  const stale = ageMs > 7 * DAY_MS;

  const absolute = generatedAt.toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  let relative;
  if (ageDays <= 0) {
    const ageHours = Math.max(0, Math.floor(ageMs / (60 * 60 * 1000)));
    relative = ageHours <= 0 ? "just now" : `${ageHours} hour${ageHours === 1 ? "" : "s"} ago`;
  } else if (ageDays === 1) {
    relative = "1 day ago";
  } else {
    relative = `${ageDays} days ago`;
  }

  return { generatedAt, ageDays, stale, absolute, relative };
}

export function formatDate(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
