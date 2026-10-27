import type { ContextItem, ContextReceipt, Run, TraceStep } from "@/lib/types";
import { REASON_TEXT } from "@/components/ReceiptPanel";

export type Finding = {
  tone: "bad" | "warn" | "info";
  title: string;
  detail?: string;
  /** Timeline row to open: `s<step>` or `s<step>-<span index>`. */
  focus?: string;
};

// Exclusions that usually explain a wrong answer (low relevance and budget are routine).
const NOTABLE = new Set(["scope_mismatch", "conflict_lost", "superseded", "expired", "retracted"]);

/**
 * What went wrong in a run, derived only from its recorded trace: errors, failed tools, policy interventions, rejected
 * model output, guards, and memories the context engine excluded. Nothing is inferred beyond the events.
 */
export function diagnose(run: Run, steps: TraceStep[]): Finding[] {
  const out: Finding[] = [];
  if (run.status === "failed" && run.error) out.push({ tone: "bad", title: "Run failed", detail: run.error });
  if (run.status === "cancelled") out.push({ tone: "warn", title: "Run cancelled", detail: run.error ?? undefined });
  if (run.feedback?.verdict === "incorrect")
    out.push({ tone: "bad", title: `A human flagged the answer as incorrect${run.feedback.by ? ` (${run.feedback.by})` : ""}`, detail: run.feedback.note ?? undefined });

  let lastReceipt: { step: number; index: number; r: ContextReceipt } | null = null;
  for (const s of steps) {
    s.nodes.forEach((n, i) => {
      const p = (n.event?.payload ?? {}) as Record<string, unknown> & { [k: string]: any };
      const focus = `s${s.step}-${i}`;
      if (n.kind === "tool" && n.status && n.status !== "ok" && n.status !== "running")
        out.push({ tone: "bad", title: `Step ${s.step}: tool ${n.tool} failed`, detail: n.error ?? undefined, focus });
      if (n.kind === "tool" && n.retries?.length)
        out.push({ tone: "warn", title: `Step ${s.step}: ${n.tool} needed ${n.retries.length} retr${n.retries.length === 1 ? "y" : "ies"}`, focus });
      if (n.kind === "policy" && p.effect === "deny")
        out.push({ tone: "bad", title: `Step ${s.step}: policy denied ${p.tool}`, detail: `${p.rule_name ?? "rule"}: ${p.reason}`, focus });
      if (n.kind === "policy" && p.effect === "require_approval")
        out.push({ tone: "warn", title: `Step ${s.step}: ${p.tool} paused for human approval`, detail: `${p.rule_name ?? "rule"}: ${p.reason}`, focus });
      if (n.kind === "model_error")
        out.push({ tone: p.will_retry ? "warn" : "bad", title: `Step ${s.step}: model output rejected${p.will_retry ? ", retried" : ""}`, detail: String(p.error ?? ""), focus });
      if (["guard", "budget", "divergence"].includes(n.kind))
        out.push({ tone: "bad", title: `Step ${s.step}: ${n.kind === "guard" ? "guard triggered" : n.kind === "budget" ? "budget exceeded" : "replay diverged"}`, detail: String(p.reason ?? p.guard ?? p.budget ?? ""), focus });
      if (n.kind === "context") lastReceipt = { step: s.step, index: i, r: p as unknown as ContextReceipt };
    });
    if (s.outcome?.status === "invalid_args")
      out.push({ tone: "bad", title: `Step ${s.step}: invalid tool arguments`, detail: s.outcome.error, focus: `s${s.step}` });
  }

  const lr = lastReceipt as { step: number; index: number; r: ContextReceipt } | null;
  if (lr) {
    const notable = lr.r.excluded.filter((x: ContextItem) => x.reason && NOTABLE.has(x.reason));
    if (notable.length) {
      const x = notable[0];
      out.push({
        tone: out.length || run.feedback?.verdict === "incorrect" ? "bad" : "info",
        title: `Context excluded ${notable.length} memor${notable.length === 1 ? "y" : "ies"} the agent might have needed`,
        detail: `${x.subject_key ?? x.item_id} (${x.scope}): ${REASON_TEXT[x.reason!] ?? x.reason}${x.detail ? `: ${x.detail}` : ""}`,
        focus: `s${lr.step}-${lr.index}`,
      });
    }
  }
  return out;
}
