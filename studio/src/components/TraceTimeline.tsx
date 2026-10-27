import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ChevronRight,
  CircleDot,
  Cpu,
  Flag,
  Gauge,
  GitBranch,
  Layers,
  PauseCircle,
  ShieldAlert,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import type { ContextReceipt, Run, TraceNode, TraceStep } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Json, StatusDot } from "@/components/common";
import { ReceiptPanel } from "@/components/ReceiptPanel";
import { cn, durationMs, fmtMs, fmtNum, parseTs } from "@/lib/utils";

/** Identifies one row of the timeline: a step, or one span inside it. */
export type SpanRef = { step: number; index?: number };

type Row = {
  key: string;
  ref: SpanRef;
  depth: 0 | 1;
  icon: React.ElementType;
  label: React.ReactNode;
  detail: React.ReactNode;
  status: string;
  start: number | null; // ms from run start
  end: number | null;
};

const ICON: Record<string, React.ElementType> = {
  context: Layers,
  model: Cpu,
  model_error: AlertTriangle,
  policy: ShieldCheck,
  tool: Wrench,
  approval: PauseCircle,
  approval_resolved: PauseCircle,
  guard: ShieldAlert,
  budget: Gauge,
  divergence: GitBranch,
};

function spanStatus(n: TraceNode): string {
  const p: any = n.event?.payload ?? {};
  switch (n.kind) {
    case "tool":
      return n.status ?? (p.kind === "invalid_args" ? "invalid_args" : "error");
    case "policy":
      return p.effect === "allow" ? "ok" : p.effect;
    case "model_error":
      return p.will_retry ? "warn" : "error";
    case "approval":
      return "waiting_approval";
    case "approval_resolved":
      return p.status === "approved" ? "ok" : "rejected";
    case "guard":
    case "budget":
    case "divergence":
      return "error";
    default:
      return "ok";
  }
}

function spanLabel(n: TraceNode): { label: React.ReactNode; detail: React.ReactNode } {
  const p: any = n.event?.payload ?? {};
  switch (n.kind) {
    case "context": {
      const inc = (p.included ?? []).filter((i: any) => i.kind !== "task").length;
      const exc = (p.excluded ?? []).length;
      return { label: "context assembled", detail: `${inc} included · ${exc} excluded · ${p.used_tokens}/${p.budget_tokens} tok` };
    }
    case "model":
      return {
        label: <span className="font-mono">{p.model}</span>,
        detail: `${fmtNum(p.tokens_in)} → ${fmtNum(p.tokens_out)} tok${p.attempt > 1 ? ` · attempt ${p.attempt}` : ""}${p.stop_reason ? ` · ${p.stop_reason}` : ""}`,
      };
    case "model_error":
      return { label: "model output rejected", detail: `${p.error ?? ""}${p.will_retry ? " · retrying" : ""}` };
    case "policy":
      return {
        label: <>policy <span className="font-mono">{p.tool}</span></>,
        detail: `${p.effect.replace("_", " ")} · ${p.rule_name ?? p.reason ?? ""}`,
      };
    case "tool":
      return {
        label: <span className="font-mono">{n.tool ?? p.tool}</span>,
        detail:
          (n.status === "ok" ? JSON.stringify(n.args ?? {}) : (n.error ?? p.error ?? n.status ?? "")) +
          (n.retries?.length ? ` · ${n.retries.length} retr${n.retries.length === 1 ? "y" : "ies"}` : ""),
      };
    case "approval":
      return { label: "approval requested", detail: p.reason ?? "" };
    case "approval_resolved":
      return { label: `approval ${p.status}`, detail: p.resolver ? `by ${p.resolver}${p.note ? ` · ${p.note}` : ""}` : "" };
    case "guard":
      return { label: "guard triggered", detail: `${p.guard ?? ""} ${p.tool ?? ""}` };
    case "budget":
      return { label: "budget exceeded", detail: `${p.budget ?? ""} limit ${p.limit ?? ""}` };
    case "divergence":
      return { label: "replay diverged", detail: p.reason ?? "" };
    default:
      return { label: n.type ?? n.kind, detail: "" };
  }
}

export function stepLabel(s: TraceStep): string {
  if (!s.action) return "in progress…";
  if (s.action.type === "final_answer") return "final answer";
  return s.action.tool ?? "tool call";
}

