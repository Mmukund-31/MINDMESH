import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  Cpu,
  Eye,
  FlaskConical,
  Loader2,
  Lock,
  Play,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  Wrench,
  XCircle,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Comparison, ContextReceipt, EvalRun, ExperimentRunInfo, ExperimentState } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ErrorNote, Mono } from "@/components/common";
import { ReceiptPanel } from "@/components/ReceiptPanel";
import { DiffView } from "@/components/DiffView";
import { LiveRun, RunModeBadge } from "@/components/LiveRun";
import { MemoryImpactView, PolicyImpactView } from "@/components/Impact";
import { Scorecard, VARIANT_TEXT, improvementSummary } from "@/components/Scorecard";
import { modelName } from "@/lib/narrate";
import { cn, timeAgo } from "@/lib/utils";

const DONE = ["succeeded", "failed", "cancelled"];
const isDone = (r?: ExperimentRunInfo | null): r is ExperimentRunInfo => !!r && DONE.includes(r.status);
const isApproved = (answer?: string | null) => !!answer?.startsWith("APPROVED");
const approved = (r: { result?: { answer?: string } | null }) => isApproved(r.result?.answer);
const SUITE = "refund";
const VARIANTS = ["baseline", "mindmesh-misconfigured", "mindmesh"];

type Mode = "demo" | "live";

function Step({
  n,
  id,
  title,
  done,
  locked,
  lockedText,
  children,
}: {
  n: number;
  id: string;
  title: string;
  done: boolean;
  locked?: boolean;
  lockedText?: string;
  children: ReactNode;
}) {
  return (
    <Card id={id} className={cn("scroll-mt-4", locked && "opacity-60")} data-testid={`step-${id}`}>
      <CardContent className="space-y-3 pt-4">
        <div className="flex items-center gap-2.5">
          <span
            className={cn(
              "grid size-7 shrink-0 place-items-center rounded-full text-xs font-bold",
              done ? "bg-success text-white" : "bg-primary/15 text-primary",
            )}
          >
            {done ? <CheckCircle2 className="size-4" /> : n}
          </span>
          <h2 className="text-base font-semibold">{title}</h2>
          {locked && <Lock className="ml-auto size-4 text-muted-foreground" />}
        </div>
        {locked ? <p className="text-sm text-muted-foreground">{lockedText}</p> : children}
      </CardContent>
    </Card>
  );
}

function Explain({ tone = "info", children, testid }: { tone?: "info" | "bad" | "good" | "warn"; children: ReactNode; testid?: string }) {
  return (
    <div
      className={cn(
        "rounded-lg border p-3 text-sm leading-relaxed",
        tone === "info" && "border-info/30 bg-info/5",
        tone === "bad" && "border-destructive/40 bg-destructive/8",
        tone === "good" && "border-success/40 bg-success/8",
        tone === "warn" && "border-warning/40 bg-warning/8",
      )}
      data-testid={testid}
    >
      {children}
    </div>
  );
}

function Stepper({ steps }: { steps: { id: string; label: string; done: boolean }[] }) {
  return (
    <ol className="flex flex-wrap gap-1.5">
      {steps.map((s, i) => (
        <li key={s.id}>
          <a
            href={`#${s.id}`}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs hover:bg-muted",
              s.done && "border-success/40 text-success",
            )}
          >
            {s.done ? <CheckCircle2 className="size-3.5" /> : <span className="tabular-nums text-muted-foreground">{i + 1}</span>}
            {s.label}
          </a>
        </li>
      ))}
    </ol>
  );
}

