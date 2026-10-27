import { Link } from "react-router-dom";
import { ArrowRight, GitBranch, Minus, Plus } from "lucide-react";
import type { CompareStepSide, Comparison, RunSummary } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Mono, StatusBadge } from "@/components/common";
import { RunModeBadge } from "@/components/LiveRun";
import { cn, fmtMs, fmtNum, shortId } from "@/lib/utils";

function describe(side: CompareStepSide | undefined): string {
  const a = side?.action;
  if (!a) return "—";
  if (a.type === "final_answer") return `final: ${a.answer ?? ""}`;
  return `${a.tool}(${Object.values(a.args ?? {}).map((v) => JSON.stringify(v)).join(", ")})`;
}

function Summary({ s, label }: { s: RunSummary; label: string }) {
  const good = s.answer?.startsWith("APPROVED") || s.answer?.startsWith("APPROVE") || s.status === "succeeded";
  return (
    <Card className="flex-1 p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="outline">{label}</Badge>
        <Link to={`/runs/${s.id}`} className="font-mono text-primary hover:underline">{shortId(s.id)}</Link>
        <RunModeBadge run={{ kind: s.kind, model: s.model }} />
        <StatusBadge status={s.status} className="ml-auto" />
      </div>
      <p className={cn("mt-2 text-sm font-medium", !s.error && good ? "" : "text-destructive")} data-testid={`answer-${label}`}>
        {s.answer ?? s.error ?? "—"}
      </p>
      <div className="mt-2 grid grid-cols-4 gap-2 text-[11px] text-muted-foreground">
        <span>{s.steps} steps</span>
        <span>{s.tool_calls} tools</span>
        <span>{fmtNum(s.tokens)} tok</span>
        <span>{fmtMs(s.duration_ms)}</span>
      </div>
      {s.model && <div className="mt-1 text-[10.5px] text-muted-foreground">model {s.model}</div>}
    </Card>
  );
}

export function DiffView({ cmp }: { cmp: Comparison }) {
  return (
    <div className="space-y-3" data-testid="diff-view">
      <div className="flex flex-col gap-3 md:flex-row md:items-stretch">
        <Summary s={cmp.a} label="A" />
        <div className="hidden items-center md:flex"><ArrowRight className="size-5 text-muted-foreground" /></div>
        <Summary s={cmp.b} label="B" />
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {cmp.identical ? (
          <Badge variant="success">identical behaviour</Badge>
        ) : (
          <Badge variant="warning" data-testid="divergence">
            <GitBranch /> diverged at step {cmp.divergence_step ?? "?"}
          </Badge>
        )}
        {cmp.delta.status_changed && <Badge variant="info">status changed</Badge>}
        <span className="text-muted-foreground">
          Δ steps {cmp.delta.steps >= 0 ? "+" : ""}{cmp.delta.steps} · Δ tool calls {cmp.delta.tool_calls >= 0 ? "+" : ""}{cmp.delta.tool_calls} · Δ tokens{" "}
          {cmp.delta.tokens >= 0 ? "+" : ""}{fmtNum(cmp.delta.tokens)}
        </span>
      </div>
      <div className="overflow-hidden rounded-lg border">
        <div className="grid grid-cols-[48px_1fr_1fr] bg-muted/50 text-[11px] font-medium text-muted-foreground">
          <div className="px-2 py-1.5">step</div>
          <div className="px-2 py-1.5">A</div>
          <div className="px-2 py-1.5">B</div>
        </div>
        {cmp.steps.map((s) => (
          <div
            key={s.step}
            className={cn("border-t", s.step === cmp.divergence_step && "bg-warning/8")}
            data-testid={`diff-step-${s.step}`}
          >
            <div className="grid grid-cols-[48px_1fr_1fr] text-xs">
              <div className="px-2 py-2 font-mono text-muted-foreground">
                {s.step}
                {s.step === cmp.divergence_step && <span className="block text-[9px] text-warning">diverge</span>}
              </div>
              {[s.a, s.b].map((side, i) => (
                <div key={i} className={cn("px-2 py-2", !s.same_action && "font-medium")}>
                  <div className="break-words">{describe(side)}</div>
                  {side.outcome && side.outcome.status !== "final" && (
                    <div className="mt-0.5 flex items-center gap-1"><StatusBadge status={side.outcome.status} />{side.outcome.policy && side.outcome.policy.effect !== "allow" && <span className="text-[10.5px] text-muted-foreground">{side.outcome.policy.rule_name}</span>}</div>
                  )}
                </div>
              ))}
            </div>
            {(s.context_added.length > 0 || s.context_removed.length > 0) && (
              <div className="space-y-1 border-t border-dashed bg-muted/20 px-2 py-1.5 pl-[56px] text-[11px]">
                <div className="text-muted-foreground">context delta (A → B):</div>
                {s.context_removed.map((m) => (
                  <div key={m} className="flex items-start gap-1.5 text-destructive">
                    <Minus className="mt-0.5 size-3 shrink-0" />
                    <span><Mono>{cmp.memories[m]?.subject_key ?? m}</Mono> {cmp.memories[m]?.content ?? ""}</span>
                  </div>
                ))}
                {s.context_added.map((m) => (
                  <div key={m} className="flex items-start gap-1.5 text-success" data-testid="context-added">
                    <Plus className="mt-0.5 size-3 shrink-0" />
                    <span><Mono>{cmp.memories[m]?.subject_key ?? m}</Mono> {cmp.memories[m]?.content ?? ""}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
