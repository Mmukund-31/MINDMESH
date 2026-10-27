import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronRight,
  Eye,
  FileCode2,
  Gavel,
  Grid3x3,
  History,
  Minus,
  PauseCircle,
  Plus,
  ShieldBan,
  ShieldCheck,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import type { AgentSpec, AuditEntry, PolicyRule, ToolInfo } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, ErrorNote, IdChip, Json, Metric, PageHeader, Panel, StatusBadge, StatusDot } from "@/components/common";
import { PolicyImpactView } from "@/components/Impact";
import { cn, shortId, timeAgo } from "@/lib/utils";

const EFFECT_VARIANT = { allow: "success", deny: "destructive", require_approval: "warning" } as const;

function glob(value: string, patterns: string[]) {
  return (patterns.length ? patterns : ["*"]).some((p) =>
    new RegExp(`^${p.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".")}$`).test(value),
  );
}

function Approvals() {
  const qc = useQueryClient();
  const all = useQuery({ queryKey: ["approvals", "all"], queryFn: () => api.approvals(), refetchInterval: 3000 });
  const [notes, setNotes] = useState<Record<string, string>>({});
  const resolve = useMutation({
    mutationFn: ({ id, ok }: { id: string; ok: boolean }) => api.resolveApproval(id, ok, notes[id]),
    onSuccess: () => {
      for (const k of ["approvals", "runs", "audit", "overview"]) qc.invalidateQueries({ queryKey: [k] });
    },
  });
  const pending = (all.data ?? []).filter((a) => a.status === "pending");
  const done = (all.data ?? []).filter((a) => a.status !== "pending");
  return (
    <div className="space-y-3">
      <ErrorNote error={resolve.error} />
      <Panel title={`Waiting for a decision · ${pending.length}`} icon={PauseCircle}
        description="Tool calls matching a require_approval rule pause their run here until a human decides. Approving resumes the run.">
        {pending.length === 0 ? (
          <div className="px-3 py-6 text-xs text-muted-foreground">No pending approvals.</div>
        ) : (
          <ul className="divide-y">
            {pending.map((a) => (
              <li key={a.id} className="grid gap-2 px-3 py-2.5 lg:grid-cols-[minmax(0,1fr)_auto]" data-testid="approval-card">
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <StatusDot status="waiting_approval" />
                    <span className="font-mono text-[13px] font-medium">{a.tool}</span>
                    <span className="text-muted-foreground">
                      run <Link className="text-primary hover:underline" to={`/runs/${a.run_id}`}>{shortId(a.run_id)}</Link> · step {a.step} · {timeAgo(a.requested_at)}
                    </span>
                  </div>
                  <code className="block truncate rounded-sm bg-background/60 px-2 py-1 font-mono text-[11px]" title={JSON.stringify(a.args)}>{JSON.stringify(a.args)}</code>
                  <p className="text-xs text-muted-foreground">Why: {a.reason}</p>
                </div>
                <div className="flex items-center gap-1.5 self-end lg:self-center">
                  <Input placeholder="Note (optional)" value={notes[a.id] ?? ""} onChange={(e) => setNotes({ ...notes, [a.id]: e.target.value })} className="h-7 w-44 text-xs" />
                  <Button size="sm" variant="ghost" className="text-destructive" onClick={() => resolve.mutate({ id: a.id, ok: false })}><X /> Reject</Button>
                  <Button size="sm" variant="success" onClick={() => resolve.mutate({ id: a.id, ok: true })} data-testid="approve-card"><Check /> Approve & resume</Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      {done.length > 0 && (
        <Panel title="Decision history" icon={History}>
          <ul className="divide-y">
            {done.map((a) => (
              <li key={a.id} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-3 py-1.5 text-xs">
                <StatusBadge status={a.status} />
                <span className="min-w-0 truncate">
                  <span className="font-mono">{a.tool}</span> <span className="font-mono text-muted-foreground">{JSON.stringify(a.args)}</span>
                  <span className="text-muted-foreground"> · by {a.resolver}{a.note ? ` — ${a.note}` : ""}</span>
                </span>
                <span className="flex items-center gap-2 text-muted-foreground">
                  <Link className="font-mono text-[11px] text-primary hover:underline" to={`/runs/${a.run_id}`}>{shortId(a.run_id)}</Link>
                  {timeAgo(a.resolved_at)}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}

function RuleRow({ rule, hits }: { rule: PolicyRule; hits: number }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const refresh = () => {
    for (const k of ["policies", "audit"]) qc.invalidateQueries({ queryKey: [k] });
  };
  const toggle = useMutation({
    onError: (e) => alert(`Could not update rule: ${e instanceof Error ? e.message : e}`),
    mutationFn: () => {
      // Send only the editable fields: the API rejects read-only ones (id, project_id, created_at).
      const { name, description, effect, tools, roles, agents, conditions, priority, max_calls_per_run } = rule;
      return api.updatePolicy(rule.id, { name, description, effect, tools, roles, agents, conditions, priority, max_calls_per_run, enabled: !rule.enabled });
    },
    onSuccess: refresh,
  });
  const del = useMutation({ mutationFn: () => api.deletePolicy(rule.id), onSuccess: refresh });
  const scope = [
    rule.tools.join(", "),
    rule.agents.join() !== "*" ? `agents ${rule.agents.join(", ")}` : null,
    rule.roles.join() !== "*" ? `roles ${rule.roles.join(", ")}` : null,
  ].filter(Boolean).join(" · ");
  const when = [
    ...rule.conditions.map((c) => `${c.arg} ${c.op} ${JSON.stringify(c.value)}`),
    ...(rule.max_calls_per_run !== null ? [`after ${rule.max_calls_per_run} call(s)/run`] : []),
  ].join(" and ");
  return (
    <li className={cn(!rule.enabled && "opacity-50")} data-testid="policy-rule">
      <div className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-2 px-3 py-1.5">
        <span className="font-mono text-[11px] text-muted-foreground tabular-nums" title="priority (lower is evaluated first)">{rule.priority}</span>
        <button className="flex min-w-0 items-center gap-2 text-left" onClick={() => setOpen(!open)}>
          <ChevronRight className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
          <Badge variant={EFFECT_VARIANT[rule.effect]} className="w-[88px] justify-center">{rule.effect.replace("_", " ")}</Badge>
          <span className="min-w-0">
            <span className="block truncate font-mono text-xs font-medium">{rule.name}</span>
            <span className="block truncate text-[11px] text-muted-foreground">
              {scope}{when ? <> · when <span className="text-foreground/80">{when}</span></> : null}
            </span>
          </span>
        </button>
        <span className="flex items-center gap-1">
          <span className="w-16 text-right text-[11px] text-muted-foreground tabular-nums" title="recorded decisions made by this rule">{hits ? `${hits} hit${hits === 1 ? "" : "s"}` : ""}</span>
          <Button size="sm" variant="ghost" className="h-6 px-2" onClick={() => toggle.mutate()}>{rule.enabled ? "Disable" : "Enable"}</Button>
          <Button size="icon" variant="ghost" className="size-6" onClick={() => confirm(`Delete rule "${rule.name}"?`) && del.mutate()} aria-label={`Delete rule ${rule.name}`}><Trash2 /></Button>
        </span>
      </div>
      {open && (
        <div className="space-y-1 border-t bg-background/40 px-3 py-2 pl-12 text-xs">
          {rule.description && <p>{rule.description}</p>}
          <Json value={{ tools: rule.tools, agents: rule.agents, roles: rule.roles, conditions: rule.conditions, max_calls_per_run: rule.max_calls_per_run }} className="max-h-40" />
          <p className="text-[11px] text-muted-foreground">created {timeAgo(rule.created_at)} · <IdChip id={rule.id} /></p>
        </div>
      )}
    </li>
  );
}

function NewRule({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [effect, setEffect] = useState("deny");
  const [tools, setTools] = useState("*");
  const [arg, setArg] = useState("");
  const [op, setOp] = useState("gt");
  const [value, setValue] = useState("");
  const [priority, setPriority] = useState(50);
  const m = useMutation({
    mutationFn: () =>
      api.createPolicy({
        name, effect, priority, tools: tools.split(",").map((t) => t.trim()).filter(Boolean),
        conditions: arg ? [{ arg, op, value: isNaN(Number(value)) ? value : Number(value) }] : [],
      }),
    onSuccess: () => {
      for (const k of ["policies", "audit"]) qc.invalidateQueries({ queryKey: [k] });
      onDone();
    },
  });
  return (
    <div className="grid gap-2 border-t p-3 sm:grid-cols-2">
      <div className="space-y-1"><Label>Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="block-large-payouts" /></div>
      <div className="space-y-1"><Label>Effect</Label>
        <Select value={effect} onChange={(e) => setEffect(e.target.value)} className="w-full">
          <option value="deny">deny</option><option value="require_approval">require_approval</option><option value="allow">allow</option>
        </Select>
      </div>
      <div className="space-y-1"><Label>Tools (globs, comma separated)</Label><Input value={tools} onChange={(e) => setTools(e.target.value)} /></div>
      <div className="space-y-1"><Label>Priority (lower is evaluated first)</Label><Input type="number" value={priority} onChange={(e) => setPriority(Number(e.target.value))} /></div>
      <div className="space-y-1 sm:col-span-2"><Label>Condition (optional)</Label>
        <div className="flex gap-2">
          <Input value={arg} onChange={(e) => setArg(e.target.value)} placeholder="arg (e.g. amount)" />
          <Select value={op} onChange={(e) => setOp(e.target.value)}>
            {["eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in", "regex", "path_prefix", "not_path_prefix"].map((o) => <option key={o}>{o}</option>)}
          </Select>
          <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="value" />
        </div>
      </div>
      <ErrorNote error={m.error} />
      <div className="flex justify-end gap-1.5 sm:col-span-2">
        <Button size="sm" variant="ghost" onClick={onDone}>Cancel</Button>
        <Button size="sm" disabled={!name || m.isPending} onClick={() => m.mutate()}>Add rule</Button>
      </div>
    </div>
  );
}

function YamlEditor() {
  const qc = useQueryClient();
  const y = useQuery({ queryKey: ["policies", "yaml"], queryFn: api.policiesYaml });
  const [text, setText] = useState("");
  useEffect(() => { if (y.data) setText(y.data.yaml); }, [y.data]);
  const preview = useMutation({ mutationFn: () => api.policyImpact({ yaml: text }) });
  const save = useMutation({
    mutationFn: () => api.putPoliciesYaml(text),
    onSuccess: () => {
      for (const k of ["policies", "audit"]) qc.invalidateQueries({ queryKey: [k] });
      preview.reset();
    },
  });
  return (
    <Panel title="Policy as code" icon={FileCode2} description="Replace all rules atomically, validated server-side. Preview re-evaluates recorded tool calls first.">
      <div className="space-y-2 p-3">
        <Textarea value={text} onChange={(e) => { setText(e.target.value); preview.reset(); }} rows={16} className="font-mono text-[11px] leading-relaxed" spellCheck={false} />
        <ErrorNote error={save.error ?? preview.error} />
        {preview.data && <div className="rounded-md border p-2.5"><PolicyImpactView impact={preview.data} /></div>}
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="outline" onClick={() => preview.mutate()} disabled={preview.isPending} data-testid="preview-yaml"
            title="Diff the rules and re-evaluate recorded tool calls against them. Nothing is saved.">
            <Eye /> Preview impact
          </Button>
          <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>Apply YAML</Button>
        </div>
      </div>
    </Panel>
  );
}

function Simulator() {
  const tools = useQuery({ queryKey: ["tools"], queryFn: api.tools });
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const [tool, setTool] = useState("refund.issue");
  const [agent, setAgent] = useState("support");
  const [args, setArgs] = useState('{"order_id": "A-7731", "amount": 750.0, "reason": "test"}');
  const sim = useMutation({ mutationFn: () => api.simulate({ tool, agent, args: JSON.parse(args) }) });
  return (
    <Panel title="Simulator" icon={Zap} description="Evaluate a hypothetical tool call exactly as the runtime would.">
      <div className="space-y-2 p-3">
        <div className="flex gap-2">
          <Select value={agent} onChange={(e) => setAgent(e.target.value)} aria-label="agent">{(agents.data ?? []).map((a) => <option key={a.name}>{a.name}</option>)}</Select>
          <Select value={tool} onChange={(e) => setTool(e.target.value)} className="min-w-0 flex-1" aria-label="tool">{(tools.data ?? []).map((t) => <option key={t.name}>{t.name}</option>)}</Select>
        </div>
        <div className="flex gap-2">
          <Input value={args} onChange={(e) => setArgs(e.target.value)} className="font-mono text-[11px]" aria-label="arguments" />
          <Button size="sm" variant="outline" className="h-8" onClick={() => sim.mutate()}><Gavel /> Evaluate</Button>
        </div>
        <ErrorNote error={sim.error} />
        {sim.data && (
          <div className="flex items-start gap-2 rounded-md border px-2.5 py-2 text-xs" data-testid="simulation">
            <StatusBadge status={sim.data.effect} />
            <div><span className="font-mono font-medium">{sim.data.rule_name ?? "default"}</span><p className="text-muted-foreground">{sim.data.reason}</p></div>
          </div>
        )}
      </div>
    </Panel>
  );
}

function Policies() {
  const policies = useQuery({ queryKey: ["policies"], queryFn: api.policies });
  const blocked = useQuery({ queryKey: ["blocked"], queryFn: api.blocked });
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const [adding, setAdding] = useState(false);
  const hits = useMemo(() => {
    const h: Record<string, number> = {};
    for (const i of overview.data?.policy.interventions ?? []) h[i.rule] = (h[i.rule] ?? 0) + i.count;
    for (const b of blocked.data ?? []) if (b.rule_name && !(b.rule_name in h)) h[b.rule_name] = (h[b.rule_name] ?? 0) + 1;
    return h;
  }, [overview.data, blocked.data]);
  const rules = (policies.data ?? []).slice().sort((a, b) => a.priority - b.priority);
  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_420px]">
      <Panel
        title={`Rules · ${rules.filter((r) => r.enabled).length} enabled`}
        icon={Gavel}
        description="Evaluated in priority order; the first matching rule decides. Tools outside an agent's allowlist are always denied."
        actions={!adding && <Button size="sm" variant="outline" onClick={() => setAdding(true)}><Plus /> Add rule</Button>}
      >
        {rules.length === 0 && <div className="px-3 py-6 text-xs text-muted-foreground">No rules: every allow-listed tool call is allowed.</div>}
        <ul className="divide-y">
          {rules.map((r) => <RuleRow key={r.id} rule={r} hits={hits[r.name] ?? 0} />)}
        </ul>
        {adding && <NewRule onDone={() => setAdding(false)} />}
      </Panel>
      <div className="space-y-3">
        <Simulator />
        <YamlEditor />
      </div>
    </div>
  );
}

function Blocked() {
  const b = useQuery({ queryKey: ["blocked"], queryFn: api.blocked, refetchInterval: 4000 });
  if (b.data?.length === 0) return <EmptyState title="Nothing blocked yet" icon={ShieldBan}>Denied, paused and guard-stopped tool calls appear here.</EmptyState>;
  return (
    <Panel title="Blocked and paused tool calls" icon={ShieldBan} description="Every call a rule or guard stopped before it executed, newest first.">
      <ul className="divide-y">
        {b.data?.map((x) => (
          <li key={x.event_id} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3 px-3 py-1.5" data-testid="blocked-row">
            <StatusBadge status={x.effect ?? "blocked"} />
            <div className="min-w-0 text-xs">
              <div className="truncate"><span className="font-mono font-medium">{x.tool}</span> <span className="font-mono text-muted-foreground">{JSON.stringify(x.args)}</span></div>
              <div className="truncate text-muted-foreground"><span className="font-mono text-foreground/80">{x.rule_name ?? x.guard}</span> · {x.reason}</div>
            </div>
            <span className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <Link className="font-mono text-primary hover:underline" to={`/runs/${x.run_id}`}>{shortId(x.run_id)}</Link>
              {x.step !== null && <>step {x.step}</>} · {timeAgo(x.ts)}
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

type Cell = { allowlisted: boolean; effect: "allow" | "deny" | "require_approval"; decidedBy: string | null; conditional: PolicyRule[] };

function resolveCell(agent: AgentSpec, tool: ToolInfo, rules: PolicyRule[]): Cell {
  if (!glob(tool.name, agent.tools)) return { allowlisted: false, effect: "deny", decidedBy: "allowlist", conditional: [] };
  const conditional: PolicyRule[] = [];
  for (const r of rules) {
    if (!r.enabled || !glob(tool.name, r.tools) || !glob(agent.role, r.roles) || !glob(agent.name, r.agents)) continue;
    if (r.conditions.length || r.max_calls_per_run !== null) {
      conditional.push(r);
      continue;
    }
    return { allowlisted: true, effect: r.effect, decidedBy: r.name, conditional };
  }
  return { allowlisted: true, effect: "allow", decidedBy: null, conditional };
}

const CELL_STYLE = {
  allow: { icon: Check, className: "text-success", label: "allowed" },
  require_approval: { icon: PauseCircle, className: "text-warning", label: "needs approval" },
  deny: { icon: X, className: "text-destructive", label: "denied" },
} as const;

/** What each agent may do with each tool, resolved the way the policy engine resolves it. */
function Permissions() {
  const tools = useQuery({ queryKey: ["tools"], queryFn: api.tools });
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const policies = useQuery({ queryKey: ["policies"], queryFn: api.policies });
  const rules = (policies.data ?? []).slice().sort((a, b) => a.priority - b.priority);
  const ts = tools.data ?? [];
  return (
    <div className="space-y-3">
      <Panel
        title="Tool permissions"
        icon={Grid3x3}
        description="Each cell: what happens when that agent calls that tool, before any condition. Conditional rules that can intervene first are listed underneath."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="permission-matrix">
            <thead>
              <tr className="border-b">
                <th className="sticky left-0 bg-card px-3 py-2 text-left text-[10px] font-medium tracking-wide text-muted-foreground uppercase">Agent</th>
                {ts.map((t) => (
                  <th key={t.name} className="px-2 py-2 text-left align-bottom font-medium" title={t.description}>
                    <span className="font-mono">{t.name}</span>
                    {t.side_effect && <Badge variant="warning" className="ml-1 px-1 py-0 text-[9px]">side effect</Badge>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {(agents.data ?? []).map((a) => (
                <tr key={a.name}>
                  <td className="sticky left-0 bg-card px-3 py-2 align-top">
                    <div className="font-mono font-medium">{a.name}</div>
                    <div className="text-[10.5px] text-muted-foreground">{a.role} · {a.enforce_policies ? "policies enforced" : "policies off"}</div>
                  </td>
                  {ts.map((t) => {
                    const c = resolveCell(a, t, rules);
                    if (!c.allowlisted)
                      return (
                        <td key={t.name} className="px-2 py-2 align-top text-muted-foreground/60" title="not in this agent's tool allowlist">
                          <Minus className="size-3.5" />
                        </td>
                      );
                    const s = CELL_STYLE[c.effect];
                    return (
                      <td key={t.name} className="px-2 py-2 align-top" data-testid={`perm-${a.name}-${t.name}`}>
                        <span className={cn("flex items-center gap-1", s.className)} title={c.decidedBy ? `rule ${c.decidedBy}` : "no unconditional rule; default allow"}>
                          <s.icon className="size-3.5" /> {s.label}
                        </span>
                        {c.conditional.map((r) => (
                          <div key={r.id} className="mt-0.5 truncate text-[10.5px] text-muted-foreground" title={r.description || r.name}>
                            <span className={CELL_STYLE[r.effect].className}>{r.effect === "require_approval" ? "approval" : r.effect}</span>{" "}
                            {r.conditions.length
                              ? `if ${r.conditions.map((x) => `${x.arg} ${x.op} ${JSON.stringify(x.value)}`).join(" & ")}`
                              : `after ${r.max_calls_per_run} call${r.max_calls_per_run === 1 ? "" : "s"}/run`}
                          </div>
                        ))}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 border-t px-3 py-1.5 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1"><Check className="size-3 text-success" /> allowed</span>
          <span className="flex items-center gap-1"><PauseCircle className="size-3 text-warning" /> needs approval</span>
          <span className="flex items-center gap-1"><X className="size-3 text-destructive" /> denied by a rule</span>
          <span className="flex items-center gap-1"><Minus className="size-3" /> not in the agent's allowlist</span>
        </div>
      </Panel>
      <Panel title="Agents" icon={ShieldCheck}>
        <ul className="divide-y">
          {(agents.data ?? []).map((a) => (
            <li key={a.name} className="grid gap-1 px-3 py-2 text-xs md:grid-cols-[180px_minmax(0,1fr)]">
              <div><span className="font-mono font-medium">{a.name}</span> <span className="text-muted-foreground">· {a.role}</span></div>
              <div className="text-muted-foreground">
                model <span className="font-mono text-foreground/90">{a.model}</span> · scopes {a.memory_scopes.join(", ")} · budget {a.context.budget_tokens} tok · max {a.limits.max_steps} steps · {a.limits.max_retries} retries · timeout {a.limits.timeout_s}s
              </div>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

const ACTION_TONE: Record<string, "success" | "destructive" | "warning" | "info" | "outline"> = {
  "approval.approved": "success",
  "approval.rejected": "destructive",
  "policy.deleted": "destructive",
  "memory.retracted": "destructive",
  "key.revoked": "destructive",
  "policy.created": "info",
  "policy.updated": "info",
  "policy.replaced": "info",
  "memory.updated": "info",
  "memory.created": "info",
  "key.created": "info",
  "experiment.reset": "warning",
};

function Audit() {
  const [type, setType] = useState("");
  const a = useQuery({ queryKey: ["audit", type], queryFn: () => api.audit(type || undefined), refetchInterval: 5000 });
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Panel
      title="Audit trail"
      icon={History}
      description="Every change made through the API, newest first, attributed to the API key that made it."
      actions={
        <Select value={type} onChange={(e) => setType(e.target.value)} className="h-7 text-xs" aria-label="filter">
          <option value="">everything</option>
          {["policy", "approval", "memory", "key", "experiment"].map((t) => <option key={t}>{t}</option>)}
        </Select>
      }
      data-testid="audit-trail"
    >
      {a.data?.length === 0 && <div className="px-3 py-6 text-xs text-muted-foreground">No changes recorded yet.</div>}
      <ul className="divide-y">
        {(a.data ?? []).map((e: AuditEntry) => (
          <li key={e.id} data-testid="audit-row">
            <button className="grid w-full grid-cols-[96px_150px_minmax(0,1fr)_auto] items-center gap-3 px-3 py-1.5 text-left text-xs hover:bg-accent/40" onClick={() => setOpen(open === e.id ? null : e.id)}>
              <span className="text-[11px] text-muted-foreground tabular-nums" title={new Date(e.ts + (e.ts.endsWith("Z") ? "" : "Z")).toLocaleString()}>{timeAgo(e.ts)}</span>
              <Badge variant={ACTION_TONE[e.action] ?? "outline"} className="justify-self-start font-mono">{e.action}</Badge>
              <span className="truncate">{e.summary}</span>
              <span className="font-mono text-[11px] text-muted-foreground">{e.actor}</span>
            </button>
            {open === e.id && <div className="px-3 pb-2"><Json value={{ target: `${e.target_type}:${e.target_id ?? "-"}`, ...e.details }} className="max-h-60" /></div>}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export default function ControlRoom() {
  const policies = useQuery({ queryKey: ["policies"], queryFn: api.policies });
  const pending = useQuery({ queryKey: ["approvals", "pending"], queryFn: () => api.approvals("pending") });
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const tools = useQuery({ queryKey: ["tools"], queryFn: api.tools });
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const d = overview.data?.policy.decisions ?? {};
  return (
    <div className="space-y-3">
      <PageHeader title="Control Room" description="Rules enforced in code, outside the model: permissions, approvals, blocks and who changed what." icon={ShieldCheck} />
      <div className="grid grid-cols-2 divide-x divide-y rounded-lg border bg-card sm:grid-cols-5 sm:divide-y-0">
        <Metric label="Awaiting approval" value={pending.data?.length ?? 0} tone={pending.data?.length ? "warn" : "muted"} />
        <Metric label="Rules enabled" value={`${(policies.data ?? []).filter((r) => r.enabled).length} / ${policies.data?.length ?? 0}`} />
        <Metric label="Calls denied" value={d.deny ?? 0} tone={d.deny ? "bad" : "muted"} hint="by rules, allowlists and guards" />
        <Metric label="Calls paused for approval" value={d.require_approval ?? 0} tone="muted" />
        <Metric label="Agents · tools" value={`${agents.data?.length ?? 0} · ${tools.data?.length ?? 0}`} hint={`${(tools.data ?? []).filter((t) => t.side_effect).length} with side effects`} />
      </div>
      <Tabs defaultValue={pending.data?.length === 0 ? "policies" : "approvals"} key={pending.isSuccess ? "ready" : "loading"}>
        <TabsList>
          <TabsTrigger value="approvals"><PauseCircle /> Approvals {pending.data?.length ? <Badge variant="warning" className="px-1 py-0">{pending.data.length}</Badge> : null}</TabsTrigger>
          <TabsTrigger value="policies"><Gavel /> Policies</TabsTrigger>
          <TabsTrigger value="blocked"><ShieldBan /> Blocked actions</TabsTrigger>
          <TabsTrigger value="permissions"><Grid3x3 /> Tool permissions</TabsTrigger>
          <TabsTrigger value="audit"><History /> Audit trail</TabsTrigger>
        </TabsList>
        <TabsContent value="approvals"><Approvals /></TabsContent>
        <TabsContent value="policies"><Policies /></TabsContent>
        <TabsContent value="blocked"><Blocked /></TabsContent>
        <TabsContent value="permissions"><Permissions /></TabsContent>
        <TabsContent value="audit"><Audit /></TabsContent>
      </Tabs>
    </div>
  );
}
