import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ReceiptPanel } from "@/components/ReceiptPanel";
import { DiffView } from "@/components/DiffView";
import { StatusBadge } from "@/components/common";
import { describeNode, stepTitle } from "@/components/TraceGraph";
import type { Comparison, ContextItem, ContextReceipt, TraceStep } from "@/lib/types";
import { fmtPct, shortId } from "@/lib/utils";

const item = (over: Partial<ContextItem>): ContextItem => ({
  item_id: "mem_1",
  kind: "memory",
  content: "Refund policy: 14 days.",
  tokens: 12,
  subject_key: "refund_policy",
  scope: "project",
  source: "import:handbook-v1 (v1, active)",
  score: { relevance: 0.8, recency: 0.2, importance: 0.9, trust: 0.6, total: 0.71 },
  included: true,
  reason: null,
  detail: null,
  ...over,
});

const receipt: ContextReceipt = {
  receipt_id: "rcpt_1",
  run_id: "run_1",
  step: 3,
  query: "refund policy premium",
  strategy: "ranked",
  budget_tokens: 900,
  used_tokens: 120,
  included: [item({ item_id: "task", kind: "task", content: "the task" }), item({})],
  excluded: [
    item({
      item_id: "mem_2",
      content: "Premium customers within 30 days.",
      scope: "agent:billing",
      included: false,
      reason: "scope_mismatch",
      detail: "scope 'agent:billing' not in ['project']",
    }),
  ],
  created_at: new Date().toISOString(),
};

describe("ReceiptPanel", () => {
  it("separates included and excluded items and explains exclusions", () => {
    render(
      <MemoryRouter>
        <ReceiptPanel receipt={receipt} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Included \(1\)/)).toBeInTheDocument(); // the pinned task is not listed
    const excluded = screen.getAllByTestId("receipt-excluded");
    expect(excluded).toHaveLength(1);
    expect(within(excluded[0]).getByText("scope_mismatch")).toBeInTheDocument();
    expect(within(excluded[0]).getByText(/not in \['project'\]/)).toBeInTheDocument();
    expect(screen.getByText("120 / 900 tokens")).toBeInTheDocument();
  });
});

const cmp: Comparison = {
  a: { id: "run_a", status: "succeeded", kind: "live", label: null, steps: 3, tool_calls: 2, tokens: 900, duration_ms: 40, answer: "DENIED: outside 14-day window", error: null, model: "scripted:refund-support" },
  b: { id: "run_b", status: "succeeded", kind: "rerun", label: null, steps: 4, tool_calls: 3, tokens: 1300, duration_ms: 55, answer: "APPROVED: refunded $79.00", error: null, model: "scripted:refund-support" },
  steps: [
    {
      step: 1,
      a: { action: { type: "tool_call", tool: "crm.lookup", args: { customer_id: "C-1042" } }, outcome: { status: "ok" }, policy: [], context_tokens: 100 },
      b: { action: { type: "tool_call", tool: "crm.lookup", args: { customer_id: "C-1042" } }, outcome: { status: "ok" }, policy: [], context_tokens: 120 },
      same_action: true,
      context_added: ["mem_new"],
      context_removed: ["mem_old"],
    },
    {
      step: 3,
      a: { action: { type: "final_answer", answer: "DENIED" }, outcome: { status: "final" }, policy: [], context_tokens: 100 },
      b: { action: { type: "tool_call", tool: "refund.issue", args: { amount: 79 } }, outcome: { status: "ok" }, policy: [], context_tokens: 120 },
      same_action: false,
      context_added: [],
      context_removed: [],
    },
  ],
  divergence_step: 1,
  identical: false,
  memories: {
    mem_new: { content: "Premium customers within 30 days.", scope: "project", status: "active", subject_key: "refund_policy" },
    mem_old: { content: "Refund window 14 days.", scope: "project", status: "superseded", subject_key: "refund_policy" },
  },
  delta: { status_changed: false, steps: 1, tool_calls: 1, tokens: 400 },
};

describe("DiffView", () => {
  it("shows both outcomes, the divergence step and context deltas", () => {
    render(
      <MemoryRouter>
        <DiffView cmp={cmp} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("answer-A")).toHaveTextContent("DENIED");
    expect(screen.getByTestId("answer-B")).toHaveTextContent("APPROVED");
    expect(screen.getByTestId("divergence")).toHaveTextContent("diverged at step 1");
    expect(screen.getByTestId("context-added")).toHaveTextContent("Premium customers within 30 days.");
    expect(screen.getByTestId("diff-step-3")).toHaveTextContent("refund.issue");
  });
});

describe("helpers", () => {
  it("formats status badges, ids and percentages", () => {
    render(<StatusBadge status="waiting_approval" />);
    expect(screen.getByTestId("status-waiting_approval")).toHaveTextContent("awaiting approval");
    expect(shortId("run_01abcdefghijklmnop")).toBe("run…klmnop");
    expect(fmtPct(0.857)).toBe("86%");
    expect(fmtPct(null)).toBe("–");
  });

  it("describes trace nodes for the execution graph", () => {
    const step: TraceStep = {
      step: 2, span_id: "s", status: "blocked", started_at: null, ended_at: null,
      action: { type: "tool_call", tool: "refund.issue", args: { amount: 4999 } },
      outcome: { status: "blocked" }, nodes: [],
    };
    expect(stepTitle(step)).toBe("refund.issue");
    const d = describeNode({
      kind: "policy", span_id: "x", seq: 9,
      event: { id: "e", run_id: "r", seq: 9, type: "policy.decision", step: 2, span_id: "x", parent_span_id: null, ts: "", duration_ms: null,
        payload: { effect: "deny", tool: "refund.issue", rule_name: "block-large-refunds" } },
    });
    expect(d.title).toBe("Policy: deny");
    expect(d.tone).toBe("bad");
    expect(d.subtitle).toContain("block-large-refunds");
  });
});