/** Span detail, shown when a row is expanded: the data a developer needs to judge that span. */
function SpanDetail({ node }: { node: TraceNode }) {
  const p: any = node.event?.payload ?? {};
  switch (node.kind) {
    case "context":
      return <ReceiptPanel receipt={p as ContextReceipt} />;
    case "model":
      return (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
            <span>model <span className="font-mono text-foreground">{p.model}</span></span>
            {p.model_reported && <span>backend reported <span className="font-mono text-foreground">{p.model_reported}</span></span>}
            <span>{fmtNum(p.tokens_in)} in · {fmtNum(p.tokens_out)} out{p.usage_reported === false ? " (estimated)" : ""}</span>
            <span>latency {fmtMs(p.latency_ms)}</span>
            {p.model_digest && <span className="font-mono">{String(p.model_digest).slice(0, 19)}</span>}
          </div>
          <div>
            <div className="mb-1 text-[11px] font-medium text-muted-foreground">Response</div>
            <Json value={p.response} className="max-h-56" />
          </div>
          <details className="group">
            <summary className="cursor-pointer text-[11px] font-medium text-muted-foreground hover:text-foreground">
              Prompt · {(p.messages ?? []).length} messages
            </summary>
            <div className="mt-1.5 space-y-1.5">
              {(p.messages ?? []).map((m: { role: string; content: string }, i: number) => (
                <div key={i}>
                  <Badge variant="outline" className="mb-0.5">{m.role}</Badge>
                  <Json value={m.content} className="max-h-48" />
                </div>
              ))}
            </div>
          </details>
        </div>
      );
    case "tool":
      return (
        <div className="grid gap-2 md:grid-cols-2">
          <div>
            <div className="mb-1 text-[11px] font-medium text-muted-foreground">Arguments</div>
            <Json value={node.args ?? p.args} className="max-h-48" />
          </div>
          <div>
            <div className={cn("mb-1 text-[11px] font-medium", node.status === "ok" ? "text-muted-foreground" : "text-destructive")}>
              {node.status === "ok" ? "Result" : "Error"}
            </div>
            <Json value={node.status === "ok" ? node.result : (node.error ?? p.error)} className="max-h-48" />
          </div>
          {node.retries && node.retries.length > 0 && (
            <div className="md:col-span-2">
              <div className="mb-1 text-[11px] font-medium text-muted-foreground">Retries</div>
              <Json value={node.retries} className="max-h-40" />
            </div>
          )}
        </div>
      );
    case "policy":
      return (
        <div className="space-y-1.5 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={p.effect === "allow" ? "success" : p.effect === "deny" ? "destructive" : "warning"}>{p.effect}</Badge>
            <span className="font-mono">{p.rule_name ?? "default"}</span>
            <span className="text-muted-foreground">{p.reason}</span>
          </div>
          <Json value={p.args} className="max-h-40" />
        </div>
      );
    default:
      return <Json value={p} className="max-h-56" />;
  }
}

