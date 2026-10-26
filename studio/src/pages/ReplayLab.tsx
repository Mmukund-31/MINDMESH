import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BarChart3, CheckCircle2, FlaskConical, Loader2, Play, RotateCcw, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { EvalRun } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { DiffView } from "@/components/DiffView";
import { EmptyState, ErrorNote, PageHeader, StatusBadge } from "@/components/common";
import { fmtNum, fmtPct, shortId, timeAgo } from "@/lib/utils";

const METRICS: [keyof EvalRun["metrics"], string, "pct" | "int" | "num", boolean][] = [
  ["success_rate", "Task success", "pct", true],
  ["evidence_recall", "Evidence recall", "pct", true],
  ["context_precision", "Context precision", "pct", true],
  ["context_efficiency", "Context efficiency", "pct", true],
  ["unsafe_actions_executed", "Unsafe actions executed", "int", false],
  ["unsafe_actions_blocked", "Unsafe actions blocked", "int", true],
  ["tool_error_rate", "Tool error rate", "pct", false],
  ["recovery_rate", "Recovery after faults", "pct", true],
  ["approvals_requested", "Human approvals", "int", true],
  ["avg_steps", "Avg steps", "num", false],
  ["avg_tokens", "Avg tokens", "num", false],
];

function fmt(v: number | null | undefined, k: "pct" | "int" | "num") {
  if (v === null || v === undefined) return "–";
  return k === "pct" ? fmtPct(v) : k === "int" ? String(v) : fmtNum(v, 1);
}

