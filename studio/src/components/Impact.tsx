import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Eye, EyeOff, GitBranch, Minus, Plus } from "lucide-react";
import type { MemoryImpact, PolicyImpact } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Mono, StatusBadge } from "@/components/common";
import { REASON_TEXT } from "@/components/ReceiptPanel";
import { shortId } from "@/lib/utils";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-1.5">
      <h4 className="text-xs font-semibold">{title}</h4>
      {children}
    </section>
  );
}

const show = (v: unknown) => (typeof v === "number" ? v.toFixed(2) : String(v));

/** What a memory edit will do, computed by a dry run before anything is written. */
export function MemoryImpactView({ impact }: { impact: MemoryImpact }) {
  const gains = impact.visibility.filter((a) => !a.before && a.after);
  const loses = impact.visibility.filter((a) => a.before && !a.after);
  const others = impact.supersedes.filter((m) => m.id !== impact.memory.id);
  return (
    <div className="space-y-3 text-xs" data-testid="memory-impact">
      <Section title={`The change (saved as v${impact.new_version}; v${impact.memory.version} stays in history)`}>
        {Object.entries(impact.changes).map(([field, { before, after }]) => (
          <div key={field} className="flex flex-wrap items-center gap-1.5">
            <span className="w-20 text-muted-foreground">{field}</span>
            <Mono className="rounded bg-destructive/10 px-1 text-destructive line-through">{show(before)}</Mono>
            <ArrowRight className="size-3 text-muted-foreground" />
            <Mono className="rounded bg-success/10 px-1 text-success">{show(after)}</Mono>
          </div>
        ))}
        {Object.keys(impact.changes).length === 0 && <p className="text-muted-foreground">No field changes.</p>}
      </Section>

      <Section title="Who can see it">
        <ul className="space-y-1">
          {impact.visibility.map((a) => (
            <li key={a.agent} className="flex flex-wrap items-center gap-1.5">
              {a.after ? <Eye className="size-3.5 text-success" /> : <EyeOff className="size-3.5 text-muted-foreground" />}
              <span className="font-medium">{a.agent}</span>
              <span className="text-muted-foreground">reads {a.scopes.join(", ")}</span>
              {a.before !== a.after && (
                <Badge variant={a.after ? "success" : "destructive"}>{a.after ? "gains access" : "loses access"}</Badge>
              )}
            </li>
          ))}
        </ul>
        {gains.length === 0 && loses.length === 0 && <p className="text-muted-foreground">No agent's visibility changes.</p>}
      </Section>

      {others.length > 0 && (
        <Section title="Memories this version replaces">
          {others.map((m) => (
            <div key={m.id} className="rounded-md border border-dashed p-2">
              <div className="flex items-center gap-1.5">
                <GitBranch className="size-3.5 text-muted-foreground" />
                <Mono>{m.subject_key}</Mono> <Badge variant="outline">{m.scope}</Badge> <Badge variant="outline">v{m.version}</Badge>
                <span className="ml-auto text-muted-foreground">becomes superseded</span>
              </div>
              <p className="mt-1">{m.content}</p>
            </div>
          ))}
        </Section>
      )}

      <Section title={`Context impact on ${impact.runs.length} run${impact.runs.length === 1 ? "" : "s"} that retrieved it`}>
        {impact.runs.length === 0 && <p className="text-muted-foreground">No recorded run retrieved this memory yet.</p>}
        {impact.runs.map((r) => (
          <div key={r.run_id} className="space-y-1 rounded-md border p-2" data-testid="impact-run">
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
              <Link to={`/runs/${r.run_id}`} className="font-mono text-primary hover:underline">{shortId(r.run_id)}</Link>
              <span>{r.agent} · {r.kind}</span>
              <span className="truncate">answered: {r.answer ?? "–"}</span>
            </div>
            {r.newly_included.map((i) => (
              <div key={i.item_id} className="flex items-start gap-1.5 text-success" data-testid="impact-included">
                <Plus className="mt-0.5 size-3 shrink-0" />
                <span>would now be in context: {i.content}</span>
              </div>
            ))}
            {r.newly_excluded.map((i) => (
              <div key={i.item_id} className="flex items-start gap-1.5 text-destructive" data-testid="impact-excluded">
                <Minus className="mt-0.5 size-3 shrink-0" />
                <span>
                  would leave context: {i.content}
                  {i.reason && <span className="text-muted-foreground"> ({REASON_TEXT[i.reason] ?? i.reason})</span>}
                </span>
              </div>
            ))}
            {r.newly_included.length + r.newly_excluded.length === 0 && (
              <div className="text-muted-foreground">This run's context would not change.</div>
            )}
          </div>
        ))}
      </Section>
    </div>
  );
}

const EFFECT_TEXT: Record<string, string> = { allow: "allowed", deny: "blocked", require_approval: "needs approval" };

/** What a policy change will do: the rule diff, and which recorded tool calls would be decided differently. */
export function PolicyImpactView({ impact }: { impact: PolicyImpact }) {
  return (
    <div className="space-y-3 text-xs" data-testid="policy-impact">
      <Section title="Rule changes">
        {impact.rules.length === 0 && <p className="text-muted-foreground">The rules are unchanged.</p>}
        {impact.rules.map((r) => (
          <div key={r.rule} className="flex flex-wrap items-center gap-1.5">
            <Badge variant={r.change === "added" ? "success" : r.change === "removed" ? "destructive" : "warning"}>{r.change}</Badge>
            <Mono>{r.rule}</Mono>
            {r.fields?.map((f) => (
              <span key={f} className="text-muted-foreground">
                {f}: {JSON.stringify(r.before?.[f])} → {JSON.stringify(r.after?.[f])}
              </span>
            ))}
          </div>
        ))}
      </Section>
      <Section title="Effect on recorded tool calls">
        <p>
          <b>{impact.changed}</b> of {impact.evaluated} recorded decisions would change
          {Object.entries(impact.transitions).map(([t, n]) => {
            const [a, b] = t.split("->");
            return <span key={t}> · {n}× {EFFECT_TEXT[a] ?? a} → {EFFECT_TEXT[b] ?? b}</span>;
          })}
        </p>
        {impact.changes.map((c, i) => (
          <div key={i} className="space-y-1 rounded-md border p-2" data-testid="policy-flip">
            <div className="flex flex-wrap items-center gap-1.5">
              <Mono>{c.tool}({Object.entries(c.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})</Mono>
              <Link to={`/runs/${c.run_id}`} className="ml-auto font-mono text-[11px] text-primary hover:underline">
                {shortId(c.run_id)} · step {c.step}
              </Link>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <StatusBadge status={c.before.effect} />
              <span className="text-muted-foreground">{c.before.rule_name ?? c.before.reason}</span>
              <ArrowRight className="size-3 text-muted-foreground" />
              <StatusBadge status={c.after.effect} />
              <span className="text-muted-foreground">{c.after.rule_name ?? c.after.reason}</span>
            </div>
          </div>
        ))}
        <p className="text-[11px] text-muted-foreground">{impact.note}</p>
      </Section>
    </div>
  );
}
