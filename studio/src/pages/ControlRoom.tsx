import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, FileCode2, Gavel, PauseCircle, Plus, ShieldBan, ShieldCheck, Trash2, Wrench, X, Zap } from "lucide-react";
import { api } from "@/lib/api";
import type { PolicyRule } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, ErrorNote, Json, Mono, PageHeader, StatusBadge } from "@/components/common";
import { shortId, timeAgo } from "@/lib/utils";

function Approvals() {
  const qc = useQueryClient();
  const all = useQuery({ queryKey: ["approvals", "all"], queryFn: () => api.approvals(), refetchInterval: 3000 });
  const [notes, setNotes] = useState<Record<string, string>>({});
  const resolve = useMutation({
    mutationFn: ({ id, ok }: { id: string; ok: boolean }) => api.resolveApproval(id, ok, notes[id]),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });
  const pending = (all.data ?? []).filter((a) => a.status === "pending");
  const done = (all.data ?? []).filter((a) => a.status !== "pending");
  return (
    <div className="space-y-4">
      <ErrorNote error={resolve.error} />
      {pending.length === 0 ? (
        <EmptyState title="No pending approvals" icon={PauseCircle}>
          Tool calls matching a <b>require_approval</b> rule pause their run here until a human decides.
        </EmptyState>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {pending.map((a) => (
            <Card key={a.id} className="border-warning/50" data-testid="approval-card">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <PauseCircle className="size-4 text-warning" /> {a.tool}
                </CardTitle>
                <CardDescription>
                  run <Link className="text-primary hover:underline" to={`/runs/${a.run_id}`}>{shortId(a.run_id)}</Link> · step {a.step} · {timeAgo(a.requested_at)}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                <Json value={a.args} />
                <p className="text-xs text-muted-foreground">Rule: {a.reason}</p>
                <Input placeholder="Note (optional)" value={notes[a.id] ?? ""} onChange={(e) => setNotes({ ...notes, [a.id]: e.target.value })} />
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="destructive" onClick={() => resolve.mutate({ id: a.id, ok: false })}><X /> Reject</Button>
                  <Button size="sm" variant="success" onClick={() => resolve.mutate({ id: a.id, ok: true })} data-testid="approve-card"><Check /> Approve & resume</Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      {done.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Decision history</CardTitle></CardHeader>
          <CardContent className="px-0">
            <Table>
              <THead><TR><TH>Tool</TH><TH>Args</TH><TH>Decision</TH><TH>By</TH><TH>Run</TH><TH>When</TH></TR></THead>
              <TBody>
                {done.map((a) => (
                  <TR key={a.id}>
                    <TD className="font-medium">{a.tool}</TD>
                    <TD><Mono>{JSON.stringify(a.args)}</Mono></TD>
                    <TD><StatusBadge status={a.status} /></TD>
                    <TD className="text-xs">{a.resolver}{a.note ? ` — ${a.note}` : ""}</TD>
                    <TD><Link className="font-mono text-xs text-primary hover:underline" to={`/runs/${a.run_id}`}>{shortId(a.run_id)}</Link></TD>
                    <TD className="text-xs text-muted-foreground">{timeAgo(a.resolved_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

const EFFECT_VARIANT = { allow: "success", deny: "destructive", require_approval: "warning" } as const;

function RuleCard({ rule }: { rule: PolicyRule }) {
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: () => {
      const { id: _i, created_at: _c, ...body } = rule;
      return api.updatePolicy(rule.id, { ...body, enabled: !rule.enabled });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["policies"] }),
  });
  const del = useMutation({ mutationFn: () => api.deletePolicy(rule.id), onSuccess: () => qc.invalidateQueries({ queryKey: ["policies"] }) });
  return (
    <Card className={rule.enabled ? "" : "opacity-55"} data-testid="policy-rule">
      <CardContent className="space-y-1.5 pt-4">
        <div className="flex items-center gap-2">
          <Badge variant="outline">#{rule.priority}</Badge>
          <span className="text-sm font-semibold">{rule.name}</span>
          <Badge variant={EFFECT_VARIANT[rule.effect]}>{rule.effect.replace("_", " ")}</Badge>
          <div className="ml-auto flex gap-1">
            <Button size="sm" variant="ghost" onClick={() => toggle.mutate()}>{rule.enabled ? "Disable" : "Enable"}</Button>
            <Button size="icon" variant="ghost" onClick={() => del.mutate()} aria-label="Delete rule"><Trash2 /></Button>
          </div>
        </div>
        {rule.description && <p className="text-xs text-muted-foreground">{rule.description}</p>}
        <div className="flex flex-wrap gap-1 text-[11px]">
          <span className="text-muted-foreground">tools</span>{rule.tools.map((t) => <Badge key={t} variant="secondary">{t}</Badge>)}
          {rule.roles.join() !== "*" && <><span className="text-muted-foreground">roles</span>{rule.roles.map((t) => <Badge key={t} variant="secondary">{t}</Badge>)}</>}
          {rule.agents.join() !== "*" && <><span className="text-muted-foreground">agents</span>{rule.agents.map((t) => <Badge key={t} variant="secondary">{t}</Badge>)}</>}
          {rule.conditions.map((c, i) => <Badge key={i} variant="info">{c.arg} {c.op} {JSON.stringify(c.value)}</Badge>)}
          {rule.max_calls_per_run !== null && <Badge variant="info">max {rule.max_calls_per_run} call(s)/run</Badge>}
        </div>
      </CardContent>
    </Card>
  );
}

function NewRule() {
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
      qc.invalidateQueries({ queryKey: ["policies"] });
      setName("");
    },
  });
  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2"><Plus className="size-4" /> New rule</CardTitle></CardHeader>
      <CardContent className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1"><Label>Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="block-large-payouts" /></div>
        <div className="space-y-1"><Label>Effect</Label>
          <Select value={effect} onChange={(e) => setEffect(e.target.value)} className="w-full">
            <option value="deny">deny</option><option value="require_approval">require_approval</option><option value="allow">allow</option>
          </Select>
        </div>
        <div className="space-y-1"><Label>Tools (globs, comma separated)</Label><Input value={tools} onChange={(e) => setTools(e.target.value)} /></div>
        <div className="space-y-1"><Label>Priority (lower wins)</Label><Input type="number" value={priority} onChange={(e) => setPriority(Number(e.target.value))} /></div>
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
        <div className="flex justify-end sm:col-span-2"><Button disabled={!name || m.isPending} onClick={() => m.mutate()}>Add rule</Button></div>
      </CardContent>
    </Card>
  );
}

function YamlEditor() {
  const qc = useQueryClient();
  const y = useQuery({ queryKey: ["policies", "yaml"], queryFn: api.policiesYaml });
  const [text, setText] = useState("");
  useEffect(() => { if (y.data) setText(y.data.yaml); }, [y.data]);
  const save = useMutation({ mutationFn: () => api.putPoliciesYaml(text), onSuccess: () => qc.invalidateQueries({ queryKey: ["policies"] }) });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><FileCode2 className="size-4" /> Policy as code</CardTitle>
        <CardDescription>Replace all rules of this project atomically (validated server-side).</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={18} className="font-mono text-xs" spellCheck={false} />
        <ErrorNote error={save.error} />
        <div className="flex justify-end"><Button onClick={() => save.mutate()} disabled={save.isPending}>Apply YAML</Button></div>
      </CardContent>
    </Card>
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
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Zap className="size-4" /> Policy simulator</CardTitle>
        <CardDescription>Evaluate a hypothetical tool call against the current rules — exactly as the runtime would.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex gap-2">
          <Select value={agent} onChange={(e) => setAgent(e.target.value)}>{(agents.data ?? []).map((a) => <option key={a.name}>{a.name}</option>)}</Select>
          <Select value={tool} onChange={(e) => setTool(e.target.value)} className="flex-1">{(tools.data ?? []).map((t) => <option key={t.name}>{t.name}</option>)}</Select>
        </div>
        <Input value={args} onChange={(e) => setArgs(e.target.value)} className="font-mono text-xs" />
        <Button variant="outline" onClick={() => sim.mutate()}><Gavel /> Evaluate</Button>
        <ErrorNote error={sim.error} />
        {sim.data && (
          <div className="rounded-lg border p-3 text-sm" data-testid="simulation">
            <StatusBadge status={sim.data.effect} /> <span className="ml-1 font-medium">{sim.data.rule_name ?? "default"}</span>
            <p className="mt-1 text-xs text-muted-foreground">{sim.data.reason}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Blocked() {
  const b = useQuery({ queryKey: ["blocked"], queryFn: api.blocked, refetchInterval: 4000 });
  if (b.data?.length === 0) return <EmptyState title="Nothing blocked yet" icon={ShieldBan} />;
  return (
    <Card>
      <CardContent className="px-0 pt-2">
        <Table>
          <THead><TR><TH>When</TH><TH>Decision</TH><TH>Tool</TH><TH>Arguments</TH><TH>Rule / reason</TH><TH>Run</TH></TR></THead>
          <TBody>
            {b.data?.map((x) => (
              <TR key={x.event_id} data-testid="blocked-row">
                <TD className="text-xs whitespace-nowrap text-muted-foreground">{timeAgo(x.ts)}</TD>
                <TD><StatusBadge status={x.effect ?? "blocked"} /></TD>
                <TD className="font-medium">{x.tool}</TD>
                <TD><Mono className="line-clamp-2">{JSON.stringify(x.args)}</Mono></TD>
                <TD className="max-w-sm text-xs"><b>{x.rule_name ?? x.guard}</b> {x.reason}</TD>
                <TD><Link className="font-mono text-xs text-primary hover:underline" to={`/runs/${x.run_id}`}>{shortId(x.run_id)}</Link></TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function Registry() {
  const tools = useQuery({ queryKey: ["tools"], queryFn: api.tools });
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Wrench className="size-4" /> Tools</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {tools.data?.map((t) => (
            <div key={t.name} className="rounded-md border p-2.5 text-xs">
              <div className="flex items-center gap-2"><b className="text-sm">{t.name}</b>{t.side_effect && <Badge variant="warning">side effect</Badge>}</div>
              <p className="text-muted-foreground">{t.description}</p>
              <div className="mt-1 flex flex-wrap gap-1">
                {Object.entries(t.parameters.properties ?? {}).map(([k, v]) => (
                  <Badge key={k} variant="secondary">{k}: {v.type ?? "any"}{t.parameters.required?.includes(k) ? "" : "?"}</Badge>
                ))}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4" /> Agents & permissions</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {agents.data?.map((a) => (
            <div key={a.name} className="rounded-md border p-2.5 text-xs">
              <div className="flex items-center gap-2"><b className="text-sm">{a.name}</b><Badge variant="outline">{a.role}</Badge><Mono className="ml-auto text-muted-foreground">{a.model}</Mono></div>
              <div className="mt-1 flex flex-wrap gap-1">
                <span className="text-muted-foreground">allowed tools:</span>
                {a.tools.length ? a.tools.map((t) => <Badge key={t} variant="success">{t}</Badge>) : <span>none</span>}
              </div>
              <div className="mt-1 text-muted-foreground">
                scopes {a.memory_scopes.join(", ")} · budget {a.context.budget_tokens} tok · max {a.limits.max_steps} steps · retries {a.limits.max_retries} · policies {a.enforce_policies ? "enforced" : "off"}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

export default function ControlRoom() {
  const policies = useQuery({ queryKey: ["policies"], queryFn: api.policies });
  const pending = useQuery({ queryKey: ["approvals", "pending"], queryFn: () => api.approvals("pending") });
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        title="Control Room"
        description="Policies enforced in code: tool permissions, limits, approvals, and every blocked action."
        icon={ShieldCheck}
      />
      <Tabs defaultValue="approvals">
        <TabsList className="flex-wrap">
          <TabsTrigger value="approvals"><PauseCircle /> Approvals {pending.data?.length ? <Badge variant="warning">{pending.data.length}</Badge> : null}</TabsTrigger>
          <TabsTrigger value="policies"><Gavel /> Policies</TabsTrigger>
          <TabsTrigger value="blocked"><ShieldBan /> Blocked actions</TabsTrigger>
          <TabsTrigger value="registry"><Wrench /> Tools & agents</TabsTrigger>
        </TabsList>
        <TabsContent value="approvals"><Approvals /></TabsContent>
        <TabsContent value="policies">
          <div className="grid gap-4 xl:grid-cols-[1fr_440px]">
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">Evaluated in priority order; the first matching rule decides. Tools outside an agent's allowlist are always denied.</p>
              {policies.data?.map((r) => <RuleCard key={r.id} rule={r} />)}
              {policies.data?.length === 0 && <EmptyState title="No rules: every allow-listed tool call is allowed" />}
              <NewRule />
            </div>
            <div className="space-y-4"><Simulator /><YamlEditor /></div>
          </div>
        </TabsContent>
        <TabsContent value="blocked"><Blocked /></TabsContent>
        <TabsContent value="registry"><Registry /></TabsContent>
      </Tabs>
    </div>
  );
}
