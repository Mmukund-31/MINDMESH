import { useMemo } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Bot, Brain, Cpu, Flag, Gavel, PauseCircle, ShieldAlert, Wrench } from "lucide-react";
import type { Run, TraceNode, TraceStep } from "@/lib/types";
import { cn, fmtMs } from "@/lib/utils";

export type Selection = { kind: "step"; step: TraceStep } | { kind: "node"; step: TraceStep; node: TraceNode } | { kind: "run" };

type StepData = { title: string; subtitle: string; status: string; icon: "run" | "step" | "final" };
type DetailData = { title: string; subtitle: string; tone: "ok" | "bad" | "warn" | "info" | "muted"; kind: string };

const tone: Record<string, string> = {
  ok: "border-success/50 bg-success/8",
  bad: "border-destructive/60 bg-destructive/10",
  warn: "border-warning/60 bg-warning/10",
  info: "border-primary/40 bg-primary/8",
  muted: "border-border bg-card",
};

function statusTone(status: string): DetailData["tone"] {
  if (["ok", "final", "succeeded", "allow", "done"].includes(status)) return "ok";
  if (["error", "blocked", "failed", "deny", "invalid_args", "cancelled"].includes(status)) return "bad";
  if (["pending_approval", "require_approval", "waiting_approval"].includes(status)) return "warn";
  if (status === "running") return "info";
  return "muted";
}

function StepNode({ data, selected }: NodeProps<Node<StepData>>) {
  const Icon = data.icon === "run" ? Bot : data.icon === "final" ? Flag : Cpu;
  return (
    <div
      className={cn(
        "w-[220px] rounded-lg border-2 px-3 py-2 shadow-sm",
        tone[statusTone(data.status)],
        selected && "ring-2 ring-primary",
      )}
    >
      <Handle type="target" position={Position.Left} className="!bg-muted-foreground" />
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Icon className="size-3.5" />
        <span className="truncate">{data.subtitle}</span>
      </div>
      <div className="mt-0.5 truncate text-[13px] font-semibold">{data.title}</div>
      <div className="text-[10.5px] text-muted-foreground">{data.status.replace(/_/g, " ")}</div>
      <Handle type="source" position={Position.Right} className="!bg-muted-foreground" />
      <Handle type="source" id="down" position={Position.Bottom} className="!bg-transparent !border-0" />
    </div>
  );
}

const DETAIL_ICON: Record<string, React.ElementType> = {
  context: Brain,
  model: Bot,
  model_error: Bot,
  policy: Gavel,
  tool: Wrench,
  approval: PauseCircle,
  approval_resolved: PauseCircle,
  guard: ShieldAlert,
  budget: ShieldAlert,
  divergence: ShieldAlert,
};

function DetailNode({ data, selected }: NodeProps<Node<DetailData>>) {
  const Icon = DETAIL_ICON[data.kind] ?? Cpu;
  return (
    <div className={cn("w-[200px] rounded-md border px-2.5 py-1.5", tone[data.tone], selected && "ring-2 ring-primary")}>
      <Handle type="target" position={Position.Top} className="!bg-transparent !border-0" />
      <div className="flex items-center gap-1.5 text-[11.5px] font-medium">
        <Icon className="size-3.5 shrink-0" />
        <span className="truncate">{data.title}</span>
      </div>
      <div className="truncate text-[10.5px] text-muted-foreground">{data.subtitle}</div>
      <Handle type="source" position={Position.Bottom} className="!bg-transparent !border-0" />
    </div>
  );
}

const nodeTypes = { step: StepNode, detail: DetailNode };

