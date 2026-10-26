import { useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ArrowRightLeft, Bot, FileText, Play, RotateCcw, ShieldCheck, Workflow } from "lucide-react";
import { api } from "@/lib/api";
import type { WorkflowDetail, WorkflowTask } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorNote, Mono, PageHeader, StatusBadge } from "@/components/common";
import { cn, durationMs, fmtMs, shortId, timeAgo } from "@/lib/utils";

type TaskData = { task: WorkflowTask; verifier: boolean };

const BORDER: Record<string, string> = {
  succeeded: "border-success/60",
  failed: "border-destructive/70",
  running: "border-primary animate-pulse",
  ready: "border-info/60",
  skipped: "border-muted-foreground/40 border-dashed",
  pending: "border-border",
};

function TaskNode({ data }: NodeProps<Node<TaskData>>) {
  const t = data.task;
  return (
    <div className={cn("w-[210px] rounded-lg border-2 bg-card px-3 py-2 shadow-sm", BORDER[t.status] ?? "border-border")} data-testid={`wf-task-${t.key}`}>
      <Handle type="target" position={Position.Left} className="!bg-muted-foreground" />
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        {data.verifier ? <ShieldCheck className="size-3.5" /> : <Bot className="size-3.5" />}
        {t.agent}
        {t.attempts > 1 && (
          <Badge variant="warning" className="ml-auto">
            <RotateCcw /> {t.attempts}/{t.max_attempts}
          </Badge>
        )}
      </div>
      <div className="text-[13px] font-semibold">{t.key}</div>
      <div className="mt-1 flex items-center justify-between">
        <StatusBadge status={t.status} />
        <span className="text-[10px] text-muted-foreground">{fmtMs(durationMs(t.started_at, t.ended_at))}</span>
      </div>
      {t.output?.answer && <p className="mt-1 line-clamp-2 text-[10.5px] text-muted-foreground">{t.output.answer}</p>}
      <Handle type="source" position={Position.Right} className="!bg-muted-foreground" />
      <Handle type="source" id="bottom" position={Position.Bottom} className="!bg-transparent !border-0" />
      <Handle type="target" id="bottom-in" position={Position.Bottom} className="!bg-transparent !border-0" />
    </div>
  );
}