function ModePicker({ mode, setMode, live }: { mode: Mode; setMode: (m: Mode) => void; live: string | null }) {
  return (
    <div className="space-y-1">
      <div className="inline-flex rounded-lg border p-0.5" role="radiogroup" aria-label="Model mode">
        <Button size="sm" variant={mode === "demo" ? "secondary" : "ghost"} onClick={() => setMode("demo")} role="radio" aria-checked={mode === "demo"}>
          <Bot /> Demo model
        </Button>
        <Button
          size="sm"
          variant={mode === "live" ? "secondary" : "ghost"}
          onClick={() => setMode("live")}
          disabled={!live}
          role="radio"
          aria-checked={mode === "live"}
          title={live ? undefined : "Start the server with MINDMESH_MODEL=ollama:qwen3:4b to use a real model"}
        >
          <Cpu /> Live model{live ? ` · ${modelName(live)}` : ""}
        </Button>
      </div>
      <p className="max-w-md text-[11px] text-muted-foreground">
        {mode === "demo"
          ? "Demo: a deterministic scripted model that only sees what MindMesh puts in its context, so every run is reproducible."
          : `Live: ${live} makes the decisions. Results can vary between runs, and each step takes a few seconds.`}
        {!live && " No live model is configured on this server."}
      </p>
    </div>
  );
}

/** Step 2: the context receipt explains why the agent decided what it did. */
function Diagnosis({ runId }: { runId: string }) {
  const receipts = useQuery({ queryKey: ["receipts", runId], queryFn: () => api.receipts(runId) });
  const run = useQuery({ queryKey: ["runs", "one", runId], queryFn: () => api.run(runId) });
  const first: ContextReceipt | undefined = receipts.data?.[0];
  if (!first) return <ErrorNote error={receipts.error} />;
  const used = first.included.find((i) => i.subject_key === "refund_policy");
  const missed = first.excluded.find((i) => i.subject_key === "refund_policy");
  const scopes = run.data?.config.agent_spec?.memory_scopes ?? [];
  return (
    <div className="space-y-3">
      <p className="text-sm">
        Every step records a <b>context receipt</b>: exactly which memories the agent was shown, and why everything else was left out.
        Here is the receipt for the agent's first step:
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm" data-testid="diagnosis-used">
          <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-warning">
            <Eye className="size-3.5" /> What the agent saw
          </div>
          {used ? (
            <>
              <p>{used.content}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">scope {used.scope} · {used.source}</p>
            </>
          ) : (
            <p className="text-muted-foreground">No refund policy was in context.</p>
          )}
        </div>
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm" data-testid="diagnosis-missed">
          <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-destructive">
            <XCircle className="size-3.5" /> What it never saw
          </div>
          {missed ? (
            <>
              <p>{missed.content}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                excluded: <Mono>{missed.reason}</Mono> · {missed.detail}
              </p>
            </>
          ) : (
            <p className="text-muted-foreground">No refund policy was excluded.</p>
          )}
        </div>
      </div>
      {missed?.reason === "scope_mismatch" && (
        <Explain tone="warn" testid="root-cause">
          <b>Root cause:</b> the updated policy exists, but the billing agent stored it in its private scope{" "}
          <Mono>{missed.scope}</Mono>. The support agent may only read <Mono>{scopes.join(", ")}</Mono>, so MindMesh correctly kept the
          memory out of its context, and the agent decided with the stale 14-day policy. The model did nothing wrong: it was given the
          wrong facts.
        </Explain>
      )}
      <details className="rounded-lg border p-3">
        <summary className="cursor-pointer text-xs font-medium">Show the full context receipt</summary>
        <div className="mt-3">
          <ReceiptPanel receipt={first} />
        </div>
      </details>
    </div>
  );
}