export function describeNode(n: TraceNode): DetailData {
  const p = n.event?.payload ?? {};
  switch (n.kind) {
    case "context": {
      const inc = (p.included ?? []).filter((i: any) => i.kind !== "task").length;
      const exc = (p.excluded ?? []).length;
      return { kind: n.kind, title: "Context assembled", subtitle: `${inc} in · ${exc} out · ${p.used_tokens}/${p.budget_tokens} tok`, tone: exc ? "info" : "muted" };
    }
    case "model":
      return { kind: n.kind, title: `Model ${p.model ?? ""}`, subtitle: `${p.tokens_in}+${p.tokens_out} tok · ${fmtMs(p.latency_ms)}`, tone: "muted" };
    case "model_error":
      return { kind: n.kind, title: "Model output rejected", subtitle: p.error ?? "", tone: "bad" };
    case "policy":
      return { kind: n.kind, title: `Policy: ${p.effect}`, subtitle: `${p.tool} · ${p.rule_name ?? p.reason ?? ""}`, tone: statusTone(p.effect) };
    case "tool":
      return {
        kind: n.kind,
        title: `${n.tool ?? p.tool}${n.retries?.length ? ` (${n.retries.length} retries)` : ""}`,
        subtitle: n.status === "ok" ? `ok · ${fmtMs(n.duration_ms)}` : n.error ?? p.error ?? n.status ?? "",
        tone: statusTone(n.status ?? (p.kind === "invalid_args" ? "invalid_args" : "error")),
      };
    case "approval":
      return { kind: n.kind, title: "Approval requested", subtitle: p.reason ?? "", tone: "warn" };
    case "approval_resolved":
      return { kind: n.kind, title: `Approval ${p.status}`, subtitle: p.resolver ? `by ${p.resolver}` : "", tone: p.status === "approved" ? "ok" : "bad" };
    case "guard":
      return { kind: n.kind, title: "Guard triggered", subtitle: p.guard ?? "", tone: "bad" };
    case "budget":
      return { kind: n.kind, title: "Budget exceeded", subtitle: p.budget ?? p.reason ?? "", tone: "bad" };
    case "divergence":
      return { kind: n.kind, title: "Replay diverged", subtitle: p.reason ?? "", tone: "bad" };
    default:
      return { kind: n.kind, title: n.type ?? n.kind, subtitle: "", tone: "muted" };
  }
}

export function stepTitle(s: TraceStep): string {
  if (!s.action) return "in progress…";
  if (s.action.type === "final_answer") return (s.action.answer ?? "").split(":")[0] || "final answer";
  return s.action.tool ?? "tool call";
}

export function TraceGraph({
  run,
  steps,
  onSelect,
  selectedId,
}: {
  run: Run;
  steps: TraceStep[];
  onSelect: (s: Selection) => void;
  selectedId?: string;
}) {
  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    const X = 270;
    nodes.push({
      id: "run",
      type: "step",
      position: { x: 0, y: 0 },
      data: { title: run.agent_name, subtitle: run.kind === "live" ? "run" : run.kind, status: run.status, icon: "run" },
      selected: selectedId === "run",
    });
    let prev = "run";
    steps.forEach((s, i) => {
      const id = `step-${s.step}`;
      nodes.push({
        id,
        type: "step",
        position: { x: (i + 1) * X, y: 0 },
        data: {
          title: stepTitle(s),
          subtitle: `step ${s.step}${s.action?.type === "tool_call" ? " · tool call" : ""}`,
          status: s.status,
          icon: s.action?.type === "final_answer" ? "final" : "step",
        },
        selected: selectedId === id,
      });
      edges.push({
        id: `${prev}->${id}`,
        source: prev,
        target: id,
        animated: s.status === "running",
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { strokeWidth: 1.5 },
      });
      prev = id;
      s.nodes.forEach((n, j) => {
        const nid = `${id}-n${j}`;
        nodes.push({
          id: nid,
          type: "detail",
          position: { x: (i + 1) * X + 10, y: 110 + j * 66 },
          data: describeNode(n),
          selected: selectedId === nid,
        });
        edges.push({
          id: `${j === 0 ? id : `${id}-n${j - 1}`}->${nid}`,
          source: j === 0 ? id : `${id}-n${j - 1}`,
          sourceHandle: j === 0 ? "down" : undefined,
          target: nid,
          style: { strokeDasharray: "4 3", opacity: 0.6 },
        });
      });
    });
    return { nodes, edges };
  }, [run, steps, selectedId]);

  return (
    <div className="h-[460px] rounded-lg border bg-muted/20" data-testid="trace-graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
        minZoom={0.2}
        nodesDraggable={false}
        nodesConnectable={false}
        onNodeClick={(_, node) => {
          if (node.id === "run") return onSelect({ kind: "run" });
          const m = /^step-(\d+)(?:-n(\d+))?$/.exec(node.id);
          if (!m) return;
          const step = steps.find((s) => s.step === Number(m[1]));
          if (!step) return;
          if (m[2] === undefined) onSelect({ kind: "step", step });
          else onSelect({ kind: "node", step, node: step.nodes[Number(m[2])] });
        }}
      >
        <Background gap={18} size={1} color="var(--border)" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
