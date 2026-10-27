import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ArrowRightLeft, Bot, CheckCircle2, FileText, Play, RotateCcw, ShieldCheck, Workflow, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { Run, WorkflowDetail, WorkflowTask } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote, IdChip, Metric, PageHeader, Panel, StatusBadge, StatusDot } from "@/components/common";
import { cn, durationMs, fmtMs, parseTs, shortId, timeAgo } from "@/lib/utils";

type TaskData = { task: WorkflowTask; verifier: boolean; selected: boolean; onSelect: (k: string) => void };

const BORDER: Record<string, string> = {
  succeeded: "border-success/50",
  failed: "border-destructive/70",
  running: "border-primary",
  ready: "border-info/60",
  skipped: "border-dashed border-muted-foreground/40",
  pending: "border-border",
};

function TaskNode({ data }: NodeProps<Node<TaskData>>) {
  const t = data.task;
  return (
    <button
      type="button"
      onClick={() => data.onSelect(t.key)}
      className={cn(
        "w-[196px] rounded-md border bg-card px-2.5 py-2 text-left transition-shadow",
        BORDER[t.status] ?? "border-border",
        data.selected && "ring-2 ring-primary/60",
        t.status === "running" && "animate-pulse",
      )}
      data-testid={`wf-task-${t.key}`}
    >
      <Handle type="target" position={Position.Left} className="!bg-muted-foreground" />
      <div className="flex items-center gap-1.5 text-[10.5px] text-muted-foreground">
        {data.verifier ? <ShieldCheck className="size-3" /> : <Bot className="size-3" />}
        {t.agent}
        {t.attempts > 1 && (
          <span className="ml-auto flex items-center gap-0.5 text-warning" title="attempts">
            <RotateCcw className="size-3" /> {t.attempts}/{t.max_attempts}
          </span>
        )}
      </div>
      <div className="font-mono text-[12.5px] font-semibold">{t.key}</div>
      <div className="mt-0.5 flex items-center justify-between text-[10.5px]">
        <span className="flex items-center gap-1"><StatusDot status={t.status} /> {t.status}</span>
        <span className="font-mono text-muted-foreground">{fmtMs(durationMs(t.started_at, t.ended_at))}</span>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-muted-foreground" />
      <Handle type="source" id="bottom" position={Position.Bottom} className="!border-0 !bg-transparent" />
      <Handle type="target" id="bottom-in" position={Position.Bottom} className="!border-0 !bg-transparent" />
    </button>
  );
}

function levels(wf: WorkflowDetail) {
  const byKey = new Map(wf.tasks.map((t) => [t.key, t]));
  const level = new Map<string, number>();
  const depth = (k: string): number => {
    if (level.has(k)) return level.get(k)!;
    const t = byKey.get(k);
    const d = t && t.depends_on.length ? 1 + Math.max(...t.depends_on.map(depth)) : 0;
    level.set(k, d);
    return d;
  };
  wf.tasks.forEach((t) => depth(t.key));
  return level;
}

function layout(wf: WorkflowDetail, selected: string | null, onSelect: (k: string) => void) {
  const level = levels(wf);
  const rows = new Map<number, number>();
  const verifies = new Map((wf.spec.tasks ?? []).filter((t) => t.verifies).map((t) => [t.key, t.verifies as string]));
  const rejected = new Set(wf.events.filter((e) => e.type === "verifier.rejected").map((e) => `${e.payload.verifier}->${e.payload.task}`));
  const handoffs = new Set(wf.events.filter((e) => e.type === "handoff").map((e) => `${e.payload.from}->${e.payload.to}`));
  const nodes: Node[] = wf.tasks.map((t) => {
    const l = level.get(t.key)!;
    const r = rows.get(l) ?? 0;
    rows.set(l, r + 1);
    return { id: t.key, type: "task", position: { x: l * 240, y: r * 96 }, data: { task: t, verifier: verifies.has(t.key), selected: selected === t.key, onSelect } };
  });
  const edges: Edge[] = [];
  wf.tasks.forEach((t) =>
    t.depends_on.forEach((d) =>
      edges.push({
        id: `${d}->${t.key}`,
        source: d,
        target: t.key,
        animated: t.status === "running",
        label: handoffs.has(`${d}->${t.key}`) ? "handoff" : undefined,
        labelStyle: { fontSize: 10, fill: "var(--muted-foreground)" },
        labelBgStyle: { fill: "var(--background)" },
        markerEnd: { type: MarkerType.ArrowClosed },
      }),
    ),
  );
  verifies.forEach((target, v) => {
    if (rejected.has(`${v}->${target}`))
      edges.push({
        id: `reject-${v}`,
        source: v,
        sourceHandle: "bottom",
        target,
        targetHandle: "bottom-in",
        type: "smoothstep",
        label: "rejected → redo",
        style: { stroke: "var(--destructive)", strokeDasharray: "5 4" },
        labelStyle: { fontSize: 10, fill: "var(--destructive)" },
        labelBgStyle: { fill: "var(--background)" },
        markerEnd: { type: MarkerType.ArrowClosed, color: "var(--destructive)" },
      });
  });
  return { nodes, edges };
}

