import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, Cpu, Flag, LayoutDashboard, PauseCircle, Play, ShieldAlert, Sparkles, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { ExperimentState, Overview as OverviewData, Run } from "@/lib/types";
import { EmptyState, ErrorNote, Metric, PageHeader, Panel, StatusDot } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, durationMs, fmtMs, fmtNum, fmtPct, timeAgo } from "@/lib/utils";

const EFFECT_VARIANT = { deny: "destructive", require_approval: "warning" } as const;

/** The signature experiment: prominent before it is done, a progress strip after. */
function ExperimentEntry({ exp, measured, empty }: { exp?: ExperimentState; measured: boolean; empty: boolean }) {
  const r = exp?.runs ?? {};
  const done = (k: string) => !!r[k] && !["pending", "running"].includes(r[k]!.status);
  const steps = [
    { label: "Run", ok: done("original") },
    { label: "Diagnose", ok: done("original") && !!exp?.fixed },
    { label: "Fix", ok: !!exp?.fixed },
    { label: "Compare", ok: done("rerun") },
    { label: "Stress-test", ok: done("injection") && done("faults") },
    { label: "Measure", ok: measured && done("original") },
  ];
  const next = steps.findIndex((s) => !s.ok);
  const finished = next === -1;
  return (
    <Link
      to="/experiment"
      data-testid="experiment-banner"
      className={cn(
        "group flex flex-col gap-3 rounded-lg border border-l-2 border-l-primary bg-card px-4 py-3 transition-colors hover:bg-accent/40 md:flex-row md:items-center",
        empty && "bg-gradient-to-r from-primary/10 to-transparent py-5",
      )}
    >
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <Sparkles className="mt-0.5 size-4 shrink-0 text-primary" />
        <div className="min-w-0">
          <div className="text-sm font-semibold">Signature experiment: watch an agent fail, find out why, fix it, prove it</div>
          <p className="text-xs text-muted-foreground">
            A support agent wrongly denies a refund. Trace the cause, preview a memory fix, stress-test it with a prompt injection and
            an outage, and measure the improvement. Sandboxed, about five minutes.
          </p>
        </div>
      </div>
      <ol className="flex flex-wrap items-center gap-1 text-[11px]" aria-label="experiment progress">
        {steps.map((s, i) => (
          <li
            key={s.label}
            className={cn(
              "flex items-center gap-1 rounded-sm border px-1.5 py-0.5",
              s.ok ? "border-success/30 text-success" : i === next ? "border-primary/50 text-foreground" : "text-muted-foreground",
            )}
          >
            {s.ok ? <Check className="size-3" /> : <span className="tabular-nums">{i + 1}</span>}
            {s.label}
          </li>
        ))}
      </ol>
      <span className="inline-flex shrink-0 items-center gap-1.5 text-xs font-medium text-primary" data-testid="start-experiment">
        {finished ? "Review" : next <= 0 ? <><Play className="size-3.5" /> Start</> : "Continue"}
        <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
      </span>
    </Link>
  );
}

