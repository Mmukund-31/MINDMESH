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
import { Activity, AlertTriangle, Brain, Coins, Gauge, LayoutDashboard, ShieldAlert, Timer } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorNote, PageHeader, Stat, StatusBadge } from "@/components/common";
import { Badge } from "@/components/ui/badge";
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
