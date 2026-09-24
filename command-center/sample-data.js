// Sample mode reuses the REAL plan.json — the requirements and stories are
// this project's actual plan, not invented — and swaps in a synthetic
// progress.json/manifest.json so you can see what a further-along project
// looks like. Every number here is fictional and the UI must label it as
// such everywhere it appears (see chrome.js's sample banner + per-card tag).

const SAMPLE_STORY_STATES = {
  "STORY-000": { state: "submitted", passed: 3, total: 5 },
  "STORY-001": { state: "verified", passed: 3, total: 3 },
  "STORY-002": { state: "verified", passed: 3, total: 3 },
  "STORY-011": { state: "verified", passed: 3, total: 3 },
  "STORY-006": { state: "verified", passed: 3, total: 3 },
  "STORY-003": { state: "submitted", passed: 2, total: 3 },
  "STORY-012": { state: "submitted", passed: 2, total: 3 },
  "STORY-004": { state: "in_progress", passed: 1, total: 3 },
  "STORY-005": { state: "in_progress", passed: 0, total: 3 },
  "STORY-007": { state: "in_progress", passed: 0, total: 3 },
  "STORY-008": { state: "in_progress", passed: 0, total: 3 },
  "STORY-009": { state: "in_progress", passed: 0, total: 3 },
  "STORY-010": { state: "in_progress", passed: 0, total: 3 },
};

export function buildSampleData(realPlan) {
  const stories = Object.entries(SAMPLE_STORY_STATES).map(([id, s]) => ({
    id,
    release: (realPlan.stories || []).find((r) => r.id === id)?.release ?? null,
    acceptance_total: s.total,
    criteria: Array.from({ length: s.total }, (_, i) => ({
      text: `Sample criterion ${i + 1} for ${id}`,
      passed: i < s.passed,
    })),
    files_touched: [],
    tests_added: [],
    notes: "Sample data — for illustration only.",
    updated_at: null,
    verification: {
      state: s.state,
      criteria_passed: s.passed,
      criteria_total: s.total,
      verified_at: s.state === "verified" ? new Date().toISOString() : null,
      commit_sha: s.state === "verified" ? "sample0commit" : null,
      commit_url: null,
      commit_at: null,
      points_awarded: 50,
      outstanding: [],
    },
  }));

  const stories_total = stories.length;
  const stories_verified = stories.filter((s) => s.verification.state === "verified").length;
  const stories_submitted = stories.filter((s) => s.verification.state === "submitted").length;
  const stories_in_progress = stories.filter((s) => s.verification.state === "in_progress").length;
  const stories_not_started = stories_total - stories_verified - stories_submitted - stories_in_progress;
  const criteria_total = stories.reduce((n, s) => n + s.verification.criteria_total, 0);
  const criteria_passed = stories.reduce((n, s) => n + s.verification.criteria_passed, 0);
  const points_awarded = stories.reduce((n, s) => n + s.verification.points_awarded, 0);

  const progress = {
    schema_version: 2,
    project: realPlan.project?.name ?? null,
    totals: {
      stories_total,
      stories_verified,
      stories_submitted,
      stories_in_progress,
      stories_not_started,
      criteria_total,
      criteria_passed,
      points_awarded,
    },
    stories,
  };

  const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
  const manifest = {
    generated_at: threeHoursAgo,
    plan_version: realPlan.project?.plan_version ?? 1,
    plan_sha256: "sample-not-a-real-hash",
    correlation_id: "sample-correlation-id",
    project_id: "sample-project-id",
    truth_revision: 1,
    files: [],
  };

  const profile = {
    schema_version: 1,
    disclosure: "private",
    headline: "Sample headline — for illustration only.",
    summary: "Sample summary text describing the project's portfolio pitch.",
    challenge: null,
    highlight_story_ids: ["STORY-001", "STORY-011"],
    links: { repo: realPlan.project?.repo_url ?? null, command_center: null },
    include: { requirement_statements: true, measures: true, systems: true, narrative: true },
  };

  return { plan: realPlan, progress, manifest, profile };
}