function layout(wf: WorkflowDetail) {
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
  const rows = new Map<number, number>();
  const verifies = new Map((wf.spec.tasks ?? []).filter((t) => t.verifies).map((t) => [t.key, t.verifies as string]));
  const rejected = new Set(wf.events.filter((e) => e.type === "verifier.rejected").map((e) => `${e.payload.verifier}->${e.payload.task}`));
  const handoffs = new Set(wf.events.filter((e) => e.type === "handoff").map((e) => `${e.payload.from}->${e.payload.to}`));
  const nodes: Node[] = wf.tasks.map((t) => {
    const l = level.get(t.key)!;
    const r = rows.get(l) ?? 0;
    rows.set(l, r + 1);
    return { id: t.key, type: "task", position: { x: l * 270, y: r * 150 }, data: { task: t, verifier: verifies.has(t.key) } };
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

function EventLine({ e }: { e: WorkflowDetail["events"][number] }) {
  const p = e.payload;
  let text = e.type;
  let tone = "";
  if (e.type === "task.state_changed") text = `${p.task}: ${p.from} → ${p.to}${p.error ? ` (${p.error})` : ""}`;
  if (e.type === "handoff") text = `handoff ${p.from} → ${p.to} (${(p.evidence_ids ?? []).length} evidence)`;
  if (e.type === "verifier.rejected") { text = `${p.verifier} rejected ${p.task}: ${p.reason}`; tone = "text-destructive"; }
  if (e.type === "verifier.approved") { text = `${p.verifier} approved ${p.task}`; tone = "text-success"; }
  if (e.type === "task.retry") { text = `retry ${p.task} after attempt ${p.attempt}: ${p.error}`; tone = "text-warning"; }
  if (e.type.startsWith("workflow.")) { text = `${e.type} ${p.status ?? ""}`; tone = "font-semibold"; }
  return (
    <li className="flex gap-2 text-[11.5px]">
      <span className="w-8 shrink-0 text-right font-mono text-muted-foreground">#{e.seq}</span>
      {e.type === "handoff" ? <ArrowRightLeft className="mt-0.5 size-3 shrink-0 text-muted-foreground" /> : <span className="w-3" />}
      <span className={tone}>{text}</span>
    </li>
  );
}

function WorkflowView({ id }: { id: string }) {
  const wf = useQuery({
    queryKey: ["workflow", id],
    queryFn: () => api.workflow(id),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 800 : false),
  });
  const graph = useMemo(() => (wf.data ? layout(wf.data) : null), [wf.data]);
  if (wf.error) return <ErrorNote error={wf.error} />;
  if (!wf.data || !graph) return <Card className="h-96 animate-pulse" />;
  const d = wf.data;
  return (
    <div className="min-w-0 space-y-3">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 pt-4">
          <span className="text-base font-semibold">{d.name}</span>
          <StatusBadge status={d.status} />
          <Mono className="text-muted-foreground">{d.id}</Mono>
          <p className="w-full text-sm text-muted-foreground">Goal: {d.goal}</p>
        </CardContent>
      </Card>
      <div className="h-[420px] rounded-lg border bg-muted/20" data-testid="workflow-graph">
        <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={{ task: TaskNode }} fitView fitViewOptions={{ padding: 0.2, maxZoom: 1 }} nodesDraggable={false} nodesConnectable={false}>
          <Background gap={18} size={1} color="var(--border)" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Coordination timeline</CardTitle><CardDescription>Readiness, handoffs, retries and verifier verdicts</CardDescription></CardHeader>
          <CardContent><ul className="max-h-96 space-y-1 overflow-auto">{d.events.map((e) => <EventLine key={e.id} e={e} />)}</ul></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><FileText className="size-4" /> Shared evidence board</CardTitle><CardDescription>Outputs posted by tasks and handed to dependents</CardDescription></CardHeader>
          <CardContent className="max-h-96 space-y-2 overflow-auto">
            {d.evidence.length === 0 && <EmptyState title="No evidence yet" />}
            {d.evidence.map((e) => (
              <div key={e.id} className="rounded-md border p-2 text-xs">
                <div className="flex items-center gap-2 text-muted-foreground"><Badge variant="outline">{e.task_key}</Badge>{e.created_by}<span className="ml-auto">{timeAgo(e.created_at)}</span></div>
                <p className="mt-1 line-clamp-4">{e.content}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader><CardTitle>Agent runs</CardTitle><CardDescription>Every task attempt is a fully traced run</CardDescription></CardHeader>
        <CardContent className="px-0">
          <Table>
            <THead><TR><TH>Run</TH><TH>Label</TH><TH>Agent</TH><TH>Status</TH><TH>Outcome</TH><TH>Steps</TH></TR></THead>
            <TBody>
              {d.runs.map((r) => (
                <TR key={r.id}>
                  <TD><Link className="font-mono text-xs text-primary hover:underline" to={`/runs/${r.id}`}>{shortId(r.id)}</Link></TD>
                  <TD className="text-xs">{r.label}</TD>
                  <TD className="text-xs">{r.agent_name}</TD>
                  <TD><StatusBadge status={r.status} /></TD>
                  <TD className="max-w-md"><div className="line-clamp-1 text-xs">{r.result?.answer ?? r.error}</div></TD>
                  <TD className="text-xs">{r.steps}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
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
    <div className="mx-auto max-w-[1500px]">
      <PageHeader
        title="Orchestration Lab"
        description="Multi-agent workflows: dependencies, parallelism, handoffs, retries, verification and shared evidence."
        icon={Workflow}
        actions={<Button onClick={() => start.mutate()} disabled={start.isPending} data-testid="start-workflow"><Play /> Run research-brief workflow</Button>}
      />
      <ErrorNote error={start.error} />
      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <Card className="h-fit">
          <CardHeader><CardTitle>Workflow runs</CardTitle></CardHeader>
          <CardContent className="space-y-1 px-2">
            {list.data?.length === 0 && <EmptyState title="No workflows yet" />}
            {list.data?.map((w) => (
              <Link key={w.id} to={`/orchestration/${w.id}`} className={cn("block rounded-md px-2.5 py-2 hover:bg-muted/60", selected === w.id && "bg-accent/60")}>
                <div className="flex items-center justify-between"><span className="text-sm font-medium">{w.name}</span><StatusBadge status={w.status} /></div>
                <div className="text-[11px] text-muted-foreground">{w.succeeded}/{w.tasks} tasks · {timeAgo(w.created_at)}</div>
              </Link>
            ))}
          </CardContent>
        </Card>
        {selected ? <WorkflowView id={selected} key={selected} /> : <EmptyState title="Start a workflow to see it here" icon={Workflow} />}
      </div>
    </div>
  );
}
