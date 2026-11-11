/**
 * Ting-Yi001 external scheduler (Cloudflare Workers Free).
 * Runs at :07, :27 and :47 UTC; GitHub hourly :37 remains backup.
 * NO forecasting or Metaculus credentials live here: only a GitHub Actions token.
 *
 * API responses prove dispatch acceptance, not forecast success.
 */
const OWNER = "Ting-YiLin";
const REPO = "metac-bot-template";
const WORKFLOW = "run_bot_testing_area.yaml";
const BRANCH = "main";
const API = "https://api.github.com/repos/" + OWNER + "/" + REPO;
const ACTIVE_STATES = new Set(["queued", "in_progress", "pending", "waiting", "requested"]);
const RECENT_MS = 15 * 60 * 1000;
const ACTIVE_MS = 50 * 60 * 1000;

export function decideFromRuns(runs, nowMs = Date.now()) {
  if (!Array.isArray(runs)) throw new Error("INVALID_RUN_LIST");
  for (const run of runs) {
    if (typeof run !== "object" || run === null) continue;
    const created = Date.parse(run.created_at || "");
    if (!Number.isFinite(created)) continue;
    const elapsed = nowMs - created;
    if (elapsed < 0) continue;
    // Avoid a duplicate immediately after an external or hourly backup trigger.
    if (elapsed < RECENT_MS) {
      return { action: "SKIP", reason: "RECENT_RUN", run_id: run.id ?? null };
    }
    // Old permanently queued runs must not block the scheduler indefinitely.
    if (elapsed < ACTIVE_MS && ACTIVE_STATES.has(run.status)) {
      return { action: "SKIP", reason: "RECENT_ACTIVE_RUN", run_id: run.id ?? null };
    }
  }
  return { action: "DISPATCH", reason: "NO_RECENT_BUSY_RUN" };
}

function authHeaders(token) {
  return {
    "Accept": "application/vnd.github+json",
    "Authorization": "Bearer " + token,
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "TingYi001-External-Scheduler"
  };
}

async function githubFetch(url, options, doFetch) {
  const response = await doFetch(url, {
    ...options,
    signal: AbortSignal.timeout(10000),
  });
  if (response.status === 401 || response.status === 403) {
    throw new Error("GITHUB_CREDENTIALS_OR_PERMISSIONS_" + response.status);
  }
  if (!response.ok) {
    throw new Error("GITHUB_API_STATUS_" + response.status);
  }
  return response;
}

export async function dispatchScheduled(env, { nowMs = Date.now(), doFetch = fetch } = {}) {
  const token = env.GITHUB_DISPATCH_TOKEN;
  if (!token || typeof token !== "string") {
    throw new Error("CLOUDFLARE_SECRET_NOT_CONFIGURED");
  }
  const headers = authHeaders(token);
  const lookup = await githubFetch(
    API + "/actions/workflows/" + WORKFLOW + "/runs?per_page=25",
    { method: "GET", headers }, doFetch
  );
  const body = await lookup.json();
  if (!Array.isArray(body.workflow_runs)) throw new Error("INVALID_GITHUB_WORKFLOW_RESPONSE");
  const decision = decideFromRuns(body.workflow_runs, nowMs);
  if (decision.action === "SKIP") {
    return { ...decision, time_utc: new Date(nowMs).toISOString() };
  }
  const submit = await githubFetch(
    API + "/actions/workflows/" + WORKFLOW + "/dispatches",
    {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ ref: BRANCH, return_run_details: true }),
    },
    doFetch
  );
  let runId = null;
  if (submit.status === 200) {
    const response = await submit.json();
    runId = response.workflow_run_id ?? null;
  }
  return {
    action: "DISPATCH_ACCEPTED",
    status_code: submit.status,
    run_id: runId,
    time_utc: new Date(nowMs).toISOString(),
  };
}

export default {
  async scheduled(controller, env, ctx) {
    try {
      const result = await dispatchScheduled(env);
      console.log(JSON.stringify({ component: "tingyi001-dispatcher", ...result }));
    } catch (error) {
      // Never log tokens, request headers or raw response bodies.
      console.error(JSON.stringify({
        component: "tingyi001-dispatcher",
        action: "ERROR",
        error_type: error instanceof Error ? error.message : "UNKNOWN",
      }));
      throw error;
    }
  },
  async fetch() {
    // External/public requests must not allow arbitrary manual dispatch.
    return new Response("Not Found", { status: 404 });
  },
};