function Benchmarks() {
  const qc = useQueryClient();
  const suites = useQuery({ queryKey: ["suites"], queryFn: api.evalSuites });
  const evals = useQuery({ queryKey: ["evals"], queryFn: () => api.evals() });
  const [job, setJob] = useState<string | null>(null);
  const jobQ = useQuery({
    queryKey: ["evaljob", job],
    queryFn: () => api.evalJob(job!),
    enabled: !!job,
    refetchInterval: (q) => (q.state.data?.status === "running" ? 700 : false),
  });
  useEffect(() => {
    if (jobQ.data && jobQ.data.status !== "running") {
      qc.invalidateQueries({ queryKey: ["evals"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
    }
  }, [jobQ.data, qc]);
  const start = useMutation({ mutationFn: (suite: string) => api.startEval(suite), onSuccess: (j) => setJob(j.id) });
  const suite = suites.data?.[0];

  // latest run per variant, in suite variant order
  const latest = useMemo(() => {
    const m = new Map<string, EvalRun>();
    for (const e of evals.data ?? []) if (e.suite === suite?.name && !m.has(e.variant)) m.set(e.variant, e);
    return Object.keys(suite?.variants ?? {}).map((v) => m.get(v)).filter(Boolean) as EvalRun[];
  }, [evals.data, suite]);
  const details = useQuery({
    queryKey: ["evaldetails", latest.map((l) => l.id).join()],
    queryFn: () => Promise.all(latest.map((l) => api.evalRun(l.id))),
    enabled: latest.length > 0,
  });
  const chart = latest.map((l) => ({
    variant: l.variant,
    success: Math.round(l.metrics.success_rate * 100),
    recall: Math.round((l.metrics.evidence_recall ?? 0) * 100),
    precision: Math.round((l.metrics.context_precision ?? 0) * 100),
  }));
  const running = jobQ.data?.status === "running" || start.isPending;

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2"><BarChart3 className="size-4" /> Reproducible benchmark: {suite?.name ?? "…"}</CardTitle>
          <CardDescription>{suite?.description}</CardDescription>
        </div>
        <Button onClick={() => suite && start.mutate(suite.name)} disabled={!suite || running} data-testid="run-benchmark">
          {running ? <Loader2 className="animate-spin" /> : <Play />} Run benchmark
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <ErrorNote error={start.error ?? jobQ.data?.error} />
        {latest.length === 0 ? (
          <EmptyState title="No benchmark results yet" icon={BarChart3}>
            Runs every task of the suite against each variant in an isolated database — baseline agent stack vs MindMesh (misconfigured) vs MindMesh (fixed).
          </EmptyState>
        ) : (
          <>
            <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
              <Table data-testid="benchmark-table">
                <THead>
                  <TR>
                    <TH>Metric</TH>
                    {latest.map((l) => <TH key={l.variant} className="text-right">{l.variant}</TH>)}
                  </TR>
                </THead>
                <TBody>
                  {METRICS.map(([k, label, kind]) => (
                    <TR key={k}>
                      <TD className="text-xs">{label}</TD>
                      {latest.map((l) => <TD key={l.variant} className="text-right text-xs font-medium tabular-nums">{fmt(l.metrics[k] as number | null, kind)}</TD>)}
                    </TR>
                  ))}
                </TBody>
              </Table>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chart} margin={{ left: -20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="variant" fontSize={10} stroke="var(--muted-foreground)" />
                    <YAxis domain={[0, 100]} fontSize={10} stroke="var(--muted-foreground)" unit="%" />
                    <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} cursor={{ fill: "var(--muted)" }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar isAnimationActive={false} dataKey="success" name="success %" fill="var(--chart-2)" radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="recall" name="evidence recall %" fill="var(--chart-1)" radius={[3, 3, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="precision" name="context precision %" fill="var(--chart-4)" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
            {details.data && (
              <Table>
                <THead>
                  <TR>
                    <TH>Task</TH>
                    {details.data.map((d) => <TH key={d.variant}>{d.variant}</TH>)}
                  </TR>
                </THead>
                <TBody>
                  {(details.data[0].results ?? []).map((r, i) => (
                    <TR key={r.task_id}>
                      <TD className="text-xs">
                        <div className="font-medium">{r.task_id}</div>
                        <div className="text-[10.5px] text-muted-foreground">{r.description}</div>
                      </TD>
                      {details.data.map((d) => {
                        const x = d.results![i];
                        return (
                          <TD key={d.variant} className="max-w-64 text-[11px]">
                            <div className="flex items-start gap-1.5">
                              {x.success ? <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-success" /> : <XCircle className="mt-0.5 size-3.5 shrink-0 text-destructive" />}
                              <span className="line-clamp-2">{x.answer || x.error}</span>
                            </div>
                          </TD>
                        );
                      })}
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
            <p className="text-[11px] text-muted-foreground">
              Latest results · {latest[0] && timeAgo(latest[0].created_at)} · model {latest[0]?.model} · seed {latest[0]?.seed}. Each task runs in a fresh, isolated database.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default function ReplayLab() {
  const [params, setParams] = useSearchParams();
  const a = params.get("a") ?? "";
  const b = params.get("b") ?? "";
  const runs = useQuery({ queryKey: ["runs", "all"], queryFn: () => api.runs({ limit: 200 }), refetchInterval: 3000 });
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p, { replace: true });
  };
  const runB = runs.data?.find((r) => r.id === b);
  const bDone = runB && !["pending", "running"].includes(runB.status);
  const cmp = useQuery({
    queryKey: ["compare", a, b, runB?.status],
    queryFn: () => api.compare(a, b),
    enabled: !!a && !!b && !!bDone,
  });

  const [model, setModel] = useState("");
  const [scopes, setScopes] = useState("");
  const [budget, setBudget] = useState("");
  const [strategy, setStrategy] = useState("");
  const [enforce, setEnforce] = useState("");
  const rerun = useMutation({
    mutationFn: () => {
      const o: Record<string, unknown> = {};
      if (model) o.model = model;
      if (scopes) o.memory_scopes = scopes.split(",").map((s) => s.trim());
      const ctx: Record<string, unknown> = {};
      if (budget) ctx.budget_tokens = Number(budget);
      if (strategy) ctx.strategy = strategy;
      if (Object.keys(ctx).length) o.context = ctx;
      if (enforce) o.enforce_policies = enforce === "on";
      return api.rerun(a, o);
    },
    onSuccess: (r) => set("b", r.id),
  });
  const replay = useMutation({ mutationFn: () => api.replay(a), onSuccess: (r) => set("b", r.id) });
  const originals = (runs.data ?? []).filter((r) => r.kind === "live" || r.kind === "rerun");
  const derived = (runs.data ?? []).filter((r) => r.id !== a);

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <PageHeader
        title="Replay Lab"
        description="Replay recorded runs safely, rerun with new configuration, compare outcomes and measure improvements."
        icon={FlaskConical}
      />
      <Card>
        <CardContent className="grid gap-3 pt-4 lg:grid-cols-2">
          <div className="space-y-1">
            <Label>A · original run</Label>
            <Select value={a} onChange={(e) => set("a", e.target.value)} className="w-full" data-testid="select-a">
              <option value="">select a run…</option>
              {originals.map((r) => (
                <option key={r.id} value={r.id}>
                  {shortId(r.id)} · {r.kind} · {r.status} · {(r.result?.answer ?? r.error ?? r.task).slice(0, 60)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <Label>B · replay / rerun to compare</Label>
            <Select value={b} onChange={(e) => set("b", e.target.value)} className="w-full" data-testid="select-b">
              <option value="">select a run…</option>
              {derived.map((r) => (
                <option key={r.id} value={r.id}>
                  {shortId(r.id)} · {r.kind}{r.parent_run_id === a ? " (of A)" : ""} · {r.status} · {(r.result?.answer ?? r.error ?? "").slice(0, 50)}
                </option>
              ))}
            </Select>
          </div>
          {a && (
            <div className="space-y-2 rounded-lg border p-3 lg:col-span-2">
              <div className="text-xs font-semibold">Create B from A</div>
              <div className="grid gap-2 sm:grid-cols-5">
                <Input placeholder="model (e.g. ollama:qwen3:8b)" value={model} onChange={(e) => setModel(e.target.value)} />
                <Input placeholder="memory scopes (comma sep.)" value={scopes} onChange={(e) => setScopes(e.target.value)} />
                <Input placeholder="context budget tokens" value={budget} onChange={(e) => setBudget(e.target.value)} />
                <Select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
                  <option value="">strategy: unchanged</option><option value="ranked">ranked</option><option value="naive">naive</option>
                </Select>
                <Select value={enforce} onChange={(e) => setEnforce(e.target.value)}>
                  <option value="">policies: unchanged</option><option value="on">policies on</option><option value="off">policies off</option>
                </Select>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => rerun.mutate()} disabled={rerun.isPending} data-testid="rerun-a">
                  <RotateCcw /> Rerun with current memory & policies {model || scopes || budget || strategy || enforce ? "+ overrides" : ""}
                </Button>
                <Button variant="outline" onClick={() => replay.mutate()} disabled={replay.isPending}>
                  <FlaskConical /> Safe replay (recorded outputs, no side effects)
                </Button>
              </div>
              <ErrorNote error={rerun.error ?? replay.error} />
            </div>
          )}
        </CardContent>
      </Card>

      {a && b ? (
        !bDone ? (
          <Card className="flex items-center gap-2 p-4 text-sm"><Loader2 className="size-4 animate-spin" /> Run B is executing… <StatusBadge status={runB?.status} /></Card>
        ) : cmp.data ? (
          <DiffView cmp={cmp.data} />
        ) : (
          <ErrorNote error={cmp.error} />
        )
      ) : (
        <EmptyState title="Pick two runs to compare" icon={FlaskConical}>
          Typical loop: find a failing run in Execution Studio → fix memory or policy → rerun here → confirm the divergence is the fix → run the benchmark.
        </EmptyState>
      )}
      <Benchmarks />
    </div>
  );
}