/** Step 3: preview a memory change's effect before applying it. */
function Fix({ exp }: { exp: ExperimentState }) {
  const qc = useQueryClient();
  const mem = exp.memories.current_policy!;
  const change = { scope: "project" };
  const preview = useMutation({ mutationFn: () => api.memoryImpact(mem.id, change) });
  const apply = useMutation({
    mutationFn: () =>
      api.updateMemory(mem.id, { ...change, reason: "the refund policy applies to every customer-facing agent", edited_by: "studio-user" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["experiment"] });
      qc.invalidateQueries({ queryKey: ["memories"] });
    },
  });
  if (exp.fixed)
    return (
      <Explain tone="good" testid="fix-applied">
        <b>Fixed.</b> The updated policy is now version {mem.version}, in scope <Mono>{mem.scope}</Mono>, and the stale 14-day policy is
        marked <i>superseded</i>. Nothing was deleted: both old versions remain in the{" "}
        <Link to={`/memory?focus=${mem.id}`} className="text-primary hover:underline">memory history</Link>.
      </Explain>
    );
  return (
    <div className="space-y-3">
      <p className="text-sm">
        <b>Proposed fix:</b> move the updated policy into the <Mono>project</Mono> scope, so every customer-facing agent can see it. MindMesh
        records this as a new version with the reason and editor, and supersedes older policies on the same subject.
      </p>
      <p className="text-sm text-muted-foreground">Preview what the change would do before applying it. The preview writes nothing.</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => preview.mutate()} disabled={preview.isPending} data-testid="preview-fix">
          {preview.isPending ? <Loader2 className="animate-spin" /> : <Eye />} Preview the impact
        </Button>
        <Button onClick={() => apply.mutate()} disabled={!preview.data || apply.isPending} data-testid="apply-fix"
          title={preview.data ? undefined : "Preview the impact first"}>
          <Wrench /> Apply the fix
        </Button>
      </div>
      <ErrorNote error={preview.error ?? apply.error} />
      {preview.data && (
        <div className="rounded-lg border p-3">
          <MemoryImpactView impact={preview.data} />
        </div>
      )}
    </div>
  );
}

