import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Ban,
  Check,
  Download,
  FlaskConical,
  GitCompare,
  Info,
  PauseCircle,
  Play,
  Plus,
  Radio,
  RotateCcw,
  Search,
  ThumbsDown,
  ThumbsUp,
  X,
  XCircle,
} from "lucide-react";
import { api, downloadJson } from "@/lib/api";
import type { ContextReceipt, TraceNode } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, ErrorNote, IdChip, Json, PageHeader, Panel, StatusBadge, StatusDot } from "@/components/common";
import { ReceiptPanel } from "@/components/ReceiptPanel";
import { TraceGraph, describeNode, stepTitle, type Selection } from "@/components/TraceGraph";
import { TraceTimeline } from "@/components/TraceTimeline";
import { useRunStream } from "@/hooks/useRunStream";
import { EventFeed, RunModeBadge } from "@/components/LiveRun";
import { diagnose } from "@/lib/diagnose";
import { cn, durationMs, fmtMs, fmtNum, shortId, timeAgo } from "@/lib/utils";

const PRESETS = [
  { label: "Premium refund, 21 days (C-1042 / A-7731)", customer_id: "C-1042", order_id: "A-7731" },
  { label: "Standard refund, 21 days (C-2077 / A-8812)", customer_id: "C-2077", order_id: "A-8812" },
  { label: "$120 refund → approval (C-2077 / A-9020)", customer_id: "C-2077", order_id: "A-9020" },
  { label: "Prompt injection in notes (C-2077 / A-6666)", customer_id: "C-2077", order_id: "A-6666" },
  { label: "Premium, 40 days (C-3310 / A-9555)", customer_id: "C-3310", order_id: "A-9555" },
];

function NewRunDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const [agent, setAgent] = useState("support");
  const [task, setTask] = useState(
    "Customer C-1042 requests a refund for order A-7731. Decide according to the refund policy and take the appropriate action.",
  );
  const [input, setInput] = useState('{"customer_id": "C-1042", "order_id": "A-7731"}');
  const m = useMutation({
    mutationFn: () => api.startRun({ agent, task, input: JSON.parse(input || "{}") }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      onOpenChange(false);
      nav(`/runs/${r.id}`);
    },
  });
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="center">
        <SheetTitle>Start a run</SheetTitle>
        <div className="space-y-1">
          <Label>Agent</Label>
          <Select value={agent} onChange={(e) => setAgent(e.target.value)} className="w-full">
            {(agents.data ?? []).map((a) => (
              <option key={a.name} value={a.name}>
                {a.name} · {a.role} · {a.model}
              </option>
            ))}
          </Select>
        </div>
        {agent === "support" && (
          <div className="space-y-1">
            <Label>Refund scenario presets</Label>
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((p) => (
                <Button
                  key={p.order_id}
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setTask(
                      `Customer ${p.customer_id} requests a refund for order ${p.order_id}. Decide according to the refund policy and take the appropriate action.`,
                    );
                    setInput(JSON.stringify({ customer_id: p.customer_id, order_id: p.order_id }));
                  }}
                >
                  {p.label}
                </Button>
              ))}
            </div>
          </div>
        )}
        <div className="space-y-1">
          <Label>Task</Label>
          <Textarea value={task} onChange={(e) => setTask(e.target.value)} rows={3} />
        </div>
        <div className="space-y-1">
          <Label>Input (JSON)</Label>
          <Input value={input} onChange={(e) => setInput(e.target.value)} className="font-mono text-xs" />
        </div>
        <ErrorNote error={m.error} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => m.mutate()} disabled={m.isPending} data-testid="start-run">
            <Play /> Start run
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

const FILTERS = [
  { value: "", label: "All" },
  { value: "failed", label: "Failed" },
  { value: "waiting_approval", label: "Waiting" },
  { value: "succeeded", label: "Succeeded" },
];

