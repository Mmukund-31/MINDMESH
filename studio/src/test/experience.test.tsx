import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { MemoryImpactView, PolicyImpactView } from "@/components/Impact";
import { RunModeBadge } from "@/components/LiveRun";
import { Scorecard, improvementSummary } from "@/components/Scorecard";
import { modelName, narrate, runMode } from "@/lib/narrate";
import type { EvalMetrics, EvalRun, MemoryImpact, MMEvent, PolicyImpact } from "@/lib/types";

const ev = (type: string, payload: Record<string, unknown>, step: number | null = 1): MMEvent => ({
  id: `evt_${type}`,
  run_id: "run_1",
  seq: 1,
  type,
  step,
  span_id: "s",
  parent_span_id: null,
  ts: new Date().toISOString(),
  duration_ms: null,
  payload,
});

describe("run modes", () => {
  it("labels demo, live and replay runs", () => {
    expect(runMode({ kind: "live", model: "scripted:refund-support?think_ms=650" })).toBe("demo");
    expect(runMode({ kind: "rerun", model: "ollama:qwen3:4b" })).toBe("live");
    expect(runMode({ kind: "replay", model: "ollama:qwen3:4b" })).toBe("replay");
    expect(modelName("scripted:refund-support?think_ms=650")).toBe("refund-support");
    expect(modelName("ollama:qwen3:4b")).toBe("qwen3:4b");
    render(<RunModeBadge run={{ kind: "live", model: "ollama:qwen3:4b" }} />);
    expect(screen.getByTestId("mode-live")).toHaveTextContent("Live model · qwen3:4b");
  });
});

describe("narrate", () => {
  it("explains exclusions, policy blocks and injected faults in plain language", () => {
    const ctx = narrate(
      ev("context.assembled", {
        included: [{ kind: "task" }, { kind: "memory" }],
        excluded: [{ subject_key: "refund_policy", reason: "scope_mismatch" }, { subject_key: "x", reason: "low_relevance" }],
        used_tokens: 120,
        budget_tokens: 900,
      }),
    )!;
    expect(ctx.text).toBe("Context assembled: 1 included, 2 excluded (120/900 tokens)");
    expect(ctx.detail).toBe("excluded refund_policy: not visible to this agent");

    const deny = narrate(
      ev("policy.decision", { tool: "refund.issue", args: { amount: 4999 }, effect: "deny", rule_name: "block-large-refunds", reason: "too big" }),
    )!;
    expect(deny).toMatchObject({ tone: "bad", text: "Policy blocked refund.issue(amount=4999)", detail: "rule block-large-refunds: too big" });

    const retry = narrate(ev("tool.retry", { tool: "crm.lookup", attempt: 1, backoff_s: 0.2, error: "503", injected: true }))!;
    expect(retry.detail).toBe("injected fault: 503");
    expect(narrate(ev("tool.started", { tool: "crm.lookup" }))).toBeNull();
    expect(narrate(ev("model.called", { response: '{"type":"tool_call","tool":"orders.get","args":{"order_id":"A-1"}}' }))!.text).toBe(
      'Model chose orders.get(order_id="A-1")',
    );
  });
});

const metrics = (over: Partial<EvalMetrics>): EvalMetrics => ({
  tasks: 7,
  success_rate: 1,
  evidence_recall: 1,
  context_precision: 0.48,
  context_efficiency: 0.5,
  unsafe_actions_executed: 0,
  unsafe_actions_blocked: 1,
  tool_error_rate: 0,
  recovery_rate: 1,
  approvals_requested: 1,
  avg_steps: 4,
  avg_tokens: 900,
  avg_latency_ms: 10,
  ...over,
});
const evalRun = (variant: string, m: EvalMetrics): EvalRun => ({
  id: variant, suite: "refund", variant, model: "scripted", seed: 0, metrics: m, created_at: new Date().toISOString(),
});

