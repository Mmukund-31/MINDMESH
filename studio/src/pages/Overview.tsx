import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Activity, AlertTriangle, ArrowRight, Brain, Coins, Gauge, LayoutDashboard, Play, ShieldAlert, Sparkles, Timer } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorNote, PageHeader, Stat, StatusBadge } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RunModeBadge } from "@/components/LiveRun";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtMs, fmtNum, fmtPct, shortId, timeAgo } from "@/lib/utils";

const tooltipStyle = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
  color: "var(--popover-foreground)",
};

/** The entry point for newcomers: prominent on an empty project, a slim banner afterwards. */
function FirstRun({ empty }: { empty: boolean }) {
  if (!empty)
    return (
      <Link
        to="/experiment"
        className="flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm hover:bg-primary/10"
        data-testid="experiment-banner"
      >
        <Sparkles className="size-4 text-primary" />
        <span>New to MindMesh? The guided experiment shows an agent fail, the cause, the fix and the measured improvement.</span>
        <ArrowRight className="ml-auto size-4 text-primary" />
      </Link>
    );
  return (
    <Card className="border-primary/30 bg-gradient-to-br from-primary/10 to-transparent" data-testid="first-run">
      <CardContent className="flex flex-col gap-4 pt-6 md:flex-row md:items-center">
        <div className="grid size-12 shrink-0 place-items-center rounded-xl bg-primary/15 text-primary">
          <Sparkles className="size-6" />
        </div>
        <div className="flex-1 space-y-1">
          <h2 className="text-lg font-semibold">Welcome to MindMesh</h2>
          <p className="max-w-2xl text-sm text-muted-foreground">
            This project has no runs yet. Start with the guided experiment: a support agent wrongly denies a refund, you trace the
            cause, fix it with a previewed memory change, stress-test it with a prompt injection and an outage, and measure the result.
            Runs in a sandbox; about five minutes.
          </p>
        </div>
        <Button size="lg" asChild>
          <Link to="/experiment" data-testid="start-experiment">
            <Play /> Run experiment
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

export default function Overview() {
  const q = useQuery({ queryKey: ["overview"], queryFn: api.overview, refetchInterval: 5000 });
  const d = q.data;

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <PageHeader
        title="Overview"
        description="Run health, failures, policy enforcement and evaluation results across this project."
        icon={LayoutDashboard}
      />
      <ErrorNote error={q.error} />
      {d && <FirstRun empty={d.runs.total === 0} />}
      {!d ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
            <Stat label={`Runs (${d.window_days}d)`} value={fmtNum(d.runs.total)} icon={Activity}
              hint={`${d.runs.by_status.running ?? 0} running`} />
            <Stat label="Completion rate" value={fmtPct(d.runs.success_rate)} icon={Gauge}
              tone={d.runs.success_rate !== null && d.runs.success_rate < 0.9 ? "warn" : "good"}
              hint={`${d.runs.by_status.failed ?? 0} failed`} />
            <Stat label="Latency p50 / p95" value={fmtMs(d.runs.latency_p50_ms)} icon={Timer}
              hint={`p95 ${fmtMs(d.runs.latency_p95_ms)}`} />
            <Stat label="Tokens" value={fmtNum(d.runs.tokens)} icon={Coins} hint={`${fmtNum(d.runs.tool_calls)} tool calls`} />
            <Stat label="Blocked / needs approval" icon={ShieldAlert}
              value={`${d.policy.decisions.deny ?? 0} / ${d.policy.decisions.require_approval ?? 0}`}
              hint={<Link to="/control" className="hover:underline">{d.policy.pending_approvals} pending approvals</Link>}
              tone={d.policy.pending_approvals ? "warn" : undefined} />
            <Stat label="Memories" value={fmtNum(Object.values(d.memory).reduce((a, b) => a + b, 0))} icon={Brain}
              hint={`${d.memory.active ?? 0} active · ${(d.memory.superseded ?? 0) + (d.memory.retracted ?? 0)} retired`} />
          </div>

          <div className="grid gap-3 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Runs per day</CardTitle>
                <CardDescription>Succeeded vs failed/cancelled vs other (live, waiting, replay)</CardDescription>
              </CardHeader>
              <CardContent className="h-60">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={d.series} margin={{ left: -20, right: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="date" tickFormatter={(v: string) => v.slice(5)} fontSize={11} stroke="var(--muted-foreground)" />
                    <YAxis allowDecimals={false} fontSize={11} stroke="var(--muted-foreground)" />
                    <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--muted)" }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="succeeded" stackId="a" fill="var(--chart-2)" radius={[0, 0, 0, 0]} />
                    <Bar dataKey="failed" stackId="a" fill="var(--chart-3)" />
                    <Bar dataKey="other" stackId="a" fill="var(--chart-1)" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Tool usage</CardTitle>
                <CardDescription>Executions and errors per tool</CardDescription>
              </CardHeader>
              <CardContent className="h-60">
                {d.tools.length === 0 ? (
                  <EmptyState title="No tool calls yet" />
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={d.tools} layout="vertical" margin={{ left: 10, right: 8 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
                      <XAxis type="number" allowDecimals={false} fontSize={11} stroke="var(--muted-foreground)" />
                      <YAxis type="category" dataKey="tool" width={90} fontSize={11} stroke="var(--muted-foreground)" />
                      <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--muted)" }} />
                      <Bar dataKey="ok" stackId="t" fill="var(--chart-1)" />
                      <Bar dataKey="error" stackId="t" fill="var(--chart-3)" radius={[0, 3, 3, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-3 lg:grid-cols-5">
            <Card className="lg:col-span-3">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <AlertTriangle className="size-4 text-destructive" /> Recent failures
                </CardTitle>
                <CardDescription>Failed, cancelled or escalated runs and runs flagged incorrect by a human</CardDescription>
              </CardHeader>
              <CardContent className="px-0">
                {d.recent_failures.length === 0 ? (
                  <div className="px-4">
                    <EmptyState title="No failures in this window" />
                  </div>
                ) : (
                  <Table>
                    <THead>
                      <TR>
                        <TH>Run</TH>
                        <TH>Status</TH>
                        <TH>Outcome</TH>
                        <TH>When</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {d.recent_failures.map((f) => (
                        <TR key={f.id}>
                          <TD>
                            <Link to={`/runs/${f.id}`} className="font-mono text-xs text-primary hover:underline">
                              {shortId(f.id)}
                            </Link>
                            <div className="text-[11px] text-muted-foreground">{f.agent} · {f.kind}</div>
                            <RunModeBadge run={{ kind: f.kind, model: f.model }} className="mt-1" />
                          </TD>
                          <TD>
                            <div className="flex flex-col items-start gap-1">
                              <StatusBadge status={f.status} />
                              {f.feedback?.verdict === "incorrect" && <Badge variant="destructive">flagged incorrect</Badge>}
                            </div>
                          </TD>
                          <TD className="max-w-sm">
                            <div className="line-clamp-2 text-xs">{f.answer ?? f.error}</div>
                            {f.feedback?.note && (
                              <div className="line-clamp-1 text-[11px] text-destructive/90">“{f.feedback.note}”</div>
                            )}
                          </TD>
                          <TD className="text-xs text-muted-foreground whitespace-nowrap">{timeAgo(f.created_at)}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                )}
              </CardContent>
            </Card>
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Latest evaluations</CardTitle>
                <CardDescription>Task success per variant (reproducible benchmark)</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2.5">
                {d.evals.length === 0 && (
                  <EmptyState title="No benchmark runs yet">
                    Run one from the <Link to="/replay" className="text-primary hover:underline">Replay Lab</Link> or with{" "}
                    <code>mindmesh bench</code>.
                  </EmptyState>
                )}
                {d.evals.map((e) => (
                  <div key={e.id} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span>
                        <span className="text-muted-foreground">{e.suite}/</span>
                        <span className="font-medium">{e.variant}</span>
                      </span>
                      <span className="tabular-nums font-semibold">{fmtPct(e.metrics.success_rate)}</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${e.metrics.success_rate * 100}%`,
                          background: e.metrics.success_rate >= 0.99 ? "var(--chart-2)" : e.metrics.success_rate >= 0.6 ? "var(--chart-4)" : "var(--chart-3)",
                        }}
                      />
                    </div>
                    <div className="text-[10.5px] text-muted-foreground">
                      recall {fmtPct(e.metrics.evidence_recall)} · unsafe executed {e.metrics.unsafe_actions_executed} ·
                      recovery {fmtPct(e.metrics.recovery_rate)}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