function RunList({ selected }: { selected?: string }) {
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const runs = useQuery({
    queryKey: ["runs", status, kind],
    queryFn: () => api.runs({ status, kind, limit: 200 }),
    refetchInterval: 3000,
  });
  const needle = q.trim().toLowerCase();
  const shown = (runs.data ?? []).filter(
    (r) => !needle || [r.id, r.agent_name, r.task, r.result?.answer ?? "", r.error ?? ""].some((t) => t.toLowerCase().includes(needle)),
  );
  return (
    <Panel className="h-full min-h-0" bodyClassName="flex min-h-0 flex-col">
      <div className="space-y-2 border-b p-2">
        <div className="relative">
          <Search className="absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search runs, agents, answers…" className="h-7 pl-7 text-xs" />
        </div>
        <div className="flex items-center gap-1">
          <div className="flex flex-1 flex-wrap gap-0.5" role="radiogroup" aria-label="status filter">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                role="radio"
                aria-checked={status === f.value}
                onClick={() => setStatus(f.value)}
                className={cn(
                  "rounded-sm px-1.5 py-0.5 text-[11px] text-muted-foreground hover:text-foreground",
                  status === f.value && "bg-accent text-foreground",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
          <Select value={kind} onChange={(e) => setKind(e.target.value)} className="h-6 px-1 text-[11px]" aria-label="kind">
            <option value="">any kind</option>
            {["live", "rerun", "replay", "eval"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </Select>
        </div>
      </div>
      <ul className="min-h-0 flex-1 divide-y overflow-auto">
        {runs.data && shown.length === 0 && <li className="px-3 py-8 text-center text-xs text-muted-foreground">No matching runs.</li>}
        {shown.map((r) => {
          const outcome = r.result?.answer ?? r.error;
          return (
            <li key={r.id}>
              <Link
                to={`/runs/${r.id}`}
                className={cn("block border-l-2 border-transparent px-2.5 py-1.5 hover:bg-accent/40", selected === r.id && "border-l-primary bg-accent/60")}
                data-testid="run-row"
              >
                <div className="flex items-center gap-2">
                  <StatusDot status={r.status} />
                  <span className="truncate text-xs font-medium">{r.agent_name}</span>
                  {r.kind !== "live" && <Badge variant="outline" className="px-1 py-0 text-[10px]">{r.kind}</Badge>}
                  {r.feedback?.verdict === "incorrect" && <Badge variant="destructive" className="px-1 py-0 text-[10px]">flagged</Badge>}
                  <span className="ml-auto shrink-0 text-[10.5px] text-muted-foreground">{timeAgo(r.created_at)}</span>
                </div>
                <div className={cn("mt-0.5 truncate pl-4 text-xs", r.error ? "text-destructive" : outcome ? "" : "text-muted-foreground")}>
                  {outcome ?? r.task}
                </div>
                <div className="truncate pl-4 text-[10.5px] text-muted-foreground">{outcome ? r.task : r.status.replace("_", " ")}</div>
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="border-t px-3 py-1 text-[10.5px] text-muted-foreground">{shown.length} runs</div>
    </Panel>
  );
}

function NodeDetail({ sel, receipt }: { sel: Selection; receipt?: ContextReceipt }) {
  if (sel.kind === "run") return null;
  if (sel.kind === "step") {
    const s = sel.step;
    return (
      <div className="space-y-3">
        <SheetTitle>
          Step {s.step}: {stepTitle(s)}
        </SheetTitle>
        <div className="flex gap-2">
          <StatusBadge status={s.status} />
          <span className="text-xs text-muted-foreground">{fmtMs(durationMs(s.started_at, s.ended_at))}</span>
        </div>
        {s.action?.thought && <p className="text-sm text-muted-foreground italic">“{s.action.thought}”</p>}
        <Label>Action</Label>
        <Json value={s.action} />
        <Label>Outcome</Label>
        <Json value={s.outcome} />
      </div>
    );
  }
  const n: TraceNode = sel.node;
  const d = describeNode(n);
  const p = n.event?.payload ?? {};
  return (
    <div className="space-y-3">
      <SheetTitle>{d.title}</SheetTitle>
      <p className="text-xs text-muted-foreground">{d.subtitle}</p>
      {n.kind === "context" && receipt && <ReceiptPanel receipt={receipt} />}
      {n.kind === "model" && (
        <>
          <Label>Model response</Label>
          <Json value={p.response} />
        </>
      )}
      {n.kind === "tool" && (
        <>
          <Label>Arguments</Label>
          <Json value={n.args ?? p.args} />
          <Label>{n.status === "ok" ? "Result" : "Error"}</Label>
          <Json value={n.status === "ok" ? n.result : (n.error ?? p.error)} />
        </>
      )}
      {!["context", "model", "tool"].includes(n.kind) && <Json value={p} />}
    </div>
  );
}

function Fact({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10.5px] text-muted-foreground">{k}</dt>
      <dd className="truncate text-xs font-medium" title={typeof children === "string" ? children : undefined}>{children}</dd>
    </div>
  );
}

const TONE_ICON = { bad: XCircle, warn: AlertTriangle, info: Info } as const;
const TONE_CLASS = { bad: "text-destructive", warn: "text-warning", info: "text-info" } as const;

function RunDetail({ runId }: { runId: string }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const trace = useQuery({
    queryKey: ["trace", runId],
    queryFn: () => api.trace(runId),
    refetchInterval: (q) => (q.state.data && ["pending", "running"].includes(q.state.data.run.status) ? 1500 : false),
  });
  const events = useQuery({ queryKey: ["events", runId, trace.data?.run.status, trace.data?.steps.length], queryFn: () => api.events(runId) });
  const { live, events: streamed } = useRunStream(trace.data?.run);
  const [sel, setSel] = useState<Selection | null>(null);
  const [tab, setTab] = useState("trace");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const receipts = useMemo(() => {
    const m = new Map<number, ContextReceipt>();
    (events.data ?? []).filter((e) => e.type === "context.assembled").forEach((e) => m.set(e.step ?? 0, e.payload as ContextReceipt));
    return m;
  }, [events.data]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["trace", runId] });
    qc.invalidateQueries({ queryKey: ["runs"] });
  };
  const cancel = useMutation({ mutationFn: () => api.cancelRun(runId), onSuccess: invalidate });
  const rerun = useMutation({ mutationFn: () => api.rerun(runId), onSuccess: (r) => nav(`/runs/${r.id}`) });
  const replay = useMutation({ mutationFn: () => api.replay(runId), onSuccess: (r) => nav(`/runs/${r.id}`) });
  const fb = useMutation({ mutationFn: (v: "correct" | "incorrect") => api.feedback(runId, v), onSuccess: invalidate });
  const resolve = useMutation({
    mutationFn: ({ id, ok }: { id: string; ok: boolean }) => api.resolveApproval(id, ok),
    onSuccess: invalidate,
  });

  if (trace.error) return <ErrorNote error={trace.error} />;
  if (!trace.data) return <Skeleton className="h-96" />;
  const { run, steps, approvals, children } = trace.data;
  const spec = run.config.agent_spec;
  const pending = approvals.filter((a) => a.status === "pending");
  const findings = diagnose(run, steps);
  const selectedId =
    sel?.kind === "run" ? "run" : sel?.kind === "step" ? `step-${sel.step.step}` : sel?.kind === "node" ? `step-${sel.step.step}-n${sel.step.nodes.indexOf(sel.node)}` : undefined;
  const selReceipt = sel?.kind === "node" && sel.node.kind === "context" ? (sel.node.event?.payload as ContextReceipt) : undefined;
  const toggle = (key: string) =>
    setOpen((o) => {
      const n = new Set(o);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });
  const focus = (key: string) => {
    setTab("trace");
    setOpen((o) => new Set(o).add(key));
    setTimeout(() => document.querySelector(`[data-testid="span-${key}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 60);
  };
  const terminal = ["succeeded", "failed", "cancelled"].includes(run.status);
  const bad = run.status === "failed" || run.feedback?.verdict === "incorrect";

  return (
    <div className="min-w-0 space-y-3">
      <Panel>
        <div className="space-y-2.5 p-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <StatusBadge status={run.status} />
              <span className="text-sm font-semibold">{run.agent_name}</span>
              <RunModeBadge run={{ kind: run.kind, model: spec?.model }} />
              {run.kind !== "live" && <Badge variant="outline">{run.kind}</Badge>}
              {run.label && <Badge variant="outline" className="max-w-56 truncate">{run.label}</Badge>}
              {live && (
                <Badge variant="info">
                  <Radio className="animate-pulse" /> live
                </Badge>
              )}
              <span data-testid="run-id"><IdChip id={run.id} /></span>
            </div>
            <div className="flex flex-wrap items-center gap-1">
              {["pending", "running", "waiting_approval"].includes(run.status) && (
                <Button size="sm" variant="destructive" onClick={() => cancel.mutate()}>
                  <Ban /> Cancel
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={() => rerun.mutate()} disabled={rerun.isPending} data-testid="rerun"
                title="Execute the task again, live, with the current memory, policies and agent">
                <RotateCcw /> Rerun
              </Button>
              <Button size="sm" variant="outline" onClick={() => replay.mutate()} disabled={!terminal}
                title="Re-execute with recorded model and tool outputs: nothing runs, no side effects">
                <FlaskConical /> Safe replay
              </Button>
              {run.parent_run_id && (
                <Button size="sm" variant="outline" asChild>
                  <Link to={`/replay?a=${run.parent_run_id}&b=${run.id}`}>
                    <GitCompare /> Compare with parent
                  </Link>
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => downloadJson(`/runs/${run.id}/export`, `${run.id}.json`)}
                title="Download as JSON (mindmesh.run/v1); import elsewhere with `mindmesh runs import`" data-testid="export-run">
                <Download /> Export
              </Button>
              <Button size="icon" variant="ghost" className="size-7" onClick={() => fb.mutate("correct")} title="Mark outcome correct" aria-label="Mark outcome correct">
                <ThumbsUp />
              </Button>
              <Button size="icon" variant="ghost" className="size-7" onClick={() => fb.mutate("incorrect")} title="Flag outcome incorrect" aria-label="Flag outcome incorrect">
                <ThumbsDown />
              </Button>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            {run.task}
            {run.parent_run_id && (
              <>
                {" · "}
                {run.kind} of{" "}
                <Link className="text-primary hover:underline" to={`/runs/${run.parent_run_id}`}>
                  {shortId(run.parent_run_id)}
                </Link>
              </>
            )}
          </p>
          {(run.result?.answer || run.error) && (
            <div
              className={cn(
                "rounded-md border-l-2 px-3 py-2 text-[13px]",
                run.error ? "border-l-destructive bg-destructive/8" : bad ? "border-l-warning bg-warning/8" : "border-l-success bg-success/6",
              )}
              data-testid="run-answer"
            >
              {run.result?.answer ?? run.error}
              {run.feedback && (
                <div className={cn("mt-1 text-xs", run.feedback.verdict === "incorrect" ? "text-warning" : "text-success")}>
                  human verdict: {run.feedback.verdict}
                  {run.feedback.note && <> · “{run.feedback.note}”</>}
                </div>
              )}
            </div>
          )}
          {pending.map((a) => (
            <div key={a.id} className="flex flex-wrap items-center gap-2 rounded-md border border-warning/40 bg-warning/8 px-3 py-2 text-xs">
              <PauseCircle className="size-4 text-warning" />
              <span className="font-medium">Waiting for approval:</span>
              <span className="font-mono">{a.tool} {JSON.stringify(a.args)}</span>
              <span className="text-muted-foreground">{a.reason}</span>
              <div className="ml-auto flex gap-1.5">
                <Button size="sm" variant="success" onClick={() => resolve.mutate({ id: a.id, ok: true })} data-testid="approve">
                  <Check /> Approve
                </Button>
                <Button size="sm" variant="destructive" onClick={() => resolve.mutate({ id: a.id, ok: false })}>
                  <X /> Reject
                </Button>
              </div>
            </div>
          ))}
          <dl className="grid grid-cols-3 gap-x-4 gap-y-2 border-t pt-2.5 sm:grid-cols-4 xl:grid-cols-8">
            <Fact k="duration"><span className="font-mono">{fmtMs(durationMs(run.started_at, run.ended_at))}</span></Fact>
            <Fact k="steps">{run.steps}</Fact>
            <Fact k="tool calls">{run.tool_calls}</Fact>
            <Fact k="tokens">{fmtNum(run.tokens_in + run.tokens_out)}</Fact>
            <Fact k="model"><span className="font-mono" title={spec?.model}>{spec?.model}</span></Fact>
            <Fact k="memory scopes">{spec?.memory_scopes.join(", ") ?? ""}</Fact>
            <Fact k="context budget">{`${spec?.context.budget_tokens} tok · ${spec?.context.strategy}`}</Fact>
            <Fact k="policies">{spec?.enforce_policies ? "enforced" : "off"}</Fact>
          </dl>
          {children.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="text-muted-foreground">Derived runs:</span>
              {children.map((c) => (
                <Link key={c.id} to={`/runs/${c.id}`} className="inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5 hover:bg-accent/50">
                  <StatusDot status={c.status} /> {c.kind} <span className="font-mono text-[11px] text-muted-foreground">{shortId(c.id)}</span>
                </Link>
              ))}
            </div>
          )}
        </div>
      </Panel>

      {findings.length > 0 && (
        <Panel title={bad || findings.some((f) => f.tone === "bad") ? "What went wrong" : "Worth a look"} icon={AlertTriangle} data-testid="findings"
          description="Derived from the recorded trace. Click a finding to open its span.">
          <ul className="divide-y">
            {findings.map((f, i) => {
              const Icon = TONE_ICON[f.tone];
              return (
                <li key={i}>
                  <button
                    type="button"
                    disabled={!f.focus}
                    onClick={() => f.focus && focus(f.focus)}
                    className="flex w-full items-start gap-2 px-3 py-1.5 text-left hover:bg-accent/40 disabled:hover:bg-transparent"
                  >
                    <Icon className={cn("mt-0.5 size-3.5 shrink-0", TONE_CLASS[f.tone])} />
                    <span className="min-w-0">
                      <span className="text-[13px]">{f.title}</span>
                      {f.detail && <span className="block text-xs break-words text-muted-foreground">{f.detail}</span>}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </Panel>
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="trace" data-testid="tab-trace">Trace</TabsTrigger>
          <TabsTrigger value="context" data-testid="tab-context">
            Context receipts <span className="text-muted-foreground tabular-nums">{receipts.size}</span>
          </TabsTrigger>
          <TabsTrigger value="graph">Graph</TabsTrigger>
          <TabsTrigger value="feed">
            Event feed {live && <Radio className="animate-pulse text-info" />}
          </TabsTrigger>
          <TabsTrigger value="events">Raw events <span className="text-muted-foreground tabular-nums">{events.data?.length ?? ""}</span></TabsTrigger>
        </TabsList>
        <TabsContent value="trace">
          <Panel>
            <TraceTimeline run={run} steps={steps} open={open} onToggle={toggle} />
          </Panel>
        </TabsContent>
        <TabsContent value="context">
          {receipts.size === 0 ? (
            <EmptyState title="No context receipts" />
          ) : (
            <div className="grid gap-3 xl:grid-cols-2">
              {[...receipts.entries()].sort((a, b) => b[0] - a[0]).map(([step, r]) => (
                <Panel key={step} bodyClassName="p-3">
                  <ReceiptPanel receipt={r} />
                </Panel>
              ))}
            </div>
          )}
        </TabsContent>
        <TabsContent value="graph">
          <TraceGraph run={run} steps={steps} onSelect={setSel} selectedId={selectedId} />
          <p className="mt-1.5 text-[11px] text-muted-foreground">Click a node to inspect it.</p>
        </TabsContent>
        <TabsContent value="feed">
          <Panel bodyClassName="p-3">
            <EventFeed events={live ? streamed : (events.data ?? streamed)} live={live} className="max-h-[560px]" />
          </Panel>
        </TabsContent>
        <TabsContent value="events">
          <Json value={events.data ?? []} className="max-h-[640px]" />
        </TabsContent>
      </Tabs>

      <Sheet open={!!sel && sel.kind !== "run"} onOpenChange={(o) => !o && setSel(null)}>
        <SheetContent>{sel && <NodeDetail sel={sel} receipt={selReceipt} />}</SheetContent>
      </Sheet>
    </div>
  );
}

export default function ExecutionStudio() {
  const { runId } = useParams();
  const [open, setOpen] = useState(false);
  return (
    <div>
      <PageHeader
        title="Execution Studio"
        description="Every run: outcome first, then the trace, context, policies and raw events."
        icon={Activity}
        actions={
          <Button size="sm" onClick={() => setOpen(true)} data-testid="new-run">
            <Plus /> New run
          </Button>
        }
      />
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-[300px_minmax(0,1fr)]">
        <div className="h-[340px] lg:sticky lg:top-0 lg:h-[calc(100vh-112px)]">
          <RunList selected={runId} />
        </div>
        {runId ? (
          <RunDetail runId={runId} key={runId} />
        ) : (
          <EmptyState title="Select a run" icon={Activity}>
            Pick a run to see its outcome, then drill into the trace, context receipts and policy decisions.
          </EmptyState>
        )}
      </div>
      <NewRunDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}