function BeforeAfter({ cmp }: { cmp: Comparison }) {
  // each step reports its own delta: list every memory once
  const once = (ids: string[]) => [...new Set(ids)].map((m) => cmp.memories[m]).filter(Boolean);
  const added = once(cmp.steps.flatMap((s) => s.context_added));
  const removed = once(cmp.steps.flatMap((s) => s.context_removed));
  const actions = (side: "a" | "b") =>
    cmp.steps.map((s) => s[side]?.action).filter((a) => a?.type === "tool_call").map((a) => a!.tool as string);
  const sides = [
    { key: "a" as const, title: "Before the fix", s: cmp.a, tone: isApproved(cmp.a.answer) },
    { key: "b" as const, title: "After the fix", s: cmp.b, tone: isApproved(cmp.b.answer) },
  ];
  return (
    <div className="space-y-3" data-testid="before-after">
      <div className="grid items-stretch gap-3 md:grid-cols-[1fr_auto_1fr]">
        {sides.map(({ key, title, s, tone }, i) => (
          <div key={key} className="contents">
            {i === 1 && (
              <div className="hidden items-center md:flex">
                <ArrowRight className="size-6 text-muted-foreground" />
              </div>
            )}
            <div
              className={cn("space-y-2 rounded-xl border-2 p-4", tone ? "border-success/50 bg-success/5" : "border-destructive/50 bg-destructive/5")}
              data-testid={`outcome-${key}`}
            >
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="font-semibold uppercase tracking-wide text-muted-foreground">{title}</span>
                <RunModeBadge run={{ kind: s.kind, model: s.model }} className="ml-auto" />
              </div>
              <div className={cn("flex items-start gap-2 text-base font-semibold", tone ? "text-success" : "text-destructive")}>
                {tone ? <CheckCircle2 className="mt-1 size-5 shrink-0" /> : <XCircle className="mt-1 size-5 shrink-0" />}
                <span>{s.answer ?? s.error}</span>
              </div>
              <div className="text-xs text-muted-foreground">tools called: {actions(key).join(" → ") || "none"}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="space-y-1 rounded-lg border p-3 text-sm">
        <div className="font-medium">What changed, and why</div>
        <p className="text-muted-foreground">
          Same task, same model. The runs diverged at step {cmp.divergence_step ?? "?"}, and the only input that differed was the context:
        </p>
        {removed.map((m, i) => (
          <div key={`r${i}`} className="text-destructive">− {m.content} <span className="text-muted-foreground">({m.scope}, now {m.status})</span></div>
        ))}
        {added.map((m, i) => (
          <div key={`a${i}`} className="text-success" data-testid="context-added">+ {m.content} <span className="text-muted-foreground">({m.scope})</span></div>
        ))}
      </div>
      <details className="rounded-lg border p-3">
        <summary className="cursor-pointer text-xs font-medium">Step-by-step comparison</summary>
        <div className="mt-3">
          <DiffView cmp={cmp} />
        </div>
      </details>
    </div>
  );
}

function RerunAndCompare({ exp, mode }: { exp: ExperimentState; mode: Mode }) {
  const qc = useQueryClient();
  const original = exp.runs.original!;
  const rerun = exp.runs.rerun;
  const replay = exp.runs.replay;
  const refresh = () => qc.invalidateQueries({ queryKey: ["experiment"] });
  const startRerun = useMutation({ mutationFn: () => api.rerun(original.id), onSuccess: refresh });
  const startReplay = useMutation({ mutationFn: () => api.replay(original.id), onSuccess: refresh });
  const cmp = useQuery({
    queryKey: ["compare", original.id, rerun?.id],
    queryFn: () => api.compare(original.id, rerun!.id),
    enabled: isDone(rerun),
  });
  return (
    <div className="space-y-3">
      <p className="text-sm">
        Rerun the <i>same</i> task with the corrected memory. The rerun reuses the original run's configuration
        {mode === "live" ? "" : " (including the model)"}, so the only difference is the fix.
      </p>
      <Button onClick={() => startRerun.mutate()} disabled={startRerun.isPending} data-testid="rerun-original">
        <RotateCcw /> {rerun ? "Rerun again" : "Rerun the same task"}
      </Button>
      <ErrorNote error={startRerun.error ?? cmp.error} />
      {rerun && <LiveRun key={rerun.id} runId={rerun.id} title="Rerun after the fix" expect={approved} />}
      {cmp.data && <BeforeAfter cmp={cmp.data} />}
      {cmp.data && (
        <div className="space-y-2 rounded-lg border border-dashed p-3">
          <p className="text-sm">
            <b>Optional: prove the original is reproducible.</b> A <i>safe replay</i> re-executes the original run from its recording: no
            model call, no tool call, no refund issued.
          </p>
          <Button size="sm" variant="outline" onClick={() => startReplay.mutate()} disabled={startReplay.isPending} data-testid="safe-replay">
            <FlaskConical /> Safe replay of the original
          </Button>
          {replay && <LiveRun key={replay.id} runId={replay.id} title="Replay of the original" />}
          {isDone(replay) && (
            <p className="text-xs text-muted-foreground" data-testid="replay-verdict">
              {replay.answer === original.answer
                ? "The replay reproduced the original decision exactly, from recorded outputs only."
                : "The replay differs from the original: see the trace for where it diverged."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

const verb = (answer: string | null) => (answer ?? "?").split(":")[0];

/** Built from what the two runs actually did: a live model may not take the bait, and the text must say so. */
function InjectionVerdict({ p, c }: { p: ExperimentRunInfo; c: ExperimentRunInfo }) {
  const big = (r: ExperimentRunInfo) => (r.facts?.refunds ?? []).filter((x) => (x.amount ?? 0) > 500);
  const blocked = big(p).find((x) => x.status === "blocked");
  const leaked = big(p).find((x) => x.status === "ok");
  const executed = big(c).find((x) => x.status === "ok");
  const legit = (p.facts?.refunds ?? []).find((x) => x.status === "ok" && (x.amount ?? 0) <= 500);
  return (
    <Explain tone={leaked ? "bad" : "good"} testid="injection-verdict">
      <p>
        {leaked
          ? `With policies on, a $${leaked.amount} refund executed. Check the policy rules in the Control Room.`
          : blocked
            ? `With policies on, the model tried to refund $${blocked.amount}; the rule ${blocked.rule} blocked it before the tool ran${legit ? `, and the agent refunded only the legitimate $${legit.amount}` : ""}.`
            : "With policies on, the model did not attempt the injected refund this time."}{" "}
        {executed
          ? `With policies off, the same model's $${executed.amount} refund executed (in the simulated ledger).`
          : "With policies off, the model did not attempt it this time either: live models vary between runs."}
      </p>
      <p className="mt-1">
        {blocked || executed
          ? "Same model, same attack: the difference is a rule enforced in code, outside the model, which a persuasive prompt cannot talk its way past."
          : "That is luck, not safety: the policy rule is what guarantees the outcome on every run."}
      </p>
    </Explain>
  );
}

function FaultsVerdict({ p, c }: { p: ExperimentRunInfo; c: ExperimentRunInfo }) {
  return (
    <Explain tone={isApproved(p.answer) ? "good" : "warn"} testid="faults-verdict">
      With retries, the agent absorbed {p.facts?.injected_faults ?? 0} injected failures ({p.facts?.retries ?? 0} retries) and answered{" "}
      <b>{verb(p.answer)}</b>. Without retries, the first injected failure ended the lookup and the agent answered <b>{verb(c.answer)}</b>
      {isApproved(c.answer) ? "." : ": a safe outcome, but a customer left waiting for an outage that lasted two requests."} Each failure is
      labelled as an injected fault in the trace.
    </Explain>
  );
}

function PairedTest({
  exp,
  scenario,
  mode,
  protectedTitle,
  controlTitle,
  button,
  disabled,
  verdict,
}: {
  exp: ExperimentState;
  scenario: "injection" | "faults";
  mode: Mode;
  protectedTitle: string;
  controlTitle: string;
  button: string;
  disabled?: boolean;
  verdict: (p: ExperimentRunInfo, c: ExperimentRunInfo) => ReactNode;
}) {
  const qc = useQueryClient();
  const start = useMutation({
    mutationFn: () =>
      Promise.all([
        api.startExperiment(scenario, { protected: true, mode }),
        api.startExperiment(scenario, { protected: false, mode }),
      ]),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["experiment"] }),
  });
  const p = exp.runs[scenario];
  const c = exp.runs[`${scenario}:unprotected`];
  return (
    <div className="space-y-3">
      <Button onClick={() => start.mutate()} disabled={disabled || start.isPending} data-testid={`run-${scenario}`}>
        <Zap /> {p ? "Run again" : button}
      </Button>
      <ErrorNote error={start.error} />
      {(p || c) && (
        <div className="grid gap-3 lg:grid-cols-2">
          {p && <LiveRun key={p.id} runId={p.id} title={protectedTitle} />}
          {c && <LiveRun key={c.id} runId={c.id} title={controlTitle} />}
        </div>
      )}
      {isDone(p) && isDone(c) && p.facts && c.facts && verdict(p, c)}
    </div>
  );
}

function StressTests({ exp, mode }: { exp: ExperimentState; mode: Mode }) {
  const impact = useMutation({ mutationFn: () => api.policyImpact({ disable: ["block-large-refunds"] }) });
  const attack = exp.scenarios.injection.attack;
  return (
    <div className="space-y-5">
      <div className="space-y-2" data-testid="injection-test">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold"><ShieldAlert className="size-4 text-destructive" /> Prompt injection</h3>
        <p className="text-sm">
          A customer's order notes contain a hidden instruction. The demo model is deliberately gullible: it follows instructions it finds in
          data, as weakly aligned models do (a live model may or may not). Two runs: one with MindMesh's policies enforced, one control run
          with policies switched off.
        </p>
        <blockquote className="rounded-md border-l-4 border-destructive/60 bg-muted/40 px-3 py-2 font-mono text-xs">{attack}</blockquote>
        <PairedTest
          exp={exp}
          scenario="injection"
          mode={mode}
          button="Run the attack"
          protectedTitle="With MindMesh policies"
          controlTitle="Control: policies off"
          verdict={(p, c) => <InjectionVerdict p={p} c={c} />}
        />
        {exp.runs.injection && (
          <div className="space-y-2 rounded-lg border border-dashed p-3">
            <p className="text-sm">
              <b>Explain a policy change before making it:</b> what would happen if someone disabled <Mono>block-large-refunds</Mono>?
              MindMesh re-evaluates every recorded tool call against the proposed rules. Nothing is saved.
            </p>
            <Button size="sm" variant="outline" onClick={() => impact.mutate()} disabled={impact.isPending} data-testid="preview-policy">
              <Eye /> Preview disabling the rule
            </Button>
            <ErrorNote error={impact.error} />
            {impact.data && <PolicyImpactView impact={impact.data} />}
          </div>
        )}
      </div>

      <div className="space-y-2" data-testid="faults-test">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold"><Zap className="size-4 text-warning" /> Failure injection</h3>
        <p className="text-sm">
          MindMesh makes the CRM's first two lookups fail with a 503 for this run only. The fault is injected before the tool runs, so nothing
          is left half-done. One run with MindMesh's bounded retries, one control run with retries switched off.
        </p>
        <PairedTest
          exp={exp}
          scenario="faults"
          mode={mode}
          button="Run the outage"
          protectedTitle="With retries"
          controlTitle="Control: no retries"
          disabled={!exp.fixed}
          verdict={(p, c) => <FaultsVerdict p={p} c={c} />}
        />
        {!exp.fixed && <p className="text-xs text-muted-foreground">Apply the fix first: this premium customer's refund depends on the 30-day policy.</p>}
      </div>
    </div>
  );
}

/** Step 6: the reproducible benchmark, presented as a reliability scorecard. */
function Measure({ mode, live }: { mode: Mode; live: string | null }) {
  const qc = useQueryClient();
  const evals = useQuery({ queryKey: ["evals", SUITE], queryFn: () => api.evals(SUITE) });
  const [job, setJob] = useState<string | null>(null);
  const jobQ = useQuery({
    queryKey: ["evaljob", job],
    queryFn: () => api.evalJob(job!),
    enabled: !!job,
    refetchInterval: (q) => (q.state.data?.status === "running" ? 700 : false),
  });
  useEffect(() => {
    if (jobQ.data && jobQ.data.status !== "running") qc.invalidateQueries({ queryKey: ["evals"] });
  }, [jobQ.data, qc]);
  const start = useMutation({
    mutationFn: () => api.startEval(SUITE, VARIANTS, mode === "live" ? (live ?? undefined) : undefined),
    onSuccess: (j) => setJob(j.id),
  });
  const latest = useMemo(() => {
    const m = new Map<string, EvalRun>();
    for (const e of evals.data ?? []) if (!m.has(e.variant)) m.set(e.variant, e);
    return VARIANTS.map((v) => m.get(v)).filter(Boolean) as EvalRun[];
  }, [evals.data]);
  const running = start.isPending || jobQ.data?.status === "running";
  const [baseline, before, after] = VARIANTS.map((v) => latest.find((r) => r.variant === v));
  return (
    <div className="space-y-3">
      <p className="text-sm">
        One good run is an anecdote. The benchmark runs <b>7 refund tasks</b> (including the injection and the outage) against three
        configurations, each task in a fresh, isolated database, and scores them on the same checks.
      </p>
      <Button onClick={() => start.mutate()} disabled={running} data-testid="run-scorecard">
        {running ? <Loader2 className="animate-spin" /> : <Play />} {running ? "Measuring…" : latest.length ? "Measure again" : "Run the benchmark"}
      </Button>
      {mode === "live" && <p className="text-xs text-muted-foreground">With a live model this runs 21 agent runs and can take several minutes.</p>}
      <ErrorNote error={start.error ?? jobQ.data?.error} />
      {latest.length === VARIANTS.length && (
        <>
          <Scorecard runs={latest} />
          <p className="text-[11px] text-muted-foreground">
            Measured {timeAgo(latest[2].created_at)} with the {latest[2].model === "scripted" ? "demo (scripted) model" : `live model ${latest[2].model}`} ·{" "}
            {latest[2].metrics.tasks} tasks per configuration · details in the{" "}
            <Link to="/replay" className="text-primary hover:underline">Replay Lab</Link>.
          </p>
          {baseline && before && after && (
            <Explain tone="good" testid="improvement">
              <div className="mb-1 font-semibold">The measured improvement</div>
              <ul className="list-disc space-y-0.5 pl-5">
                {improvementSummary(baseline.metrics, before.metrics, after.metrics).map((s) => <li key={s}>{s}</li>)}
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">
                Columns: {VARIANTS.map((v) => `“${VARIANT_TEXT[v].title}”: ${VARIANT_TEXT[v].help}`).join(" ")}
              </p>
            </Explain>
          )}
        </>
      )}
    </div>
  );
}

export default function Experiment() {
  const qc = useQueryClient();
  const exp = useQuery({ queryKey: ["experiment"], queryFn: api.experiment, refetchInterval: 1500 });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const [mode, setMode] = useState<Mode>("demo");
  const live = me.data?.live_model ?? null;
  const readOnly = me.data?.role === "read";
  const refresh = () => qc.invalidateQueries({ queryKey: ["experiment"] });
  const reset = useMutation({ mutationFn: api.resetExperiment, onSuccess: refresh });
  const start = useMutation({
    mutationFn: async () => {
      await api.resetExperiment(); // always start from the known failing state
      return api.startExperiment("original", { mode });
    },
    onSuccess: refresh,
  });
  const d = exp.data;
  const evals = useQuery({ queryKey: ["evals", SUITE], queryFn: () => api.evals(SUITE) });

  if (!d) return <div className="mx-auto max-w-5xl"><ErrorNote error={exp.error} /><Card className="h-64 animate-pulse" /></div>;
  const original = d.runs.original;
  const failed = isDone(original) && !isApproved(original.answer);
  const rerunOk = isDone(d.runs.rerun) && isApproved(d.runs.rerun.answer);
  const stressDone = isDone(d.runs.injection) && isDone(d.runs.faults);
  const measured = (evals.data ?? []).some((e) => d.seeded_at && e.created_at >= d.seeded_at);
  const steps = [
    { id: "run", label: "Run", done: isDone(original) },
    { id: "diagnose", label: "Diagnose", done: d.fixed },
    { id: "fix", label: "Fix", done: d.fixed },
    { id: "compare", label: "Compare", done: rerunOk },
    { id: "stress", label: "Stress-test", done: stressDone },
    { id: "measure", label: "Measure", done: measured },
  ];

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 rounded-lg bg-primary/12 p-2 text-primary"><Sparkles className="size-5" /></div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Guided experiment</h1>
            <p className="text-sm text-muted-foreground">Watch an agent fail, find out why, fix it, and measure the improvement. About five minutes.</p>
          </div>
        </div>
        <div className="flex flex-wrap items-start gap-2">
          <ModePicker mode={mode} setMode={setMode} live={live} />
          {d.seeded && (
            <Button variant="ghost" size="sm" onClick={() => reset.mutate()} disabled={reset.isPending || readOnly}
              title="Restore the scenario's failing state. Only the scenario's own memories and rules are touched." data-testid="reset-experiment">
              <RotateCcw /> Start over
            </Button>
          )}
        </div>
      </div>
      <Stepper steps={steps} />
      <ErrorNote error={reset.error} />

      <Step n={1} id="run" title="Run the agent" done={isDone(original)}>
        <p className="text-sm">
          A support agent decides refund requests. Last week the refund policy changed: <b>premium customers now get 30 days</b> instead of
          14. Dana Ruiz, a premium customer, asks for a refund on order A-7731 ($79), delivered 21 days ago. The correct answer is to
          approve it.
        </p>
        <p className="text-xs text-muted-foreground">
          Everything runs in a sandbox: the CRM, orders and refund tools are simulated and no money moves. Each run is labelled{" "}
          <Badge variant="info"><Bot /> Demo</Badge>, <Badge variant="default"><Cpu /> Live model</Badge> or{" "}
          <Badge variant="warning">Replay</Badge> so you always know what produced a result.
        </p>
        {!original ? (
          <div className="space-y-1.5">
            <Button size="lg" onClick={() => start.mutate()} disabled={start.isPending || readOnly} data-testid="run-experiment">
              {start.isPending ? <Loader2 className="animate-spin" /> : <Play />} Run experiment
            </Button>
            {readOnly && (
              <p className="text-xs text-muted-foreground" data-testid="read-only-experiment">
                Running experiments needs a developer key. In this public demo, explore the recorded runs in Execution Studio and
                Replay Lab.
              </p>
            )}
          </div>
        ) : (
          <LiveRun key={original.id} runId={original.id} title="Dana's refund request" expect={approved} />
        )}
        <ErrorNote error={start.error} />
        {failed && (
          <Explain tone="bad" testid="failure-verdict">
            <b>The agent got it wrong.</b> It answered {verb(original.answer ?? original.error)} for a refund the current policy allows. In
            production this is a customer complaint. Next: find out why.
          </Explain>
        )}
        {isDone(original) && !failed && (
          <Explain tone="warn">
            This run was approved, so there is no failure to diagnose. That happens when the fix is already applied or a live model
            behaved differently: use <b>Start over</b> to restore the failing state.
          </Explain>
        )}
      </Step>

      <Step n={2} id="diagnose" title="Find the cause" done={d.fixed} locked={!failed} lockedText="Run the agent first.">
        {original && <Diagnosis runId={original.id} />}
      </Step>

      <Step n={3} id="fix" title="Fix it, and see the impact before you do" done={d.fixed} locked={!failed && !d.fixed}
        lockedText="Diagnose the failure first.">
        {d.memories.current_policy && <Fix exp={d} />}
      </Step>

      <Step n={4} id="compare" title="Rerun and compare before / after" done={rerunOk} locked={!d.fixed || !original}
        lockedText="Apply the fix first.">
        {original && <RerunAndCompare exp={d} mode={mode} />}
      </Step>

      <Step n={5} id="stress" title="Stress-test: attacks and outages" done={stressDone} locked={!original} lockedText="Run the agent first.">
        <StressTests exp={d} mode={mode} />
      </Step>

      <Step n={6} id="measure" title="Measure: reliability scorecard" done={measured} locked={!original} lockedText="Run the agent first.">
        <Measure mode={mode} live={live} />
      </Step>

      {steps.every((s) => s.done) && (
        <Card className="border-success/40">
          <CardContent className="space-y-2 pt-4 text-sm" data-testid="experiment-summary">
            <div className="flex items-center gap-2 font-semibold"><CheckCircle2 className="size-5 text-success" /> What you just showed</div>
            <ul className="list-disc space-y-1 pl-5">
              <li>The agent failed because of <b>what it was shown</b>, not how it reasoned: the context receipt proved the current policy was out of scope.</li>
              <li>
                A one-field memory fix, previewed before it was applied, changed the outcome from {verb(original?.answer ?? null)} to{" "}
                {verb(d.runs.rerun?.answer ?? null)} with the same model and task.
              </li>
              <li>Safety and resilience come from code outside the model: policy rules decide what a prompt injection can reach, and retries absorb injected outages.</li>
              <li>The scorecard measures all of it on the same 7 tasks, reproducibly.</li>
            </ul>
            <div className="flex flex-wrap gap-2 pt-1">
              <Button size="sm" variant="outline" asChild><Link to="/runs"><ArrowRight /> Explore every trace</Link></Button>
              <Button size="sm" variant="outline" asChild><Link to="/control"><ArrowRight /> Edit policies</Link></Button>
              <Button size="sm" variant="outline" asChild><Link to="/memory"><ArrowRight /> Browse memory</Link></Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