function StatusStrip({ d }: { d: OverviewData }) {
  const running = (d.runs.by_status.running ?? 0) + (d.runs.by_status.pending ?? 0);
  const failed = (d.runs.by_status.failed ?? 0) + (d.runs.by_status.cancelled ?? 0);
  const blocks = (d.policy.decisions.deny ?? 0) + (d.policy.decisions.require_approval ?? 0);
  const items = [
    { to: "/runs", m: <Metric label={`Runs · ${d.window_days}d`} value={fmtNum(d.runs.total)} hint={`${fmtNum(d.runs.tool_calls)} tool calls`} /> },
    {
      to: "/runs",
      m: (
        <Metric
          label="Completed successfully"
          value={fmtPct(d.runs.success_rate)}
          tone={d.runs.success_rate === null ? "muted" : d.runs.success_rate >= 0.95 ? "good" : d.runs.success_rate >= 0.8 ? "warn" : "bad"}
          hint={`${failed} failed or cancelled`}
        />
      ),
    },
    { to: "/runs", m: <Metric label="Running now" value={running} tone={running ? undefined : "muted"} hint="live and pending" /> },
    {
      to: "/control",
      m: <Metric label="Awaiting approval" value={d.policy.pending_approvals} tone={d.policy.pending_approvals ? "warn" : "muted"} hint="human decisions" />,
    },
    { to: "/control", m: <Metric label="Policy interventions" value={blocks} hint={`${d.policy.decisions.deny ?? 0} denied`} /> },
    {
      to: "/runs",
      m: <Metric label="Run latency p50 / p95" value={<span className="font-mono text-base">{fmtMs(d.runs.latency_p50_ms)}</span>} hint={`p95 ${fmtMs(d.runs.latency_p95_ms)}`} />,
    },
    { to: "/runs", m: <Metric label="Tokens" value={fmtNum(d.runs.tokens)} hint={`${d.models.length} model${d.models.length === 1 ? "" : "s"}`} /> },
  ];
  return (
    <div className="grid grid-cols-2 divide-x divide-y rounded-lg border bg-card sm:grid-cols-4 xl:grid-cols-7 xl:divide-y-0" data-testid="status-strip">
      {items.map((it, i) => (
        <Link key={i} to={it.to} className="transition-colors hover:bg-accent/40">
          {it.m}
        </Link>
      ))}
    </div>
  );
}

type Attention = { key: string; icon: React.ElementType; tone: string; title: React.ReactNode; detail: React.ReactNode; to: string; when: string };

