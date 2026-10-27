import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, CheckCircle2, Download, FileText, FlaskConical, GitCompare, Loader2, Play, RotateCcw, ShieldCheck, XCircle } from "lucide-react";
import { api, downloadJson, downloadText } from "@/lib/api";
import type { EvalRun } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DiffView } from "@/components/DiffView";
import { EmptyState, ErrorNote, Metric, PageHeader, Panel, StatusBadge, StatusDot } from "@/components/common";
import { cn, fmtNum, fmtPct, shortId, timeAgo } from "@/lib/utils";

type Kind = "pct" | "int" | "num";
// [metric, label, format, higher is better (null: no "best", e.g. cost depends on the work done)]
const METRICS: [keyof EvalRun["metrics"], string, Kind, boolean | null][] = [
  ["success_rate", "Task success", "pct", true],
  ["evidence_recall", "Evidence recall", "pct", true],
  ["context_precision", "Context precision", "pct", true],
  ["context_efficiency", "Context efficiency", "pct", true],
  ["tool_error_rate", "Tool error rate", "pct", false],
  ["avg_steps", "Avg steps", "num", null],
  ["avg_tokens", "Avg tokens", "num", null],
];
const SAFETY: [keyof EvalRun["metrics"], string, Kind, boolean | null][] = [
  ["unsafe_actions_executed", "Unsafe actions executed", "int", false],
  ["unsafe_actions_blocked", "Unsafe actions blocked", "int", true],
  ["recovery_rate", "Recovery after injected faults", "pct", true],
  ["approvals_requested", "Human approvals requested", "int", true],
];

function fmt(v: number | null | undefined, k: Kind) {
  if (v === null || v === undefined) return "–";
  return k === "pct" ? fmtPct(v) : k === "int" ? String(v) : fmtNum(v, 1);
}

function MetricRows({ rows, latest }: { rows: typeof METRICS; latest: EvalRun[] }) {
  return (
    <>
      {rows.map(([k, label, kind, up]) => {
        const vals = latest.map((l) => l.metrics[k] as number | null);
        const nums = vals.filter((v): v is number => v !== null && v !== undefined);
        const best = up !== null && nums.length > 1 && new Set(nums).size > 1 ? (up ? Math.max(...nums) : Math.min(...nums)) : null;
        return (
          <TR key={k}>
            <TD className="text-xs">{label}</TD>
            {latest.map((l, i) => (
              <TD key={l.variant} className={cn("text-right font-mono text-xs tabular-nums", vals[i] === best && "font-semibold text-success")}>
                {fmt(vals[i], kind)}
              </TD>
            ))}
          </TR>
        );
      })}
    </>
  );
}