function StepDetail({ step }: { step: TraceStep }) {
  return (
    <div className="space-y-2 text-xs">
      {step.action?.thought && <p className="text-muted-foreground italic">“{step.action.thought}”</p>}
      {step.action?.type === "final_answer" ? (
        <p className="rounded-md border bg-background/60 p-2">{step.action.answer}</p>
      ) : (
        <div className="grid gap-2 md:grid-cols-2">
          <div>
            <div className="mb-1 text-[11px] font-medium text-muted-foreground">Action</div>
            <Json value={step.action} className="max-h-40" />
          </div>
          <div>
            <div className="mb-1 text-[11px] font-medium text-muted-foreground">Outcome</div>
            <Json value={step.outcome} className="max-h-40" />
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * The execution as a connected waterfall: steps in order, each with its spans (context, model call, policy decision,
 * tool call, approvals). Rows show the outcome; expanding a row shows its data.
 */
export function TraceTimeline({
  run,
  steps,
  open,
  onToggle,
}: {
  run: Run;
  steps: TraceStep[];
  open: Set<string>;
  onToggle: (key: string) => void;
}) {
  // Long runs start collapsed to their steps; short ones show every span.
  const [collapsed, setCollapsed] = useState<Set<number>>(() => new Set(steps.length > 6 ? steps.map((s) => s.step) : []));
  const { rows, total } = useMemo(() => {
    const t0 = parseTs(run.started_at ?? run.created_at).getTime();
    const rel = (iso: string | null | undefined) => (iso ? parseTs(iso).getTime() - t0 : null);
    let maxEnd = rel(run.ended_at) ?? 0;
    const rows: Row[] = [];
    for (const s of steps) {
      const sStart = rel(s.started_at);
      const sEnd = rel(s.ended_at);
      maxEnd = Math.max(maxEnd, sEnd ?? sStart ?? 0);
      const final = s.action?.type === "final_answer";
      rows.push({
        key: `s${s.step}`,
        ref: { step: s.step },
        depth: 0,
        icon: final ? Flag : CircleDot,
        label: (
          <>
            <span className="text-muted-foreground">step {s.step}</span>{" "}
            <span className={cn("font-medium", !final && "font-mono")}>{stepLabel(s)}</span>
          </>
        ),
        detail: final ? s.action?.answer : s.outcome?.error ?? (s.action?.args ? JSON.stringify(s.action.args) : ""),
        status: s.status === "done" ? "ok" : s.status,
        start: sStart,
        end: sEnd,
      });
      s.nodes.forEach((n, i) => {
        const endIso = n.kind === "tool" ? (n.events?.at(-1)?.ts ?? null) : (n.event?.ts ?? null);
        const end = rel(endIso);
        const dur = n.kind === "tool" ? n.duration_ms : n.event?.duration_ms;
        const { label, detail } = spanLabel(n);
        rows.push({
          key: `s${s.step}-${i}`,
          ref: { step: s.step, index: i },
          depth: 1,
          icon: ICON[n.kind] ?? CircleDot,
          label,
          detail,
          status: spanStatus(n),
          start: end !== null && dur ? end - dur : end,
          end,
        });
        if (end !== null) maxEnd = Math.max(maxEnd, end);
      });
    }
    return { rows, total: Math.max(1, maxEnd) };
  }, [run, steps]);

  const nodeFor = (ref: SpanRef) => steps.find((s) => s.step === ref.step)?.nodes[ref.index ?? -1];
  const stepFor = (ref: SpanRef) => steps.find((s) => s.step === ref.step)!;

  if (steps.length === 0)
    return <div className="px-3 py-8 text-center text-xs text-muted-foreground">{run.status === "pending" ? "Waiting to start…" : "No steps recorded."}</div>;

  return (
    <div data-testid="trace-timeline" role="tree" aria-label="execution timeline">
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(80px,28%)_64px] items-center gap-3 border-b px-3 py-1.5 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
        <span>Span</span>
        <span className="flex justify-between font-mono normal-case"><span>0</span><span>{fmtMs(total)}</span></span>
        <span className="text-right">Duration</span>
      </div>
      <ul>
        {rows.map((r) => {
          if (r.depth === 1 && collapsed.has(r.ref.step)) return null;
          const isOpen = open.has(r.key);
          const left = r.start !== null ? (Math.max(0, r.start) / total) * 100 : null;
          const width = r.start !== null && r.end !== null ? Math.max(0.6, ((r.end - r.start) / total) * 100) : 0.6;
          const dur = r.start !== null && r.end !== null ? r.end - r.start : null;
          const bad = ["error", "failed", "deny", "blocked", "rejected", "invalid_args"].includes(r.status);
          const warn = ["warn", "waiting_approval", "require_approval", "pending_approval"].includes(r.status);
          return (
            <li key={r.key} role="treeitem" aria-expanded={isOpen} data-testid={`span-${r.key}`}>
              <button
                type="button"
                onClick={() => onToggle(r.key)}
                className={cn(
                  "grid w-full grid-cols-[minmax(0,1fr)_minmax(80px,28%)_64px] items-center gap-3 border-b px-3 py-1 text-left hover:bg-accent/40",
                  r.depth === 0 && "bg-muted/30",
                  isOpen && "bg-accent/50",
                )}
              >
                <span className="flex min-w-0 items-center gap-1.5" style={{ paddingLeft: r.depth * 18 }}>
                  {r.depth === 0 ? (
                    <span
                      role="button"
                      tabIndex={-1}
                      aria-label={collapsed.has(r.ref.step) ? "expand step" : "collapse step"}
                      onClick={(e) => {
                        e.stopPropagation();
                        setCollapsed((c) => {
                          const n = new Set(c);
                          if (n.has(r.ref.step)) n.delete(r.ref.step);
                          else n.add(r.ref.step);
                          return n;
                        });
                      }}
                      className="grid size-4 place-items-center rounded-sm text-muted-foreground hover:bg-accent"
                    >
                      <ChevronRight className={cn("size-3.5 transition-transform", !collapsed.has(r.ref.step) && "rotate-90")} />
                    </span>
                  ) : (
                    <span className="h-4 w-4 border-b border-l border-border/80" aria-hidden />
                  )}
                  <StatusDot status={r.status} />
                  <r.icon className={cn("size-3.5 shrink-0", bad ? "text-destructive" : warn ? "text-warning" : "text-muted-foreground")} />
                  <span className="shrink-0 text-[13px]">{r.label}</span>
                  <span className={cn("min-w-0 truncate text-xs", bad ? "text-destructive" : "text-muted-foreground")}>{r.detail}</span>
                </span>
                <span className="relative h-2.5 rounded-sm bg-muted/40">
                  {left !== null && (
                    <span
                      className={cn(
                        "absolute top-0 h-2.5 rounded-sm",
                        bad ? "bg-destructive/80" : warn ? "bg-warning/80" : r.depth === 0 ? "bg-primary/40" : "bg-primary/80",
                      )}
                      style={{ left: `${Math.min(left, 99.4)}%`, width: `${width}%` }}
                    />
                  )}
                </span>
                <span className="text-right font-mono text-[11px] text-muted-foreground tabular-nums">{dur !== null ? fmtMs(dur) : ""}</span>
              </button>
              {isOpen && (
                <div className="border-b bg-background/40 px-3 py-2.5" style={{ paddingLeft: 12 + r.depth * 18 + 22 }}>
                  {r.ref.index === undefined ? <StepDetail step={stepFor(r.ref)} /> : <SpanDetail node={nodeFor(r.ref)!} />}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <div className="flex justify-between px-3 py-1.5 text-[11px] text-muted-foreground">
        <span>{steps.length} steps · {rows.length - steps.length} spans</span>
        <span>run {fmtMs(durationMs(run.started_at, run.ended_at))}</span>
      </div>
    </div>
  );
}
