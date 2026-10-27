import type {
  AgentSpec,
  ApiKeyInfo,
  AuditEntry,
  Approval,
  BlockedAction,
  Comparison,
  Conflict,
  ContextReceipt,
  EvalRun,
  ExperimentScenario,
  ExperimentState,
  Me,
  Memory,
  MemoryImpact,
  MMEvent,
  Overview,
  PolicyDecision,
  PolicyImpact,
  PolicyRule,
  Retrieval,
  Run,
  ToolInfo,
  Trace,
  WorkflowDetail,
  WorkflowSummary,
} from "./types";

// A deployment's public Studio build bakes in its read-only demo key; local development uses the dev key.
export const DEFAULT_KEY = (import.meta.env.VITE_DEFAULT_API_KEY as string | undefined) || "mm_dev_local_key_change_me";
const KEY_STORAGE = "mindmesh.apiKey";
const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

export function getApiKey(): string {
  try {
    return localStorage.getItem(KEY_STORAGE) || DEFAULT_KEY;
  } catch {
    return DEFAULT_KEY;
  }
}

export function setApiKey(key: string) {
  try {
    localStorage.setItem(KEY_STORAGE, key);
  } catch {
    /* storage unavailable: key lives for this session only */
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, params?: Record<string, unknown>): Promise<T> {
  const url = new URL(`${BASE}/api/v1${path}`, window.location.origin);
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => url.searchParams.append(k, String(x)));
    else url.searchParams.set(k, String(v));
  }
  const res = await fetch(url, {
    method,
    headers: { "X-API-Key": getApiKey(), ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const get = <T>(p: string, params?: Record<string, unknown>) => request<T>("GET", p, undefined, params);

/** Download a JSON export (the API key goes in a header, so a plain link cannot be used). */
export async function downloadJson(path: string, filename: string, params?: Record<string, unknown>) {
  const doc = await get<unknown>(path, params);
  const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
const post = <T>(p: string, body?: unknown) => request<T>("POST", p, body ?? {});

export interface Health {
  status: "ok" | "unavailable";
  database?: string;
}

/** Download a text export (e.g. a Markdown report) with the API key in a header. */
export async function downloadText(path: string, filename: string, params?: Record<string, unknown>) {
  const url = new URL(`${BASE}/api/v1${path}`, window.location.origin);
  for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  const res = await fetch(url, { headers: { "X-API-Key": getApiKey() } });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  const blob = new Blob([await res.text()], { type: res.headers.get("content-type") ?? "text/plain" });
  const href = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

/** Unauthenticated liveness: API up and database reachable. */
export async function health(): Promise<Health> {
  const res = await fetch(new URL(`${BASE}/healthz`, window.location.origin));
  return (await res.json()) as Health;
}

export const api = {
  me: () => get<Me>("/me"),
  overview: async () => {
    const d = await get<Overview>("/stats/overview");
    // Older servers do not report these yet: degrade to empty lists instead of crashing the page.
    return { ...d, models: d.models ?? [], policy: { ...d.policy, interventions: d.policy?.interventions ?? [] } };
  },

  runs: (params?: Record<string, unknown>) => get<Run[]>("/runs", params),
  run: (id: string) => get<Run>(`/runs/${id}`),
  trace: (id: string) => get<Trace>(`/runs/${id}/trace`),
  events: (id: string, after = 0) => get<MMEvent[]>(`/runs/${id}/events`, { after }),
  receipts: (id: string) => get<ContextReceipt[]>(`/runs/${id}/receipts`),
  startRun: (body: { agent: string; task: string; input?: Record<string, unknown>; label?: string }) =>
    post<Run>("/runs", body),
  cancelRun: (id: string) => post<Run>(`/runs/${id}/cancel`),
  feedback: (id: string, verdict: "correct" | "incorrect", note?: string) =>
    post<Run>(`/runs/${id}/feedback`, { verdict, note }),
  replay: (id: string) => post<Run>(`/runs/${id}/replay`),
  rerun: (id: string, overrides?: Record<string, unknown>) => post<Run>(`/runs/${id}/rerun`, overrides ?? {}),
  compare: (a: string, b: string) => get<Comparison>("/compare", { a, b }),

  memories: (params?: Record<string, unknown>) => get<Memory[]>("/memories", params),
  memory: (id: string) => get<Memory>(`/memories/${id}`),
  searchMemories: (q: string, include_inactive = false) =>
    get<{ memory: Memory; similarity: number; keyword: number; relevance: number }[]>("/memories/search", {
      q,
      include_inactive,
      k: 30,
    }),
  createMemory: (body: Record<string, unknown>) => post<Memory>("/memories", body),
  updateMemory: (id: string, body: Record<string, unknown>) => request<Memory>("PATCH", `/memories/${id}`, body),
  retractMemory: (id: string, reason: string) => post<Memory>(`/memories/${id}/retract`, { reason }),
  versions: (id: string) => get<Memory[]>(`/memories/${id}/versions`),
  retrievals: (id: string) => get<Retrieval[]>(`/memories/${id}/retrievals`),
  conflicts: () => get<Conflict[]>("/memories/conflicts"),
  memoryImpact: (id: string, change: Record<string, unknown>) =>
    post<MemoryImpact>(`/memories/${id}/impact`, { change }),
  previewContext: (body: { query: string; agent?: string }) => post<ContextReceipt>("/context/preview", body),

  policies: () => get<PolicyRule[]>("/policies"),
  policiesYaml: () => get<{ yaml: string }>("/policies/yaml"),
  putPoliciesYaml: (yaml: string) => request<PolicyRule[]>("PUT", "/policies/yaml", { yaml }),
  updatePolicy: (id: string, body: Record<string, unknown>) => request<PolicyRule>("PUT", `/policies/${id}`, body),
  createPolicy: (body: Record<string, unknown>) => post<PolicyRule>("/policies", body),
  deletePolicy: (id: string) => request<void>("DELETE", `/policies/${id}`),
  policyImpact: (body: { yaml: string } | { disable: string[] }) => post<PolicyImpact>("/policies/impact", body),
  simulate: (body: { tool: string; agent: string; args: Record<string, unknown> }) =>
    post<PolicyDecision>("/policies/simulate", body),
  approvals: (status?: string) => get<Approval[]>("/approvals", { status }),
  resolveApproval: (id: string, approve: boolean, note?: string) =>
    post<Approval>(`/approvals/${id}/resolve`, { approve, note, resolver: "studio-user" }),
  blocked: () => get<BlockedAction[]>("/blocked-actions"),
  audit: (target_type?: string) => get<AuditEntry[]>("/audit", { target_type, limit: 300 }),
  tools: () => get<ToolInfo[]>("/tools"),
  agents: () => get<AgentSpec[]>("/agents"),

  experiment: () => get<ExperimentState>("/experiments/refund"),
  resetExperiment: () => post<ExperimentState>("/experiments/refund/reset"),
  startExperiment: (scenario: ExperimentScenario, opts?: { protected?: boolean; mode?: "demo" | "live" }) =>
    post<Run>("/experiments/refund/runs", { scenario, ...opts }),

  workflows: () => get<WorkflowSummary[]>("/workflows"),
  workflow: (id: string) => get<WorkflowDetail>(`/workflows/${id}`),
  workflowTemplates: () => get<{ name: string; goal: string }[]>("/workflows/templates"),
  startWorkflow: (template: string) => post<WorkflowSummary>("/workflows", { template }),

  evalSuites: () =>
    get<{ name: string; description: string; variants: Record<string, string>; tasks: { id: string }[] }[]>(
      "/evals/suites",
    ),
  evals: (suite?: string) => get<EvalRun[]>("/evals", { suite }),
  keys: () => get<ApiKeyInfo[]>("/keys"),
  createKey: (name: string, role: "admin" | "read") => post<ApiKeyInfo & { key: string }>("/keys", { name, role }),
  revokeKey: (id: string) => request<void>("DELETE", `/keys/${id}`),
  evalRun: (id: string) => get<EvalRun>(`/evals/${id}`),
  startEval: (suite: string, variants?: string[], model?: string) =>
    post<{ id: string; status: string }>("/evals", { suite, variants, model }),
  evalJob: (id: string) => get<{ id: string; status: string; eval_ids: string[]; error: string | null }>(
    `/evals/jobs/${id}`,
  ),
};

/** EventSource cannot send headers, so the stream URL carries a short-lived token bound to this run
 * (minted with the API key in a header) instead of the API key itself. */
export async function streamUrl(runId: string, after = 0): Promise<string> {
  const { token } = await post<{ token: string; expires_in: number }>(`/runs/${runId}/stream-token`);
  const u = new URL(`${BASE}/api/v1/runs/${runId}/stream`, window.location.origin);
  u.searchParams.set("after", String(after));
  u.searchParams.set("token", token);
  return u.toString();
}