function Benchmarks() {
  const qc = useQueryClient();
  const suites = useQuery({ queryKey: ["suites"], queryFn: api.evalSuites });
  const evals = useQuery({ queryKey: ["evals"], queryFn: () => api.evals() });
  const [suiteName, setSuiteName] = useState("");
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
  const report = useMutation({ mutationFn: (suite: string) => downloadText("/export/evals/report", `${suite}-report.md`, { suite }) });
  const suite = suites.data?.find((s) => s.name === suiteName) ?? suites.data?.[0];

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
  const running = jobQ.data?.status === "running" || start.isPending;

  return (
    <div className="space-y-3">
      <Panel
        title={
          <span className="flex items-center gap-2">
            Reproducible benchmark
            {(suites.data?.length ?? 0) > 1 ? (
              <Select value={suite?.name ?? ""} onChange={(e) => setSuiteName(e.target.value)} className="h-6 text-xs" aria-label="suite">
                {suites.data!.map((s) => <option key={s.name}>{s.name}</option>)}
              </Select>
            ) : (
              <span className="font-mono">{suite?.name ?? "…"}</span>
            )}
          </span>
        }
        icon={BarChart3}
        description={suite?.description}
        actions={
          <>
            <Button size="sm" variant="ghost" onClick={() => suite && report.mutate(suite.name)} disabled={latest.length === 0} title="Download a Markdown report: metrics table and per-task outcomes" data-testid="export-report">
              <FileText /> Report (.md)
            </Button>
            <Button size="sm" variant="ghost" onClick={() => downloadJson("/export/evals", "benchmarks.json", { suite: suite?.name })}
              disabled={latest.length === 0} title="Download all results of this suite as JSON (mindmesh.eval/v1)" data-testid="export-evals">
              <Download /> JSON
            </Button>
            <Button size="sm" onClick={() => suite && start.mutate(suite.name)} disabled={!suite || running} data-testid="run-benchmark">
              {running ? <Loader2 className="animate-spin" /> : <Play />} Run benchmark
            </Button>
          </>
        }
      >
        <ErrorNote error={start.error ?? jobQ.data?.error ?? report.error} />
        {latest.length === 0 ? (
          <div className="p-3">
            <EmptyState title="No benchmark results yet" icon={BarChart3}>
              Runs every task of the suite against each variant in a fresh, isolated database, so results are reproducible.
            </EmptyState>
          </div>
        ) : (
          <>
            <div className="grid divide-y sm:grid-cols-3 sm:divide-x sm:divide-y-0" data-testid="variant-outcomes">
              {latest.map((l) => {
                const v = l.metrics.success_rate;
                return (
                  <div key={l.variant} className="px-3 py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-mono text-xs font-medium">{l.variant}</span>
                      <span className={cn("text-lg font-semibold tabular-nums", v >= 0.95 ? "text-success" : v >= 0.7 ? "text-warning" : "text-destructive")}>{fmtPct(v)}</span>
                    </div>
                    <p className="line-clamp-2 text-[11px] text-muted-foreground">{suite?.variants[l.variant]}</p>
                    <p className="mt-1 text-[11px]">
                      <span className={l.metrics.unsafe_actions_executed ? "text-destructive" : "text-muted-foreground"}>
                        {l.metrics.unsafe_actions_executed} unsafe executed
                      </span>
                      <span className="text-muted-foreground"> · {l.metrics.unsafe_actions_blocked} blocked · recovery {fmtPct(l.metrics.recovery_rate)}</span>
                    </p>
                  </div>
                );
              })}
            </div>
            <div className="grid gap-0 border-t xl:grid-cols-2 xl:divide-x">
              <div>
                <div className="px-3 pt-2 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Quality & cost</div>
                <Table data-testid="benchmark-table">
                  <THead>
                    <TR>
                      <TH>Metric</TH>
                      {latest.map((l) => <TH key={l.variant} className="text-right normal-case">{l.variant}</TH>)}
                    </TR>
                  </THead>
                  <TBody>
                    <MetricRows rows={METRICS} latest={latest} />
                  </TBody>
                </Table>
              </div>
              <div>
                <div className="flex items-center gap-1.5 px-3 pt-2 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
                  <ShieldCheck className="size-3.5" /> Safety
                </div>
                <Table data-testid="safety-table">
                  <THead>
                    <TR>
                      <TH>Metric</TH>
                      {latest.map((l) => <TH key={l.variant} className="text-right normal-case">{l.variant}</TH>)}
                    </TR>
                  </THead>
                  <TBody>
                    <MetricRows rows={SAFETY} latest={latest} />
                  </TBody>
                </Table>
              </div>
            </div>
            <p className="border-t px-3 py-1.5 text-[11px] text-muted-foreground">
              Latest results · {timeAgo(latest[0].created_at)} · model <span className="font-mono">{latest[0].model}</span> · seed {latest[0].seed} · best value per row in green.
            </p>
          </>
        )}
      </Panel>
      {details.data && (
        <Panel title="Per-task outcomes" description="Each cell is one task run; hover for the checks that decided it.">
          <Table>
            <THead>
              <TR>
                <TH>Task</TH>
                {details.data.map((d) => <TH key={d.variant} className="normal-case">{d.variant}</TH>)}
              </TR>
            </THead>
            <TBody>
              {(details.data[0].results ?? []).map((r, i) => (
                <TR key={r.task_id}>
                  <TD className="text-xs">
                    <div className="font-mono font-medium">{r.task_id}</div>
                    <div className="text-[10.5px] text-muted-foreground">{r.description}</div>
                  </TD>
                  {details.data.map((d) => {
                    const x = d.results![i];
                    const failed = x.checks.filter((c) => !c.passed);
                    return (
                      <TD key={d.variant} className="max-w-64 text-[11px]">
                        <div
                          className="flex items-start gap-1.5"
                          title={x.checks.map((c) => `${c.passed ? "✓" : "✗"} ${c.type}${c.tool ? ` ${c.tool}` : ""}${c.value !== null && c.value !== undefined ? ` ${JSON.stringify(c.value)}` : ""}`).join("\n")}
                        >
                          {x.success ? <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-success" /> : <XCircle className="mt-0.5 size-3.5 shrink-0 text-destructive" />}
                          <span className="min-w-0">
                            <span className="line-clamp-2">{x.answer || x.error}</span>
                            {failed.length > 0 && <span className="block text-destructive">failed: {failed.map((c) => c.type.replace(/_/g, " ")).join(", ")}</span>}
                          </span>
                        </div>
                      </TD>
                    );
                  })}
                </TR>
              ))}
            </TBody>
          </Table>
        </Panel>
      )}
    </div>
  );
}

function Compare() {
  const [params, setParams] = useSearchParams();
  const runs = useQuery({ queryKey: ["runs", "all"], queryFn: () => api.runs({ limit: 200 }), refetchInterval: 3000 });
  const derivedAll = (runs.data ?? []).filter((r) => r.parent_run_id && (r.kind === "rerun" || r.kind === "replay"));
  // Default: the most recent rerun/replay against its original, so the page opens on a real comparison.
  const a = params.get("a") ?? derivedAll[0]?.parent_run_id ?? "";
  const b = params.get("b") ?? (params.get("a") ? "" : derivedAll[0]?.id ?? "");
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (!p.get("a") && a) p.set("a", a);
    if (!p.get("b") && b && k !== "b") p.set("b", b);
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
  const [showCreate, setShowCreate] = useState(false);
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
  const byId = new Map((runs.data ?? []).map((r) => [r.id, r]));

  return (
    <div className="space-y-3">
      <Panel bodyClassName="p-3 space-y-3">
        <div className="grid gap-3 lg:grid-cols-[1fr_1fr_auto] lg:items-end">
          <div className="space-y-1">
            <Label>A · original run</Label>
            <Select value={a} onChange={(e) => set("a", e.target.value)} className="w-full" data-testid="select-a">
              <option value="">select a run…</option>
              {originals.map((r) => (
                <option key={r.id} value={r.id}>
                  {shortId(r.id)} · {r.agent_name} · {r.status} · {(r.result?.answer ?? r.error ?? r.task).slice(0, 60)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <Label>B · replay or rerun to compare</Label>
            <Select value={b} onChange={(e) => set("b", e.target.value)} className="w-full" data-testid="select-b">
              <option value="">select a run…</option>
              {derived.map((r) => (
                <option key={r.id} value={r.id}>
                  {shortId(r.id)} · {r.kind}{r.parent_run_id === a ? " of A" : ""} · {r.status} · {(r.result?.answer ?? r.error ?? "").slice(0, 50)}
                </option>
              ))}
            </Select>
          </div>
          <Button size="sm" variant="outline" disabled={!a} onClick={() => setShowCreate(!showCreate)}>
            <RotateCcw /> Create B from A
          </Button>
        </div>
        {showCreate && a && (
          <div className="space-y-2 rounded-md border p-2.5">
            <div className="text-xs text-muted-foreground">
              Rerun executes A's task again, live, with today's memory, policies and these overrides. Safe replay re-runs A's recorded decisions: nothing executes.
            </div>
            <div className="grid gap-2 sm:grid-cols-5">
              <Input placeholder="model (e.g. ollama:qwen3:4b)" value={model} onChange={(e) => setModel(e.target.value)} />
              <Input placeholder="memory scopes (comma sep.)" value={scopes} onChange={(e) => setScopes(e.target.value)} />
              <Input placeholder="context budget tokens" value={budget} onChange={(e) => setBudget(e.target.value)} />
              <Select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
                <option value="">strategy: unchanged</option><option value="ranked">ranked</option><option value="naive">naive</option>
              </Select>
              <Select value={enforce} onChange={(e) => setEnforce(e.target.value)}>
                <option value="">policies: unchanged</option><option value="on">policies on</option><option value="off">policies off</option>
              </Select>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Button size="sm" onClick={() => rerun.mutate()} disabled={rerun.isPending} data-testid="rerun-a">
                <RotateCcw /> Rerun{model || scopes || budget || strategy || enforce ? " with overrides" : ""}
              </Button>
              <Button size="sm" variant="outline" onClick={() => replay.mutate()} disabled={replay.isPending}>
                <FlaskConical /> Safe replay
              </Button>
            </div>
            <ErrorNote error={rerun.error ?? replay.error} />
          </div>
        )}
      </Panel>

      {a && b ? (
        !bDone ? (
          <Panel bodyClassName="flex items-center gap-2 p-3 text-xs"><Loader2 className="size-4 animate-spin" /> Run B is executing… <StatusBadge status={runB?.status} /></Panel>
        ) : cmp.data ? (
          <DiffView cmp={cmp.data} />
        ) : (
          <ErrorNote error={cmp.error} />
        )
      ) : (
        <EmptyState title="Pick two runs to compare" icon={FlaskConical}>
          Typical loop: find a failing run in Execution Studio, fix memory or a policy, rerun it, confirm the divergence is the fix, then run the benchmark.
        </EmptyState>
      )}

      {derivedAll.length > 0 && (
        <Panel title="Recent comparisons" icon={GitCompare} description="Reruns and replays with their originals">
          <ul className="divide-y">
            {derivedAll.slice(0, 8).map((r) => {
              const parent = byId.get(r.parent_run_id!);
              const active = r.id === b;
              return (
                <li key={r.id}>
                  <Link
                    to={`/replay?a=${r.parent_run_id}&b=${r.id}`}
                    className={cn("grid grid-cols-[70px_minmax(0,1fr)_16px_minmax(0,1fr)_auto] items-center gap-2 px-3 py-1.5 text-xs hover:bg-accent/40", active && "bg-accent/60")}
                  >
                    <Badge variant="outline" className="justify-center">{r.kind}</Badge>
                    <span className="flex min-w-0 items-center gap-1.5"><StatusDot status={parent?.status} /><span className="truncate">{parent?.result?.answer ?? parent?.error ?? shortId(r.parent_run_id)}</span></span>
                    <span className="text-muted-foreground">→</span>
                    <span className="flex min-w-0 items-center gap-1.5"><StatusDot status={r.status} /><span className="truncate">{r.result?.answer ?? r.error ?? r.status}</span></span>
                    <span className="text-[11px] text-muted-foreground">{timeAgo(r.created_at)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </Panel>
      )}
    </div>
  );
}

export default function ReplayLab() {
  const [params] = useSearchParams();
  const evals = useQuery({ queryKey: ["evals"], queryFn: () => api.evals() });
  const runs = useQuery({ queryKey: ["runs", "all"], queryFn: () => api.runs({ limit: 200 }) });
  const derived = (runs.data ?? []).filter((r) => r.kind === "rerun" || r.kind === "replay").length;
  const suites = new Set((evals.data ?? []).map((e) => e.suite)).size;
  const [tab, setTab] = useState(params.get("tab") ?? "compare");
  return (
    <div className="space-y-3">
      <PageHeader title="Replay & Evaluation" description="Prove a change: diff runs step by step, see context deltas, and measure with reproducible benchmarks." icon={FlaskConical} />
      <div className="grid grid-cols-3 divide-x rounded-lg border bg-card">
        <Metric label="replays & reruns" value={derived} />
        <Metric label="benchmark suites run" value={suites} />
        <Metric label="benchmark results" value={evals.data?.length ?? 0} hint="variants × runs" />
      </div>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="compare"><GitCompare /> Compare runs</TabsTrigger>
          <TabsTrigger value="benchmarks"><BarChart3 /> Benchmarks</TabsTrigger>
        </TabsList>
        <TabsContent value="compare"><Compare /></TabsContent>
        <TabsContent value="benchmarks"><Benchmarks /></TabsContent>
      </Tabs>
    </div>
  );
}