function NeedsAttention({ d }: { d: OverviewData }) {
  const approvals = useQuery({ queryKey: ["approvals", "pending"], queryFn: () => api.approvals("pending") });
  const blocked = useQuery({ queryKey: ["blocked"], queryFn: api.blocked });
  const items: Attention[] = [
    ...(approvals.data ?? []).map((a) => ({
      key: a.id, icon: PauseCircle, tone: "text-warning", to: "/control",
      title: <>Approval needed: <span className="font-mono">{a.tool}</span></>,
      detail: a.reason, when: a.requested_at,
    })),
    ...d.recent_failures.map((f) => {
      const flagged = f.feedback?.verdict === "incorrect";
      return {
        key: f.id, icon: flagged ? Flag : XCircle, tone: flagged ? "text-warning" : "text-destructive", to: `/runs/${f.id}`,
        title: flagged ? <>Flagged incorrect: <span className="text-muted-foreground">{f.agent}</span></> : <>Run {f.status}: {f.agent}</>,
        detail: flagged ? <>“{f.feedback?.note}” · answered: {f.answer}</> : f.error ?? f.answer ?? f.task,
        when: f.created_at,
      };
    }),
    ...(blocked.data ?? []).filter((b) => b.effect === "deny" || b.guard).slice(0, 4).map((b) => ({
      key: b.event_id, icon: ShieldAlert, tone: "text-destructive", to: `/runs/${b.run_id}`,
      title: <>Blocked: <span className="font-mono">{b.tool ?? b.guard}</span></>,
      detail: b.reason ?? b.rule_name, when: b.ts,
    })),
  ].sort((a, b) => b.when.localeCompare(a.when));

  return (
    <Panel
      title="Needs attention"
      description="Approvals, failures, answers a human flagged and actions policies stopped"
      actions={items.length ? <Badge variant="outline">{items.length}</Badge> : undefined}
      data-testid="needs-attention"
    >
      {items.length === 0 ? (
        <div className="flex items-center gap-2 px-3 py-6 text-xs text-muted-foreground">
          <Check className="size-4 text-success" /> Nothing needs attention.
        </div>
      ) : (
        <ul className="divide-y">
          {items.slice(0, 8).map((it) => (
            <li key={it.key}>
              <Link to={it.to} className="flex items-start gap-2.5 px-3 py-2 hover:bg-accent/40">
                <it.icon className={cn("mt-0.5 size-3.5 shrink-0", it.tone)} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px]">{it.title}</div>
                  <div className="line-clamp-2 text-xs text-muted-foreground">{it.detail}</div>
                </div>
                <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums">{timeAgo(it.when)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function RecentRuns() {
  const runs = useQuery({ queryKey: ["runs", "recent"], queryFn: () => api.runs({ limit: 10 }), refetchInterval: 5000 });
  return (
    <Panel
      title="Recent runs"
      actions={
        <Button variant="ghost" size="sm" asChild>
          <Link to="/runs">All runs <ArrowRight /></Link>
        </Button>
      }
    >
      {!runs.data ? (
        <Skeleton className="m-3 h-40" />
      ) : runs.data.length === 0 ? (
        <EmptyState title="No runs yet">Start the signature experiment above, or run your own agent with the SDK.</EmptyState>
      ) : (
        <ul className="divide-y">
          {runs.data.map((r: Run) => (
            <li key={r.id}>
              <Link to={`/runs/${r.id}`} className="flex items-center gap-2.5 px-3 py-1.5 hover:bg-accent/40">
                <StatusDot status={r.status} />
                <span className="w-24 shrink-0 truncate text-xs text-muted-foreground">{r.agent_name}</span>
                <span className="min-w-0 flex-1 truncate text-[13px]">{r.result?.answer ?? r.error ?? r.task}</span>
                {r.kind !== "live" && <Badge variant="outline">{r.kind}</Badge>}
                <span className="w-14 shrink-0 text-right font-mono text-[11px] text-muted-foreground">
                  {fmtMs(durationMs(r.started_at, r.ended_at))}
                </span>
                <span className="w-14 shrink-0 text-right text-[11px] text-muted-foreground">{timeAgo(r.created_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/** Failed vs total runs per day: one small, quiet chart. */
function FailureTrend({ d }: { d: OverviewData }) {
  const max = Math.max(1, ...d.series.map((s) => s.succeeded + s.failed + s.other));
  const failed = d.series.reduce((n, s) => n + s.failed, 0);
  return (
    <Panel title="Failure trend" description={`${failed} failed of ${d.runs.total} runs, last ${d.window_days} days`}>
      <div className="flex h-28 items-end gap-1 px-3 pt-3" role="img" aria-label="runs per day, failures highlighted">
        {d.series.map((s) => {
          const total = s.succeeded + s.failed + s.other;
          return (
            <div key={s.date} className="flex h-full min-w-0 flex-1 flex-col justify-end" title={`${s.date}: ${total} runs, ${s.failed} failed`}>
              <div className="flex flex-col justify-end overflow-hidden rounded-[2px]" style={{ height: `${(total / max) * 100}%` }}>
                <div className="bg-destructive/80" style={{ height: total ? `${(s.failed / total) * 100}%` : 0 }} />
                <div className="flex-1 bg-muted-foreground/30" />
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex justify-between px-3 pt-1 pb-2.5 font-mono text-[10px] text-muted-foreground">
        <span>{d.series[0]?.date.slice(5)}</span>
        <span className="flex items-center gap-3 font-sans">
          <span className="flex items-center gap-1"><span className="size-2 rounded-[2px] bg-muted-foreground/30" /> runs</span>
          <span className="flex items-center gap-1"><span className="size-2 rounded-[2px] bg-destructive/80" /> failed</span>
        </span>
        <span>{d.series.at(-1)?.date.slice(5)}</span>
      </div>
    </Panel>
  );
}

function PolicyInterventions({ d }: { d: OverviewData }) {
  return (
    <Panel title="Policy interventions" description="Tool calls that rules stopped or paused, enforced outside the model">
      {d.policy.interventions.length === 0 ? (
        <div className="px-3 py-6 text-xs text-muted-foreground">No tool call has been denied or paused yet.</div>
      ) : (
        <ul className="divide-y">
          {d.policy.interventions.slice(0, 6).map((p) => (
            <li key={`${p.rule}-${p.effect}`}>
              <Link to="/control" className="flex items-center gap-2 px-3 py-1.5 hover:bg-accent/40">
                <Badge variant={EFFECT_VARIANT[p.effect as keyof typeof EFFECT_VARIANT] ?? "outline"}>{p.effect.replace("_", " ")}</Badge>
                <span className="min-w-0 flex-1 truncate font-mono text-xs">{p.rule}</span>
                <span className="truncate text-[11px] text-muted-foreground">{Object.keys(p.tools).join(", ")}</span>
                <span className="w-6 text-right text-xs font-semibold tabular-nums">{p.count}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function ModelUsage({ d }: { d: OverviewData }) {
  return (
    <Panel title="Model usage" icon={Cpu} description="Calls, tokens and latency per model, as reported by the backends">
      {d.models.length === 0 ? (
        <div className="px-3 py-6 text-xs text-muted-foreground">No model calls yet.</div>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b text-[10px] tracking-wide text-muted-foreground uppercase">
              <th className="px-3 py-1.5 text-left font-medium">Model</th>
              <th className="px-2 py-1.5 text-right font-medium">Calls</th>
              <th className="px-2 py-1.5 text-right font-medium">Tokens</th>
              <th className="px-3 py-1.5 text-right font-medium">p50</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {d.models.slice(0, 6).map((m) => (
              <tr key={m.model}>
                <td className="max-w-0 px-3 py-1.5">
                  <div className="truncate font-mono" title={m.reported.join(", ") || m.model}>{m.model}</div>
                  {m.errors > 0 && <div className="text-[11px] text-destructive">{m.errors} failed calls</div>}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">{fmtNum(m.calls)}</td>
                <td className="px-2 py-1.5 text-right tabular-nums">{fmtNum(m.tokens_in + m.tokens_out)}</td>
                <td className="px-3 py-1.5 text-right font-mono">{fmtMs(m.latency_p50_ms)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function Evaluations({ d }: { d: OverviewData }) {
  return (
    <Panel
      title="Latest evaluations"
      description="Task success per variant of each reproducible benchmark"
      actions={
        <Button variant="ghost" size="sm" asChild>
          <Link to="/replay">Open <ArrowRight /></Link>
        </Button>
      }
    >
      {d.evals.length === 0 ? (
        <div className="px-3 py-6 text-xs text-muted-foreground">No benchmark has been run yet.</div>
      ) : (
        <ul className="space-y-2.5 px-3 py-2.5">
          {d.evals.slice(0, 6).map((e) => {
            const v = e.metrics.success_rate;
            return (
              <li key={e.id}>
                <div className="flex items-baseline justify-between text-xs">
                  <span className="truncate"><span className="text-muted-foreground">{e.suite}/</span>{e.variant}</span>
                  <span className={cn("font-semibold tabular-nums", v >= 0.95 ? "text-success" : v >= 0.7 ? "text-warning" : "text-destructive")}>
                    {fmtPct(v)}
                  </span>
                </div>
                <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
                  <div className={cn("h-full", v >= 0.95 ? "bg-success" : v >= 0.7 ? "bg-warning" : "bg-destructive")} style={{ width: `${v * 100}%` }} />
                </div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">
                  unsafe actions executed {e.metrics.unsafe_actions_executed} · evidence recall {fmtPct(e.metrics.evidence_recall)} · {timeAgo(e.created_at)}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

export default function Overview() {
  const q = useQuery({ queryKey: ["overview"], queryFn: api.overview, refetchInterval: 5000 });
  const exp = useQuery({ queryKey: ["experiment"], queryFn: api.experiment });
  const d = q.data;
  const measured =
    !!exp.data?.seeded_at && (d?.evals ?? []).some((e) => e.suite === "refund" && e.created_at >= exp.data!.seeded_at!);

  return (
    <div className="space-y-3">
      <PageHeader title="Overview" icon={LayoutDashboard} description="What happened, what needs a decision, and how the system is performing." />
      <ErrorNote error={q.error} />
      <ExperimentEntry exp={exp.data} measured={measured} empty={!!d && d.runs.total === 0} />
      {!d ? (
        <Skeleton className="h-20" />
      ) : (
        <>
          <StatusStrip d={d} />
          <div className="grid gap-3 xl:grid-cols-2">
            <NeedsAttention d={d} />
            <RecentRuns />
          </div>
          <div className="grid gap-3 xl:grid-cols-2">
            <ModelUsage d={d} />
            <FailureTrend d={d} />
            <PolicyInterventions d={d} />
            <Evaluations d={d} />
          </div>
          <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            Project memory: {fmtNum(d.memory.active ?? 0)} active memories ·
            <Link to="/memory" className="underline-offset-2 hover:underline">explore</Link>
          </p>
        </>
      )}
    </div>
  );
}