describe("Scorecard", () => {
  it("grades each configuration against the targets", () => {
    const before = metrics({ success_rate: 4 / 7, evidence_recall: 2 / 7, recovery_rate: 0 });
    const baseline = metrics({ success_rate: 3 / 7, unsafe_actions_executed: 1, recovery_rate: 0 });
    render(<Scorecard runs={[evalRun("baseline", baseline), evalRun("mindmesh-misconfigured", before), evalRun("mindmesh", metrics({}))]} />);
    const success = screen.getByTestId("score-success_rate");
    expect(within(success).getByText("43% (3/7)")).toBeInTheDocument();
    expect(within(success).getByText("100% (7/7)")).toBeInTheDocument();
    expect(within(screen.getByTestId("score-unsafe_actions_executed")).getByText("1 executed · 1 blocked")).toBeInTheDocument();
    expect(screen.getByText("MindMesh after the fix")).toBeInTheDocument();

    const summary = improvementSummary(baseline, before, metrics({}));
    expect(summary[0]).toBe(
      "The memory fix alone took correct decisions from 4/7 (57%) to 7/7 (100%): the current policy was in the agent's context 29% of the time before, 100% after.",
    );
    expect(summary[1]).toBe(
      "Compared with a typical agent stack (3/7 (43%) correct), MindMesh executed 0 unsafe refunds instead of 1, and recovered 100% of tasks hit by injected outages instead of 0%.",
    );
  });
});

describe("impact views", () => {
  it("shows a memory change's visibility, supersession and context effect", () => {
    const impact: MemoryImpact = {
      memory: { id: "mem_new", subject_key: "refund_policy", version: 1 },
      changes: { scope: { before: "agent:billing", after: "project" } },
      new_version: 2,
      supersedes: [
        { id: "mem_new", subject_key: "refund_policy", scope: "agent:billing", content: "30 days", version: 1 },
        { id: "mem_old", subject_key: "refund_policy", scope: "project", content: "14 days", version: 1 },
      ],
      visibility: [{ agent: "support", scopes: ["project", "agent:support"], before: false, after: true }],
      runs: [{
        run_id: "run_1", agent: "support", kind: "live", task: "t", answer: "DENIED", query: "q",
        newly_included: [{ item_id: "new-version", subject_key: "refund_policy", scope: "project", content: "30 days", reason: null, detail: null }],
        newly_excluded: [{ item_id: "mem_old", subject_key: "refund_policy", scope: "project", content: "14 days", reason: "superseded", detail: null }],
        used_tokens: { before: 100, after: 110 },
      }],
    };
    render(<MemoryRouter><MemoryImpactView impact={impact} /></MemoryRouter>);
    expect(screen.getByText("gains access")).toBeInTheDocument();
    expect(screen.getByText("becomes superseded")).toBeInTheDocument(); // only the other memory, not the edited one
    expect(screen.getByTestId("impact-included")).toHaveTextContent("would now be in context: 30 days");
    expect(screen.getByTestId("impact-excluded")).toHaveTextContent("would leave context: 14 days (replaced by a newer version)");
  });

  it("shows which recorded policy decisions would flip", () => {
    const impact: PolicyImpact = {
      rules: [{ rule: "block-large-refunds", change: "modified", fields: ["enabled"], before: { enabled: true }, after: { enabled: false } }],
      evaluated: 6, unchanged: 5, changed: 1, transitions: { "deny->require_approval": 1 },
      changes: [{
        run_id: "run_1", agent: "support", kind: "live", step: 3, tool: "refund.issue", args: { amount: 4999 },
        before: { effect: "deny", rule_name: "block-large-refunds", reason: "" },
        after: { effect: "require_approval", rule_name: "approve-refunds-over-100", reason: "" },
      }],
      note: "n",
    };
    render(<MemoryRouter><PolicyImpactView impact={impact} /></MemoryRouter>);
    expect(screen.getByText(/1× blocked → needs approval/)).toBeInTheDocument();
    expect(screen.getByTestId("policy-flip")).toHaveTextContent("refund.issue(amount=4999)");
    expect(screen.getByTestId("policy-flip")).toHaveTextContent("approve-refunds-over-100");
  });
});
