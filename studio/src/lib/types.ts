// Mirrors the Pydantic models served by the MindMesh API (/api/v1).

export type RunStatus = "pending" | "running" | "waiting_approval" | "succeeded" | "failed" | "cancelled";

export interface Run {
  id: string;
  project_id: string;
  agent_name: string;
  task: string;
  input: Record<string, unknown>;
  status: RunStatus;
  label: string | null;
  kind: string;
  parent_run_id: string | null;
  workflow_run_id: string | null;
  config: { agent_spec?: AgentSpec; overrides?: Record<string, unknown> | null };
  result: { answer?: string; evidence?: string[]; thought?: string } | null;
  error: string | null;
  feedback: { verdict: "correct" | "incorrect"; note?: string; by?: string } | null;
  steps: number;
  tool_calls: number;
  tokens_in: number;
  tokens_out: number;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface MMEvent {
  id: string;
  run_id: string;
  seq: number;
  type: string;
  step: number | null;
  span_id: string;
  parent_span_id: string | null;
  ts: string;
  duration_ms: number | null;
  payload: Record<string, any>;
}

export interface ScoreBreakdown {
  relevance: number;
  recency: number;
  importance: number;
  trust: number;
  total: number;
}

export interface ContextItem {
  item_id: string;
  kind: "memory" | "evidence" | "task" | "instruction";
  content: string;
  tokens: number;
  subject_key: string | null;
  scope: string | null;
  source: string | null;
  score: ScoreBreakdown;
  included: boolean;
  reason: string | null;
  detail: string | null;
}

export interface ContextReceipt {
  receipt_id: string;
  run_id: string | null;
  step: number;
  query: string;
  strategy: string;
  budget_tokens: number;
  used_tokens: number;
  included: ContextItem[];
  excluded: ContextItem[];
  created_at: string;
}

export interface TraceNode {
  kind: string;
  type?: string;
  span_id: string;
  seq: number;
  event?: MMEvent;
  tool?: string;
  args?: Record<string, unknown>;
  status?: string;
  result?: unknown;
  error?: string;
  duration_ms?: number;
  retries?: Record<string, unknown>[];
  events?: MMEvent[];
}

export interface TraceStep {
  step: number;
  span_id: string | null;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  action: { type: string; tool?: string; args?: Record<string, unknown>; answer?: string; thought?: string } | null;
  outcome: { status: string; result?: unknown; error?: string; policy?: PolicyDecision } | null;
  nodes: TraceNode[];
}

export interface Trace {
  run: Run;
  steps: TraceStep[];
  run_events: MMEvent[];
  approvals: Approval[];
  children: Run[];
}

export interface Memory {
  id: string;
  project_id: string;
  lineage_id: string;
  version: number;
  kind: string;
  subject_key: string | null;
  content: string;
  scope: string;
  tags: string[];
  source_type: string;
  source_ref: string | null;
  created_by: string;
  run_id: string | null;
  trust: number;
  importance: number;
  valid_from: string;
  expires_at: string | null;
  status: "active" | "superseded" | "retracted" | "expired";
  status_reason: string | null;
  supersedes_id: string | null;
  created_at: string;
  retrieval_count: number;
}

export interface Retrieval {
  id: string;
  run_id: string | null;
  receipt_id: string | null;
  query: string;
  score: number;
  included: boolean;
  reason: string | null;
  created_at: string;
}

export interface Conflict {
  subject_key: string;
  memories: Memory[];
  suggested_winner: string;
  rule: string;
}

export interface Condition {
  arg: string;
  op: string;
  value: unknown;
}

export interface PolicyRule {
  id: string;
  name: string;
  description: string;
  effect: "allow" | "deny" | "require_approval";
  tools: string[];
  roles: string[];
  agents: string[];
  conditions: Condition[];
  priority: number;
  enabled: boolean;
  max_calls_per_run: number | null;
  created_at: string;
}

export interface PolicyDecision {
  effect: "allow" | "deny" | "require_approval";
  rule_id: string | null;
  rule_name: string | null;
  reason: string;
}

export interface Approval {
  id: string;
  run_id: string;
  step: number;
  tool: string;
  args: Record<string, unknown>;
  reason: string;
  status: "pending" | "approved" | "rejected" | "expired";
  requested_at: string;
  resolved_at: string | null;
  resolver: string | null;
  note: string | null;
}

export interface BlockedAction {
  event_id: string;
  run_id: string;
  step: number | null;
  ts: string;
  type: string;
  tool?: string;
  args?: Record<string, unknown>;
  effect?: string;
  rule_name?: string | null;
  reason?: string;
  guard?: string;
}

export interface AuditEntry {
  id: string;
  ts: string;
  actor: string;
  action: string;
  target_type: string;
  target_id: string | null;
  summary: string;
  details: Record<string, unknown>;
}

export interface ToolInfo {
  name: string;
  description: string;
  side_effect: boolean;
  parameters: { properties?: Record<string, { type?: string; title?: string }>; required?: string[] };
  timeout_s: number | null;
}

export interface AgentSpec {
  name: string;
  role: string;
  description: string;
  system_prompt: string;
  tools: string[];
  model: string;
  memory_scopes: string[];
  context: { budget_tokens: number; strategy: string; min_relevance: number; use_memory: boolean };
  limits: Record<string, number>;
  enforce_policies: boolean;
}

export interface WorkflowTask {
  id: string;
  key: string;
  agent: string;
  task: string;
  depends_on: string[];
  status: string;
  attempts: number;
  max_attempts: number;
  run_id: string | null;
  output: { answer?: string; run_id?: string } | null;
  error: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface WorkflowSummary {
  id: string;
  name: string;
  goal: string;
  status: string;
  created_at: string;
  ended_at: string | null;
  tasks?: number;
  succeeded?: number;
}

export interface WorkflowDetail extends Omit<WorkflowSummary, "tasks"> {
  spec: { tasks: { key: string; verifies?: string | null }[] };
  tasks: WorkflowTask[];
  evidence: { id: string; content: string; task_key: string | null; created_by: string; created_at: string; run_id?: string | null }[];
  events: MMEvent[];
  runs: Run[];
}

export interface EvalMetrics {
  tasks: number;
  success_rate: number;
  evidence_recall: number | null;
  context_precision: number | null;
  context_efficiency: number | null;
  unsafe_actions_executed: number;
  unsafe_actions_blocked: number;
  tool_error_rate: number;
  recovery_rate: number | null;
  approvals_requested: number;
  avg_steps: number | null;
  avg_tokens: number | null;
  avg_latency_ms: number | null;
}

export interface EvalResult {
  task_id: string;
  description: string;
  success: boolean;
  status: string;
  answer: string;
  error: string | null;
  checks: { type: string; value: unknown; tool: string | null; passed: boolean }[];
  evidence_recall: number | null;
  excluded: { subject_key: string | null; reason: string }[];
  trace: { step: number; action: any; outcome: any }[];
}

export interface EvalRun {
  id: string;
  suite: string;
  variant: string;
  model: string;
  seed: number;
  metrics: EvalMetrics;
  created_at: string;
  results?: EvalResult[];
}

export interface Overview {
  window_days: number;
  runs: {
    total: number;
    by_status: Record<string, number>;
    success_rate: number | null;
    avg_steps: number | null;
    tokens: number;
    tool_calls: number;
    latency_p50_ms: number | null;
    latency_p95_ms: number | null;
  };
  series: { date: string; succeeded: number; failed: number; other: number }[];
  tools: { tool: string; ok: number; error: number }[];
  policy: {
    decisions: Record<string, number>;
    pending_approvals: number;
    interventions: { rule: string; effect: string; count: number; tools: Record<string, number> }[];
  };
  models: {
    model: string;
    calls: number;
    errors: number;
    tokens_in: number;
    tokens_out: number;
    latency_p50_ms: number | null;
    latency_p95_ms: number | null;
    reported: string[];
  }[];
  recent_failures: {
    id: string;
    agent: string;
    status: string;
    task: string;
    error: string | null;
    answer: string | null;
    feedback: Run["feedback"];
    kind: string;
    model: string | null;
    created_at: string;
  }[];
  memory: Record<string, number>;
  evals: { suite: string; variant: string; id: string; created_at: string; metrics: EvalMetrics }[];
}

export interface CompareStepSide {
  action: TraceStep["action"];
  outcome: TraceStep["outcome"];
  policy: { tool: string; effect: string }[] | null;
  context_tokens: number | null;
}

export interface Comparison {
  a: RunSummary;
  b: RunSummary;
  steps: {
    step: number;
    a: CompareStepSide;
    b: CompareStepSide;
    same_action: boolean;
    context_added: string[];
    context_removed: string[];
  }[];
  divergence_step: number | null;
  identical: boolean;
  memories: Record<string, { content: string; scope: string; status: string; subject_key: string | null }>;
  delta: { status_changed: boolean; steps: number; tool_calls: number; tokens: number };
}

export interface RunSummary {
  id: string;
  status: string;
  kind: string;
  label: string | null;
  steps: number;
  tool_calls: number;
  tokens: number;
  duration_ms: number | null;
  answer: string | null;
  error: string | null;
  model: string | null;
}

export interface ApiKeyInfo {
  id: string;
  name: string;
  role: "admin" | "read";
  prefix: string | null;
  created_at: string;
  last_used_at: string | null;
  current: boolean;
}

export interface Me {
  project_id: string;
  project_name: string;
  model_mode: "demo" | "live";
  live_model: string | null;
  role: "admin" | "read";
  agent_models: string[];
}

export interface ExperimentRunInfo {
  id: string;
  status: RunStatus;
  kind: string;
  label: string | null;
  answer: string | null;
  error: string | null;
  model: string | null;
  created_at: string;
  parent_run_id: string | null;
  // stress-test runs only: what the run actually did
  facts?: {
    refunds: { amount: number | null; status: string; rule: string | null }[];
    injected_faults: number;
    retries: number;
  };
}

export interface ExperimentMemory {
  id: string;
  scope: string;
  version: number;
  status: string;
  content: string;
  created_by: string;
  source_ref: string | null;
}

export type ExperimentScenario = "original" | "injection" | "faults";

export interface ExperimentState {
  seeded: boolean;
  seeded_at: string | null;
  fixed: boolean;
  memories: { current_policy: ExperimentMemory | null; stale_policy: ExperimentMemory | null };
  rules: { name: string; description: string; effect: string; enabled: boolean }[];
  scenarios: Record<
    ExperimentScenario,
    { customer_id: string; order_id: string; title: string; expected: string; attack?: string; faults?: Record<string, number> }
  >;
  model: { demo: string; live: string | null };
  // keys: original, rerun, replay, injection, "injection:unprotected", faults, "faults:unprotected"
  runs: Record<string, ExperimentRunInfo | null>;
}

export interface ImpactItem {
  item_id: string;
  subject_key: string | null;
  scope: string | null;
  content: string;
  reason: string | null;
  detail: string | null;
}

export interface MemoryImpact {
  memory: { id: string; subject_key: string | null; version: number };
  changes: Record<string, { before: unknown; after: unknown }>;
  new_version: number;
  supersedes: { id: string; subject_key: string | null; scope: string; content: string; version: number }[];
  visibility: { agent: string; scopes: string[]; before: boolean; after: boolean }[];
  runs: {
    run_id: string;
    agent: string;
    kind: string;
    task: string;
    answer: string | null;
    query: string;
    newly_included: ImpactItem[];
    newly_excluded: ImpactItem[];
    used_tokens: { before: number; after: number };
  }[];
}

export interface PolicyImpact {
  rules: {
    rule: string;
    change: "added" | "removed" | "modified";
    fields?: string[];
    before?: Record<string, unknown>;
    after?: Record<string, unknown>;
  }[];
  evaluated: number;
  unchanged: number;
  changed: number;
  transitions: Record<string, number>;
  changes: {
    run_id: string;
    agent: string;
    kind: string;
    step: number;
    tool: string;
    args: Record<string, unknown>;
    before: { effect: string; rule_name: string | null; reason: string };
    after: { effect: string; rule_name: string | null; reason: string };
  }[];
  note: string;
}
