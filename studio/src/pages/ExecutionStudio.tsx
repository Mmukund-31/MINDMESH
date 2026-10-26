import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Ban,
  Check,
  FlaskConical,
  GitCompare,
  Play,
  Plus,
  Radio,
  RotateCcw,
  ThumbsDown,
  ThumbsUp,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { ContextReceipt, MMEvent, Run, TraceNode, TraceStep } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, ErrorNote, Json, KV, Mono, PageHeader, StatusBadge } from "@/components/common";
import { ReceiptPanel } from "@/components/ReceiptPanel";
import { TraceGraph, describeNode, stepTitle, type Selection } from "@/components/TraceGraph";
import { useRunStream } from "@/hooks/useRunStream";
import { cn, durationMs, fmtMs, fmtNum, parseTs, shortId, timeAgo } from "@/lib/utils";

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

function RunList({ selected }: { selected?: string }) {
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const runs = useQuery({
    queryKey: ["runs", status, kind],
    queryFn: () => api.runs({ status, kind, limit: 100 }),
    refetchInterval: 3000,
  });
  return (
    <Card className="flex h-full min-h-0 flex-col">
      <CardHeader className="gap-2">
        <CardTitle>Runs</CardTitle>
        <div className="flex gap-2">
          <Select value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 flex-1 text-xs">
            <option value="">all statuses</option>
            {["running", "waiting_approval", "succeeded", "failed", "cancelled"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </Select>
          <Select value={kind} onChange={(e) => setKind(e.target.value)} className="h-8 flex-1 text-xs">
            <option value="">all kinds</option>
            {["live", "rerun", "replay", "eval"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </Select>
        </div>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 overflow-auto px-2">
        {runs.data?.length === 0 && <EmptyState title="No runs yet">Start one with “New run”.</EmptyState>}
        <ul className="space-y-1">
          {runs.data?.map((r) => (
            <li key={r.id}>
              <Link
                to={`/runs/${r.id}`}
                className={cn(
                  "block rounded-md border border-transparent px-2.5 py-2 hover:bg-muted/60",
                  selected === r.id && "border-primary/40 bg-accent/60",
                )}
                data-testid="run-row"
              >
                <div className="flex items-center justify-between gap-2">
                  <Mono className="text-muted-foreground">{shortId(r.id)}</Mono>
                  <StatusBadge status={r.status} />
                </div>
                <div className="mt-1 line-clamp-1 text-xs">{r.result?.answer ?? r.error ?? r.task}</div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[10.5px] text-muted-foreground">
                  <span>{r.agent_name}</span>·<span>{r.kind}</span>·<span>{timeAgo(r.created_at)}</span>
                  {r.feedback?.verdict === "incorrect" && <Badge variant="destructive">flagged</Badge>}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
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
        {s.action?.thought && <p className="text-sm italic text-muted-foreground">“{s.action.thought}”</p>}
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
          <Label>Prompt messages</Label>
          {(p.messages ?? []).map((m: { role: string; content: string }, i: number) => (
            <div key={i} className="space-y-1">
              <Badge variant="outline">{m.role}</Badge>
              <Json value={m.content} className="max-h-60" />
            </div>
          ))}
        </>
      )}
      {n.kind === "tool" && (
        <>
          <Label>Arguments</Label>
          <Json value={n.args ?? p.args} />
          {n.retries && (
            <>
              <Label>Retries</Label>
              <Json value={n.retries} />
            </>
          )}
          <Label>{n.status === "ok" ? "Result" : "Error"}</Label>
          <Json value={n.status === "ok" ? n.result : (n.error ?? p.error)} />
        </>
      )}
      {!["context", "model", "tool"].includes(n.kind) && <Json value={p} />}
    </div>
  );
}

function Timeline({ events, run }: { events: MMEvent[]; run: Run }) {
  const t0 = events.length ? parseTs(events[0].ts).getTime() : 0;
  const tEnd = events.length ? Math.max(...events.map((e) => parseTs(e.ts).getTime() + (e.duration_ms ?? 0))) : 1;
  const span = Math.max(1, tEnd - t0);
  return (
    <div className="space-y-0.5" data-testid="timeline">
      {events.map((e) => {
        const start = parseTs(e.ts).getTime() - (e.duration_ms ?? 0) - t0;
        return (
          <div key={e.id} className="grid grid-cols-[42px_150px_1fr_70px] items-center gap-2 text-[11px]">
            <span className="text-right font-mono text-muted-foreground">#{e.seq}</span>
            <span className={cn("truncate font-medium", e.type.includes("fail") || e.payload.effect === "deny" ? "text-destructive" : "")}>
              {e.type}
              {e.step ? <span className="text-muted-foreground"> · s{e.step}</span> : null}
            </span>
            <div className="relative h-3 rounded bg-muted/50">
              <div
                className="absolute top-0 h-3 rounded bg-primary/70"
                style={{ left: `${(Math.max(0, start) / span) * 100}%`, width: `max(3px, ${((e.duration_ms ?? 0) / span) * 100}%)` }}
              />
            </div>
            <span className="text-right tabular-nums text-muted-foreground">{e.duration_ms ? fmtMs(e.duration_ms) : ""}</span>
          </div>
        );
      })}
      {events.length === 0 && <EmptyState title={run.status === "pending" ? "Waiting to start…" : "No events"} />}
    </div>
  );
}

function RunDetail({ runId }: { runId: string }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const trace = useQuery({
    queryKey: ["trace", runId],
    queryFn: () => api.trace(runId),
    refetchInterval: (q) => (q.state.data && ["pending", "running"].includes(q.state.data.run.status) ? 1500 : false),
  });
  const events = useQuery({ queryKey: ["events", runId, trace.data?.run.status, trace.data?.steps.length], queryFn: () => api.events(runId) });
  const { live } = useRunStream(trace.data?.run);
  const [sel, setSel] = useState<Selection | null>(null);
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
  if (!trace.data) return <Card className="h-96 animate-pulse" />;
  const { run, steps, approvals, children } = trace.data;
  const spec = run.config.agent_spec;
  const pending = approvals.filter((a) => a.status === "pending");
  const lastReceipt = receipts.size ? receipts.get(Math.max(...receipts.keys())) : undefined;
  const selectedId =
    sel?.kind === "run" ? "run" : sel?.kind === "step" ? `step-${sel.step.step}` : sel?.kind === "node" ? `step-${sel.step.step}-n${sel.step.nodes.indexOf(sel.node)}` : undefined;
  const selReceipt = sel?.kind === "node" && sel.node.kind === "context" ? (sel.node.event?.payload as ContextReceipt) : undefined;

  return (
    <div className="min-w-0 space-y-3">
      <Card>
        <CardContent className="space-y-3 pt-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <Mono className="text-sm" data-testid="run-id">{run.id}</Mono>
                <StatusBadge status={run.status} />
                <Badge variant="outline">{run.kind}</Badge>
                {live && (
                  <Badge variant="info">
                    <Radio className="animate-pulse" /> live
                  </Badge>
                )}
                {run.feedback && (
                  <Badge variant={run.feedback.verdict === "incorrect" ? "destructive" : "success"}>
                    human: {run.feedback.verdict}
                  </Badge>
                )}
              </div>
              <p className="text-sm">{run.task}</p>
              {run.parent_run_id && (
                <p className="text-xs text-muted-foreground">
                  {run.kind} of{" "}
                  <Link className="text-primary hover:underline" to={`/runs/${run.parent_run_id}`}>
                    {shortId(run.parent_run_id)}
                  </Link>
                </p>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {["pending", "running", "waiting_approval"].includes(run.status) && (
                <Button size="sm" variant="destructive" onClick={() => cancel.mutate()}>
                  <Ban /> Cancel
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={() => rerun.mutate()} disabled={rerun.isPending} data-testid="rerun">
                <RotateCcw /> Rerun
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => replay.mutate()}
                disabled={!["succeeded", "failed", "cancelled"].includes(run.status)}
                title="Re-execute with recorded model & tool outputs (no side effects)"
              >
                <FlaskConical /> Safe replay
              </Button>
              {run.parent_run_id && (
                <Button size="sm" variant="outline" asChild>
                  <Link to={`/replay?a=${run.parent_run_id}&b=${run.id}`}>
                    <GitCompare /> Compare with parent
                  </Link>
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => fb.mutate("correct")} title="Mark outcome correct">
                <ThumbsUp />
              </Button>
              <Button size="sm" variant="ghost" onClick={() => fb.mutate("incorrect")} title="Flag outcome incorrect">
                <ThumbsDown />
              </Button>
            </div>
          </div>
          {(run.result?.answer || run.error) && (
            <div
              className={cn(
                "rounded-lg border p-3 text-sm",
                run.error ? "border-destructive/40 bg-destructive/8" : "border-success/30 bg-success/5",
              )}
              data-testid="run-answer"
            >
              {run.result?.answer ?? run.error}
            </div>
          )}
          {pending.map((a) => (
            <div key={a.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-warning/50 bg-warning/10 p-3 text-sm">
              <span className="font-medium">Approval needed:</span>
              <Mono>
                {a.tool} {JSON.stringify(a.args)}
              </Mono>
              <span className="text-xs text-muted-foreground">{a.reason}</span>
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
          <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-4">
            <KV k="agent">{run.agent_name}</KV>
            <KV k="model">{spec?.model}</KV>
            <KV k="steps / tool calls">
              {run.steps} / {run.tool_calls}
            </KV>
            <KV k="tokens">{fmtNum(run.tokens_in + run.tokens_out)}</KV>
            <KV k="duration">{fmtMs(durationMs(run.started_at, run.ended_at))}</KV>
            <KV k="memory scopes">{spec?.memory_scopes.join(", ")}</KV>
            <KV k="context budget">{spec?.context.budget_tokens} tok</KV>
            <KV k="policies">{spec?.enforce_policies ? "enforced" : "off"}</KV>
          </div>
          {children.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="text-muted-foreground">Derived runs:</span>
              {children.map((c) => (
                <Link key={c.id} to={`/runs/${c.id}`} className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 hover:bg-muted">
                  {c.kind} <Mono>{shortId(c.id)}</Mono> <StatusBadge status={c.status} />
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Tabs defaultValue="graph">
        <TabsList>
          <TabsTrigger value="graph">Execution graph</TabsTrigger>
          <TabsTrigger value="steps">Steps</TabsTrigger>
          <TabsTrigger value="context" data-testid="tab-context">
            Context receipts
          </TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="events">Raw events</TabsTrigger>
        </TabsList>
        <TabsContent value="graph">
          <TraceGraph run={run} steps={steps} onSelect={setSel} selectedId={selectedId} />
          <p className="mt-1.5 text-[11px] text-muted-foreground">
            Click a step or detail node to inspect inputs, outputs, policy decisions and the context receipt.
          </p>
        </TabsContent>
        <TabsContent value="steps" className="space-y-2">
          {steps.map((s: TraceStep) => (
            <Card key={s.step} className="p-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-semibold">Step {s.step}</span>
                <span>{stepTitle(s)}</span>
                <StatusBadge status={s.status} />
                {s.action?.args && <Mono className="text-muted-foreground">{JSON.stringify(s.action.args)}</Mono>}
              </div>
              {s.action?.thought && <p className="mt-1 text-xs italic text-muted-foreground">“{s.action.thought}”</p>}
              {s.outcome?.policy && (
                <p className="mt-1 text-xs">
                  policy: <StatusBadge status={s.outcome.policy.effect} /> {s.outcome.policy.rule_name} — {s.outcome.policy.reason}
                </p>
              )}
              {s.outcome && s.outcome.status !== "final" && (
                <Json value={s.outcome.result ?? s.outcome.error ?? s.outcome} className="mt-2 max-h-40" />
              )}
            </Card>
          ))}
        </TabsContent>
        <TabsContent value="context">
          {receipts.size === 0 ? (
            <EmptyState title="No context receipts" />
          ) : (
            <div className="grid gap-3 xl:grid-cols-2">
              {[...receipts.entries()].sort((a, b) => b[0] - a[0]).map(([step, r]) => (
                <Card key={step} className={cn("p-3", r === lastReceipt && "ring-1 ring-primary/40")}>
                  <ReceiptPanel receipt={r} />
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
        <TabsContent value="timeline">
          <Card className="p-3">
            <Timeline events={events.data ?? []} run={run} />
          </Card>
        </TabsContent>
        <TabsContent value="events">
          <Json value={events.data ?? []} className="max-h-[600px]" />
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
    <div className="mx-auto max-w-[1500px]">
      <PageHeader
        title="Execution Studio"
        description="Execution graphs, timelines, model calls, tool calls, policy decisions and context receipts for every run."
        icon={Activity}
        actions={
          <Button onClick={() => setOpen(true)} data-testid="new-run">
            <Plus /> New run
          </Button>
        }
      />
      <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
        <div className="lg:sticky lg:top-0 lg:h-[calc(100vh-150px)]">
          <RunList selected={runId} />
        </div>
        {runId ? (
          <RunDetail runId={runId} key={runId} />
        ) : (
          <EmptyState title="Select a run" icon={Activity}>
            Pick a run on the left to see its execution graph, or start a new run.
          </EmptyState>
        )}
      </div>
      <NewRunDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}
