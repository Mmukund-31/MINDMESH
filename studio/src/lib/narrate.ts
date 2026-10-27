import type { MMEvent } from "./types";

/** How a run's decisions were produced. Shown on every run so demo, live and replay results are never confused. */
export type RunMode = "demo" | "live" | "replay";

export function runMode(r: { kind: string; model?: string | null }): RunMode {
  if (r.kind === "replay") return "replay";
  if (!r.model || r.model.startsWith("scripted:")) return "demo";
  return "live";
}

/** "scripted:refund-support?think_ms=650" -> "refund-support"; "ollama:qwen3:4b" -> "qwen3:4b" */
export function modelName(model: string | null | undefined): string {
  if (!model) return "?";
  const [, ...rest] = model.split(":");
  return (rest.join(":") || model).split("?")[0];
}

export const MODE_TEXT: Record<RunMode, { label: string; help: string }> = {
  demo: {
    label: "Demo",
    help: "Decisions come from a deterministic scripted stand-in for an LLM that only sees what MindMesh puts in its context. Results are reproducible. Tools are simulated.",
  },
  live: {
    label: "Live model",
    help: "A real language model made these decisions. Results can vary between runs. Tools are still the simulated refund system.",
  },
  replay: {
    label: "Replay",
    help: "Re-executed from the original run's recorded model and tool outputs. No model was called and no tool ran, so there were no side effects.",
  },
};

export type Tone = "info" | "good" | "bad" | "warn" | "muted";

export interface Narration {
  tone: Tone;
  text: string;
  detail?: string;
}

function brief(v: unknown, max = 90): string {
  const s = typeof v === "string" ? v : JSON.stringify(v ?? "");
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function call(tool: unknown, args: unknown): string {
  const a = Object.entries((args as Record<string, unknown>) ?? {})
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(", ");
  return `${tool}(${a})`;
}

const REASONS: Record<string, string> = {
  scope_mismatch: "not visible to this agent",
  superseded: "replaced by a newer version",
  conflict_lost: "lost a conflict",
  budget: "did not fit the budget",
  retracted: "retracted",
  expired: "expired",
};

/** A one-line, plain-language description of an event, or null for events not worth narrating. */
export function narrate(e: MMEvent): Narration | null {
  const p = e.payload ?? {};
  switch (e.type) {
    case "run.created":
      return { tone: "muted", text: `Run created for agent “${p.agent ?? "?"}”` };
    case "run.state_changed":
      switch (p.to) {
        case "running":
          return p.from === "pending" ? { tone: "muted", text: "Run started" } : { tone: "muted", text: "Run continues" };
        case "succeeded":
          return { tone: "good", text: "Run finished" };
        case "failed":
          return { tone: "bad", text: `Run failed${p.reason ? `: ${p.reason}` : ""}` };
        case "waiting_approval":
          return { tone: "warn", text: "Paused until a human approves" };
        case "cancelled":
          return { tone: "muted", text: "Run cancelled" };
      }
      return null;
    case "run.resumed":
      return { tone: "info", text: `Resumed from checkpoint at step ${p.from_step}` };
    case "step.started":
      return { tone: "muted", text: `Step ${e.step}` };
    case "context.assembled": {
      const inc = (p.included ?? []).filter((i: { kind: string }) => i.kind !== "task");
      const exc = p.excluded ?? [];
      const notable = [
        ...new Set<string>(
          exc
            .filter((i: { reason: string }) => i.reason && i.reason !== "low_relevance")
            .map((i: { subject_key: string | null; reason: string }) => `${i.subject_key ?? "memory"}: ${REASONS[i.reason] ?? i.reason}`),
        ),
      ];
      return {
        tone: "info",
        text: `Context assembled: ${inc.length} included, ${exc.length} excluded (${p.used_tokens}/${p.budget_tokens} tokens)`,
        detail: notable.length ? `excluded ${notable.join("; ")}` : undefined,
      };
    }
    case "model.called": {
      let action: { type?: string; tool?: string; args?: unknown; thought?: string } | null = null;
      try {
        action = JSON.parse(p.response);
      } catch {
        /* free-form model output: parsed by the runtime, not here */
      }
      const ms = p.latency_ms ? ` in ${Math.round(p.latency_ms)} ms` : "";
      if (action?.type === "tool_call")
        return { tone: "muted", text: `Model chose ${call(action.tool, action.args)}${ms}`, detail: action.thought };
      if (action?.type === "final_answer") return { tone: "muted", text: `Model chose to answer${ms}`, detail: action.thought };
      return { tone: "muted", text: `Model ${p.model ?? ""} responded${ms}` };
    }
    case "model.failed":
      return { tone: "warn", text: `Model call failed: ${brief(p.error)}${p.will_retry ? " (retrying)" : ""}` };
    case "policy.decision":
      if (p.effect === "deny")
        return {
          tone: "bad",
          text: `Policy blocked ${call(p.tool, p.args)}`,
          detail: `${p.rule_name ? `rule ${p.rule_name}: ` : ""}${p.reason}`,
        };
      if (p.effect === "require_approval")
        return { tone: "warn", text: `Policy requires approval for ${call(p.tool, p.args)}`, detail: p.reason };
      return { tone: "muted", text: `Policy allowed ${p.tool}`, detail: p.rule_name ? `rule ${p.rule_name}` : p.reason };
    case "tool.started":
      return p.replayed ? { tone: "muted", text: `${p.tool}: using the recorded result (not executed)` } : null;
    case "tool.finished":
      return { tone: "good", text: `${p.tool} returned ${brief(p.result, 70)}` };
    case "tool.failed":
      return { tone: "bad", text: `${p.tool} failed: ${brief(p.error)}`, detail: p.injected ? "injected fault" : undefined };
    case "tool.retry":
      return {
        tone: "warn",
        text: `${p.tool} failed, retry ${p.attempt} in ${p.backoff_s}s`,
        detail: `${p.injected ? "injected fault: " : ""}${p.error}`,
      };
    case "approval.requested":
      return { tone: "warn", text: `Waiting for human approval: ${call(p.tool, p.args)}`, detail: p.reason };
    case "approval.resolved":
      return { tone: "info", text: `Approval ${p.status} by ${p.resolver ?? "reviewer"}` };
    case "guard.triggered":
      return { tone: "bad", text: `Guard ${p.guard}: ${brief(p.reason ?? "")}` };
    case "budget.exceeded":
      return { tone: "bad", text: `Budget exceeded: ${p.reason ?? p.budget}` };
    case "replay.diverged":
      return { tone: "warn", text: `Replay diverged at step ${p.step}: ${p.reason}` };
    case "step.finished":
      if (p.action?.type === "final_answer") {
        const answer = String(p.action.answer ?? "");
        // a denial can be correct: only the experiment knows the expected outcome
        return { tone: answer.startsWith("ESCALATED") ? "warn" : "info", text: `Final answer: ${answer}` };
      }
      return null;
  }
  return null;
}