type Attempt = { run: Run; task: string; attempt: number; start: number; end: number | null; rejected: boolean };

/** Attempts per task from the workflow's runs (labels are `<workflow>/<task>#<attempt>`), in milliseconds from the start. */
function attemptsOf(d: WorkflowDetail) {
  const t0 = Math.min(...d.runs.filter((r) => r.started_at).map((r) => parseTs(r.started_at!).getTime()), parseTs(d.created_at).getTime());
  const rejections = new Map<string, number>();
  for (const e of d.events) if (e.type === "verifier.rejected") rejections.set(e.payload.task, (rejections.get(e.payload.task) ?? 0) + 1);
  const out: Attempt[] = [];
  for (const r of d.runs) {
    const m = /\/([^/#]+)#(\d+)$/.exec(r.label ?? "");
    if (!m || !r.started_at) continue;
    const attempt = Number(m[2]);
    out.push({
      run: r, task: m[1], attempt,
      start: parseTs(r.started_at).getTime() - t0,
      end: r.ended_at ? parseTs(r.ended_at).getTime() - t0 : null,
      rejected: attempt <= (rejections.get(m[1]) ?? 0),
    });
  }
  const end = Math.max(1, ...out.map((a) => a.end ?? a.start), d.ended_at ? parseTs(d.ended_at).getTime() - t0 : 0);
  // peak concurrency: sweep over attempt intervals
  const pts = out.flatMap((a) => [[a.start, 1], [a.end ?? end, -1]] as [number, number][]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  let cur = 0;
  let peak = 0;
  for (const [, v] of pts) peak = Math.max(peak, (cur += v));
  return { attempts: out, end, peak };
}

function Gantt({ d, selected, onSelect }: { d: WorkflowDetail; selected: string | null; onSelect: (k: string) => void }) {
  const { attempts, end } = useMemo(() => attemptsOf(d), [d]);
  const lv = levels(d);
  const lanes = d.tasks.slice().sort((a, b) => lv.get(a.key)! - lv.get(b.key)! || a.key.localeCompare(b.key));
  return (
    <Panel title="Execution timeline" description="Each bar is one attempt, a fully traced agent run. Overlapping bars ran in parallel." data-testid="workflow-gantt">
      <div className="px-3 py-2">
        <div className="mb-1 grid grid-cols-[132px_minmax(0,1fr)] gap-2 font-mono text-[10px] text-muted-foreground">
          <span />
          <span className="flex justify-between"><span>0</span><span>{fmtMs(end / 2)}</span><span>{fmtMs(end)}</span></span>
        </div>
        <ul className="space-y-1">
          {lanes.map((t) => (
            <li key={t.key} className={cn("grid grid-cols-[132px_minmax(0,1fr)] items-center gap-2 rounded-sm", selected === t.key && "bg-accent/50")}>
              <button className="flex min-w-0 items-center gap-1.5 px-1 text-left text-xs" onClick={() => onSelect(t.key)}>
                <StatusDot status={t.status} />
                <span className="truncate font-mono">{t.key}</span>
              </button>
              <div className="relative h-5 rounded-sm bg-muted/30">
                {attempts.filter((a) => a.task === t.key).map((a) => {
                  const left = (a.start / end) * 100;
                  const width = Math.max(0.8, (((a.end ?? end) - a.start) / end) * 100);
                  return (
                    <Link
                      key={a.run.id}
                      to={`/runs/${a.run.id}`}
                      title={`${t.key} attempt ${a.attempt}: ${a.run.status}${a.rejected ? ", rejected by verifier" : ""} · ${fmtMs((a.end ?? end) - a.start)}`}
                      className={cn(
                        "absolute top-0.5 flex h-4 items-center justify-center overflow-hidden rounded-[3px] font-mono text-[9.5px] text-background",
                        a.run.status === "failed" ? "bg-destructive" : a.rejected ? "bg-warning" : a.run.status === "running" ? "bg-info" : "bg-success/80",
                      )}
                      style={{ left: `${Math.min(left, 99)}%`, width: `${width}%` }}
                    >
                      #{a.attempt}
                    </Link>
                  );
                })}
              </div>
            </li>
          ))}
        </ul>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1"><span className="size-2 rounded-[2px] bg-success/80" /> succeeded</span>
          <span className="flex items-center gap-1"><span className="size-2 rounded-[2px] bg-warning" /> rejected by verifier, redone</span>
          <span className="flex items-center gap-1"><span className="size-2 rounded-[2px] bg-destructive" /> failed</span>
        </div>
      </div>
    </Panel>
  );
}

function TaskInspector({ d, taskKey }: { d: WorkflowDetail; taskKey: string }) {
  const t = d.tasks.find((x) => x.key === taskKey);
  if (!t) return null;
  const spec = (d.spec.tasks ?? []).find((x) => x.key === taskKey);
  const runs = d.runs.filter((r) => (r.label ?? "").includes(`/${taskKey}#`)).sort((a, b) => (a.label ?? "").localeCompare(b.label ?? ""));
  const feedback = d.events.filter((e) => (e.type === "verifier.rejected" || e.type === "verifier.approved") && (e.payload.task === taskKey || e.payload.verifier === taskKey));
  const incoming = d.events.filter((e) => e.type === "handoff" && e.payload.to === taskKey);
  const evidence = new Map(d.evidence.map((e) => [e.id, e]));
  const received = [...new Set(incoming.flatMap((e) => e.payload.evidence_ids as string[]))].map((id) => evidence.get(id)).filter(Boolean);
  return (
    <Panel
      title={<span className="flex items-center gap-2"><span className="font-mono">{t.key}</span><StatusBadge status={t.status} /></span>}
      description={`${t.agent} · attempt ${t.attempts} of ${t.max_attempts}${spec?.verifies ? ` · verifies ${spec.verifies}` : ""}`}
      data-testid="task-inspector"
    >
      <div className="space-y-3 p-3 text-xs">
        <p className="text-muted-foreground">{t.task}</p>
        {t.depends_on.length > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-muted-foreground">depends on</span>
            {t.depends_on.map((k) => <Badge key={k} variant="outline" className="font-mono">{k}</Badge>)}
          </div>
        )}
        {feedback.length > 0 && (
          <div>
            <div className="mb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Verifier feedback</div>
            <ul className="space-y-1">
              {feedback.map((e) => (
                <li key={e.id} className="flex items-start gap-1.5">
                  {e.type === "verifier.rejected" ? <XCircle className="mt-0.5 size-3.5 text-destructive" /> : <CheckCircle2 className="mt-0.5 size-3.5 text-success" />}
                  <span>
                    <span className="font-mono">{e.payload.verifier}</span> {e.type === "verifier.rejected" ? "rejected" : "approved"}{" "}
                    <span className="font-mono">{e.payload.task}</span>
                    {e.payload.reason && <span className="text-muted-foreground">: {e.payload.reason}</span>}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div>
          <div className="mb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Attempts</div>
          <ul className="divide-y rounded-md border">
            {runs.map((r) => (
              <li key={r.id}>
                <Link to={`/runs/${r.id}`} className="flex items-center gap-2 px-2 py-1 hover:bg-accent/40">
                  <StatusDot status={r.status} />
                  <span className="font-mono">#{(r.label ?? "").split("#")[1]}</span>
                  <span className="min-w-0 flex-1 truncate">{r.result?.answer ?? r.error}</span>
                  <span className="font-mono text-[11px] text-muted-foreground">{fmtMs(durationMs(r.started_at, r.ended_at))}</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
        {received.length > 0 && (
          <div>
            <div className="mb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Evidence handed off to it</div>
            <ul className="space-y-1">
              {received.map((e) => (
                <li key={e!.id} className="rounded-md border px-2 py-1">
                  <span className="font-mono text-[11px] text-muted-foreground">from {e!.task_key}</span>
                  <p className="line-clamp-3">{e!.content}</p>
                </li>
              ))}
            </ul>
          </div>
        )}
        {(t.output?.answer || t.error) && (
          <div>
            <div className="mb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t.error ? "Error" : "Output"}</div>
            <p className={cn("rounded-md border bg-background/50 p-2", t.error && "text-destructive")}>{t.error ?? t.output?.answer}</p>
          </div>
        )}
      </div>
    </Panel>
  );
}

function coordinationText(e: WorkflowDetail["events"][number]): { text: string; tone: string } {
  const p = e.payload;
  switch (e.type) {
    case "task.state_changed":
      return { text: `${p.task}: ${p.from} → ${p.to}${p.error ? ` (${p.error})` : ""}`, tone: p.to === "failed" ? "text-destructive" : "" };
    case "handoff":
      return { text: `handoff ${p.from} → ${p.to} (${(p.evidence_ids ?? []).length} evidence)`, tone: "" };
    case "verifier.rejected":
      return { text: `${p.verifier} rejected ${p.task}: ${p.reason}`, tone: "text-destructive" };
    case "verifier.approved":
      return { text: `${p.verifier} approved ${p.task}`, tone: "text-success" };
    case "task.retry":
      return { text: `retry ${p.task} after attempt ${p.attempt}: ${p.error}`, tone: "text-warning" };
    default:
      return { text: `${e.type} ${p.status ?? ""}`, tone: e.type.startsWith("workflow.") ? "font-semibold" : "" };
  }
}

function WorkflowView({ id }: { id: string }) {
  const wf = useQuery({
    queryKey: ["workflow", id],
    queryFn: () => api.workflow(id),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 800 : false),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const graph = useMemo(() => (wf.data ? layout(wf.data, selected, setSelected) : null), [wf.data, selected]);
  const stats = useMemo(() => (wf.data ? attemptsOf(wf.data) : null), [wf.data]);
  if (wf.error) return <ErrorNote error={wf.error} />;
  if (!wf.data || !graph || !stats) return <Skeleton className="h-96" />;
  const d = wf.data;
  const rejections = d.events.filter((e) => e.type === "verifier.rejected");
  const handoffs = d.events.filter((e) => e.type === "handoff").length;
  const verifiers = new Set((d.spec.tasks ?? []).filter((t) => t.verifies).map((t) => t.key));
  const finalTask = d.tasks.find((t) => verifiers.has(t.key)) ? d.tasks.find((t) => (d.spec.tasks ?? []).some((s) => s.verifies === t.key)) : d.tasks.at(-1);
  const sel = selected ?? (rejections[0]?.payload.task as string | undefined) ?? d.tasks[0]?.key;
  const coordination = d.events.filter((e) => showAll || e.type !== "task.state_changed");

  return (
    <div className="min-w-0 space-y-3">
      <Panel>
        <div className="space-y-2 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={d.status} />
            <span className="text-sm font-semibold">{d.name}</span>
            <IdChip id={d.id} />
            <span className="ml-auto text-[11px] text-muted-foreground">{timeAgo(d.created_at)}</span>
          </div>
          <p className="text-xs text-muted-foreground">Goal: {d.goal}</p>
          {finalTask?.output?.answer && (
            <div className="rounded-md border-l-2 border-l-success bg-success/6 px-3 py-2 text-[13px]" data-testid="workflow-outcome">
              <span className="text-[11px] text-muted-foreground">final output · {finalTask.key}</span>
              <p>{finalTask.output.answer}</p>
            </div>
          )}
        </div>
        <div className="grid grid-cols-3 divide-x border-t sm:grid-cols-6">
          <Metric label="tasks done" value={`${d.tasks.filter((t) => t.status === "succeeded").length}/${d.tasks.length}`} />
          <Metric label="attempts" value={stats.attempts.length} hint={`${stats.attempts.length - d.tasks.length} redone`} />
          <Metric label="verifier rejections" value={rejections.length} tone={rejections.length ? "warn" : "muted"} />
          <Metric label="handoffs" value={handoffs} />
          <Metric label="peak parallelism" value={stats.peak} hint="agents at once" />
          <Metric label="duration" value={<span className="font-mono text-base">{fmtMs(durationMs(d.created_at, d.ended_at))}</span>} />
        </div>
      </Panel>

      {rejections.length > 0 && (
        <Panel title="Verifier feedback" icon={ShieldCheck}>
          <ul className="divide-y">
            {d.events.filter((e) => e.type === "verifier.rejected" || e.type === "verifier.approved").map((e) => (
              <li key={e.id}>
                <button className="flex w-full items-start gap-2 px-3 py-1.5 text-left text-xs hover:bg-accent/40" onClick={() => setSelected(e.payload.task)}>
                  {e.type === "verifier.rejected" ? <XCircle className="mt-0.5 size-3.5 text-destructive" /> : <CheckCircle2 className="mt-0.5 size-3.5 text-success" />}
                  <span>{e.type === "verifier.rejected" ? `${e.payload.verifier} rejected ${e.payload.task}: ${e.payload.reason}` : `${e.payload.verifier} approved ${e.payload.task} after rework`}</span>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel title="Task graph" description="Dependencies, handoffs, and the verifier's send-back. Click a task to inspect it." bodyClassName="p-0">
        <div className="h-[280px]" data-testid="workflow-graph">
          <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={{ task: TaskNode }} fitView fitViewOptions={{ padding: 0.12, maxZoom: 1.1 }} nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }}>
            <Background gap={18} size={1} color="var(--border)" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      </Panel>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0 space-y-3">
          <Gantt d={d} selected={sel} onSelect={setSelected} />
        <Panel
          title="Coordination log"
          icon={ArrowRightLeft}
          actions={<Button size="sm" variant="ghost" className="h-6" onClick={() => setShowAll(!showAll)}>{showAll ? "Hide state changes" : "Show state changes"}</Button>}
        >
          <ol className="max-h-80 overflow-auto py-1">
            {coordination.map((e) => {
              const { text, tone } = coordinationText(e);
              return (
                <li key={e.id} className="flex gap-2 px-3 py-0.5 text-xs">
                  <span className="w-7 shrink-0 text-right font-mono text-[11px] text-muted-foreground">{e.seq}</span>
                  <span className={tone}>{text}</span>
                </li>
              );
            })}
          </ol>
        </Panel>
        </div>
        {sel && <TaskInspector d={d} taskKey={sel} />}
      </div>
      <Panel title="Shared evidence board" icon={FileText} description="Outputs posted by tasks and handed to dependents">
          <ul className="max-h-80 divide-y overflow-auto">
            {d.evidence.length === 0 && <li className="px-3 py-6 text-xs text-muted-foreground">No evidence yet.</li>}
            {d.evidence.map((e) => (
              <li key={e.id} className="px-3 py-1.5 text-xs">
                <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <span className="font-mono text-foreground">{e.task_key}</span>· {e.created_by}
                  {e.run_id && <Link className="font-mono text-primary hover:underline" to={`/runs/${e.run_id}`}>{shortId(e.run_id)}</Link>}
                  <span className="ml-auto">{timeAgo(e.created_at)}</span>
                </div>
                <p className="mt-0.5 line-clamp-3">{e.content}</p>
              </li>
            ))}
          </ul>
        </Panel>
    </div>
  );
}

export default function OrchestrationLab() {
  const { workflowId } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["workflows"], queryFn: api.workflows, refetchInterval: 3000 });
  const start = useMutation({
    mutationFn: () => api.startWorkflow("research-brief"),
    onSuccess: (w) => {
      qc.invalidateQueries({ queryKey: ["workflows"] });
      nav(`/orchestration/${w.id}`);
    },
  });
  const selected = workflowId ?? list.data?.[0]?.id;
  return (
    <div>
      <PageHeader
        title="Orchestration Lab"
        description="Multi-agent workflows: dependencies, parallel work, handoffs, retries and verifier feedback, from the recorded runs."
        icon={Workflow}
        actions={<Button size="sm" onClick={() => start.mutate()} disabled={start.isPending} data-testid="start-workflow"><Play /> Run research-brief</Button>}
      />
      <ErrorNote error={start.error} />
      <div className="grid gap-3 lg:grid-cols-[240px_minmax(0,1fr)]">
        <Panel title="Workflow runs" className="h-fit">
          {list.data?.length === 0 && <EmptyState title="No workflows yet" />}
          <ul className="divide-y">
            {list.data?.map((w) => (
              <li key={w.id}>
                <Link to={`/orchestration/${w.id}`} className={cn("block border-l-2 border-transparent px-3 py-1.5 hover:bg-accent/40", selected === w.id && "border-l-primary bg-accent/60")}>
                  <div className="flex items-center gap-2"><StatusDot status={w.status} /><span className="truncate text-xs font-medium">{w.name}</span></div>
                  <div className="pl-4 text-[11px] text-muted-foreground">{w.succeeded}/{w.tasks} tasks · {timeAgo(w.created_at)}</div>
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
        {selected ? <WorkflowView id={selected} key={selected} /> : <EmptyState title="Start a workflow to see it here" icon={Workflow} />}
      </div>
    </div>
  );
}
