import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Brain, Eye, GitBranch, History, Pencil, Plus, Search, Trash2, Users, X } from "lucide-react";
import { api } from "@/lib/api";
import type { AgentSpec, Memory } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote, IdChip, KV, Metric, PageHeader, Panel, ScoreBar, StatusBadge, StatusDot } from "@/components/common";
import { ReceiptPanel, REASON_TEXT } from "@/components/ReceiptPanel";
import { MemoryImpactView } from "@/components/Impact";
import { cn, shortId, timeAgo } from "@/lib/utils";

/** Same rule as the context engine: exact scopes, or prefixes ending in `*`. */
function scopeVisible(scope: string, allowed: string[]) {
  return allowed.some((a) => a === "*" || a === scope || (a.endsWith("*") && scope.startsWith(a.slice(0, -1))));
}

const FIELDS: (keyof Memory)[] = ["content", "scope", "trust", "importance", "kind", "expires_at"];

function Section({ title, icon: Icon, children, aside }: { title: string; icon?: React.ElementType; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="border-t px-3 py-2.5">
      <h3 className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
        {Icon && <Icon className="size-3.5" />} {title}
        {aside && <span className="ml-auto font-normal tracking-normal normal-case">{aside}</span>}
      </h3>
      {children}
    </section>
  );
}

function Inspector({ id, agents, onClose, onNavigate }: { id: string; agents: AgentSpec[]; onClose: () => void; onNavigate: (id: string) => void }) {
  const qc = useQueryClient();
  const m = useQuery({ queryKey: ["memory", id], queryFn: () => api.memory(id) });
  const versions = useQuery({ queryKey: ["versions", id], queryFn: () => api.versions(id) });
  const retrievals = useQuery({ queryKey: ["retrievals", id], queryFn: () => api.retrievals(id) });
  const [mode, setMode] = useState<"view" | "edit" | "retract">("view");
  const [content, setContent] = useState("");
  const [scope, setScope] = useState("project");
  const [trust, setTrust] = useState(0.7);
  const [reason, setReason] = useState("");
  useEffect(() => {
    if (m.data) {
      setContent(m.data.content);
      setScope(m.data.scope);
      setTrust(m.data.trust);
    }
  }, [m.data]);
  const refresh = (next?: Memory) => {
    for (const k of ["memories", "conflicts", "memory", "versions", "audit"]) qc.invalidateQueries({ queryKey: [k] });
    setMode("view");
    setReason("");
    if (next && next.id !== id) onNavigate(next.id);
  };
  const change = () => ({
    ...(content !== m.data?.content ? { content } : {}),
    ...(scope !== m.data?.scope ? { scope } : {}),
    ...(trust !== m.data?.trust ? { trust } : {}),
  });
  const save = useMutation({
    mutationFn: () => api.updateMemory(id, { ...change(), reason: reason || undefined, edited_by: "studio-user" }),
    onSuccess: refresh,
  });
  const impact = useMutation({ mutationFn: () => api.memoryImpact(id, { ...change(), edited_by: "studio-user" }) });
  const retract = useMutation({ mutationFn: () => api.retractMemory(id, reason), onSuccess: () => refresh() });
  const mem = m.data;
  const used = retrievals.data ?? [];
  const excludedBy = used.filter((r) => !r.included).reduce<Record<string, number>>((acc, r) => ({ ...acc, [r.reason ?? "?"]: (acc[r.reason ?? "?"] ?? 0) + 1 }), {});

  if (!mem) return m.error ? <ErrorNote error={m.error} /> : <Skeleton className="h-96" />;
  const chain = (versions.data ?? []).slice().sort((a, b) => a.version - b.version);

  return (
    <Panel data-testid="memory-detail" className="lg:sticky lg:top-0 lg:max-h-[calc(100vh-112px)]" bodyClassName="overflow-auto">
      <div className="space-y-2 p-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-sm font-semibold">{mem.subject_key ?? mem.kind}</span>
              <Badge variant="outline">v{mem.version}</Badge>
              <StatusBadge status={mem.status} />
              <Badge variant={mem.scope === "project" ? "outline" : "info"}>{mem.scope}</Badge>
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground">
              <IdChip id={mem.id} /> · {mem.kind} · trust {mem.trust.toFixed(2)} · importance {mem.importance.toFixed(2)}
            </div>
          </div>
          <Button size="icon" variant="ghost" className="size-7" onClick={onClose} aria-label="Close">
            <X />
          </Button>
        </div>
        <p className="rounded-md border bg-background/50 p-2.5 text-[13px] leading-relaxed">{mem.content}</p>
        {mem.status_reason && <p className="text-xs text-muted-foreground">status: {mem.status_reason}</p>}

        {mode === "view" && mem.status === "active" && (
          <div className="flex gap-1.5">
            <Button size="sm" variant="outline" onClick={() => setMode("edit")} data-testid="edit-memory">
              <Pencil /> Edit (new version)
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setMode("retract")} data-testid="retract-memory">
              <Trash2 /> Retract
            </Button>
          </div>
        )}
        {mode === "edit" && (
          <div className="space-y-2 rounded-md border p-2.5">
            <Label>Content</Label>
            <Textarea value={content} onChange={(e) => setContent(e.target.value)} rows={4} />
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label>Scope</Label>
                <Input value={scope} onChange={(e) => setScope(e.target.value)} data-testid="scope-input" />
              </div>
              <div className="space-y-1">
                <Label>Trust ({trust.toFixed(2)})</Label>
                <input type="range" min={0} max={1} step={0.05} value={trust} onChange={(e) => setTrust(Number(e.target.value))} className="w-full accent-primary" />
              </div>
            </div>
            <Label>Reason for change (kept in provenance and the audit trail)</Label>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. policy applies to all agents" />
            <ErrorNote error={save.error ?? impact.error} />
            {impact.data && <MemoryImpactView impact={impact.data} />}
            <div className="flex justify-end gap-1.5">
              <Button size="sm" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
              <Button size="sm" variant="outline" onClick={() => impact.mutate()} disabled={impact.isPending} data-testid="preview-memory"
                title="Dry run: who gains or loses access, what gets superseded, how recent runs' context would change">
                <Eye /> Preview impact
              </Button>
              <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending} data-testid="save-memory">
                Save as v{mem.version + 1}
              </Button>
            </div>
          </div>
        )}
        {mode === "retract" && (
          <div className="space-y-2 rounded-md border border-destructive/40 p-2.5">
            <Label>Why is this memory wrong or unsafe?</Label>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} />
            <ErrorNote error={retract.error} />
            <div className="flex justify-end gap-1.5">
              <Button size="sm" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
              <Button size="sm" variant="destructive" disabled={!reason || retract.isPending} onClick={() => retract.mutate()}>Retract</Button>
            </div>
          </div>
        )}
      </div>

      <Section title="Who can see it" icon={Users}>
        <ul className="space-y-0.5 text-xs" data-testid="memory-visibility">
          {agents.map((a) => {
            const ok = mem.status === "active" && scopeVisible(mem.scope, a.memory_scopes);
            return (
              <li key={a.name} className="flex items-center gap-2">
                <StatusDot status={ok ? "ok" : "pending"} />
                <span className={cn("font-mono", !ok && "text-muted-foreground")}>{a.name}</span>
                <span className="truncate text-[11px] text-muted-foreground">scopes: {a.memory_scopes.join(", ")}</span>
              </li>
            );
          })}
        </ul>
        {mem.status === "active" && agents.every((a) => !scopeVisible(mem.scope, a.memory_scopes)) && (
          <p className="mt-1 text-xs text-warning">No registered agent can see this memory in scope {mem.scope}.</p>
        )}
      </Section>

      <Section title="Version history" icon={GitBranch} aside={`${chain.length} version${chain.length === 1 ? "" : "s"}`}>
        <ol className="relative space-y-2 border-l pl-3.5">
          {chain.slice().reverse().map((v) => {
            const prev = chain.find((p) => p.version === v.version - 1);
            const changed = prev ? FIELDS.filter((f) => JSON.stringify(prev[f]) !== JSON.stringify(v[f])) : [];
            return (
              <li key={v.id} className="relative">
                <span className={cn("absolute top-1.5 -left-[19px] size-2 rounded-full ring-2 ring-card", v.status === "active" ? "bg-success" : "bg-muted-foreground")} />
                <button className={cn("w-full rounded-md px-2 py-1 text-left hover:bg-accent/50", v.id === id && "bg-accent/60")} onClick={() => onNavigate(v.id)}>
                  <div className="flex items-center gap-1.5 text-xs">
                    <b>v{v.version}</b> <StatusBadge status={v.status} />
                    <span className="ml-auto text-[11px] text-muted-foreground">{timeAgo(v.created_at)} · {v.created_by}</span>
                  </div>
                  {prev ? (
                    <div className="mt-0.5 space-y-0.5 text-[11px]">
                      {changed.map((f) => (
                        <div key={f} className="truncate">
                          <span className="text-muted-foreground">{f}: </span>
                          <span className="text-destructive line-through decoration-destructive/60">{String(prev[f] ?? "–")}</span>{" "}
                          <ArrowRight className="inline size-3 text-muted-foreground" /> <span className="text-success">{String(v[f] ?? "–")}</span>
                        </div>
                      ))}
                      {changed.length === 0 && <div className="text-muted-foreground">no field changes</div>}
                    </div>
                  ) : (
                    <div className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">created: {v.content}</div>
                  )}
                  {v.status_reason && <div className="text-[11px] text-muted-foreground">{v.status_reason}</div>}
                </button>
              </li>
            );
          })}
        </ol>
      </Section>

      <Section title="Provenance">
        <KV k="source">{mem.source_type}{mem.source_ref ? ` · ${mem.source_ref}` : ""}</KV>
        <KV k="created by">{mem.created_by}</KV>
        <KV k="from run">{mem.run_id ? <Link className="text-primary hover:underline" to={`/runs/${mem.run_id}`}>{shortId(mem.run_id)}</Link> : "–"}</KV>
        <KV k="valid from">{new Date(mem.valid_from).toLocaleString()}</KV>
        <KV k="expires">{mem.expires_at ? new Date(mem.expires_at).toLocaleString() : "never"}</KV>
        <KV k="tags">{mem.tags.join(", ") || "–"}</KV>
        <KV k="supersedes">
          {mem.supersedes_id ? <button className="text-primary hover:underline" onClick={() => onNavigate(mem.supersedes_id!)}>{shortId(mem.supersedes_id)}</button> : "–"}
        </KV>
      </Section>

      <Section
        title="Retrieval history"
        icon={History}
        aside={used.length ? `${used.filter((r) => r.included).length} included · ${used.length - used.filter((r) => r.included).length} excluded` : undefined}
      >
        {Object.keys(excludedBy).length > 0 && (
          <div className="mb-1.5 flex flex-wrap gap-1">
            {Object.entries(excludedBy).map(([r, n]) => (
              <Badge key={r} variant="destructive" title={REASON_TEXT[r]}>excluded {n}× · {r}</Badge>
            ))}
          </div>
        )}
        {used.length === 0 && <p className="text-xs text-muted-foreground">Never considered by the context engine yet.</p>}
        <ul className="divide-y">
          {used.slice(0, 30).map((r) => (
            <li key={r.id} className="flex items-center gap-2 py-1 text-xs" data-testid="retrieval-row">
              <StatusDot status={r.included ? "ok" : "error"} />
              <span className={cn("shrink-0", !r.included && "text-destructive")}>{r.included ? "included" : r.reason}</span>
              <span className="min-w-0 flex-1 truncate text-muted-foreground" title={r.query}>{r.query}</span>
              <span className="font-mono text-[11px] text-muted-foreground">{r.score.toFixed(2)}</span>
              {r.run_id && <Link className="font-mono text-[11px] text-primary hover:underline" to={`/runs/${r.run_id}`}>{shortId(r.run_id)}</Link>}
            </li>
          ))}
        </ul>
      </Section>
    </Panel>
  );
}

function AddMemory({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [content, setContent] = useState("");
  const [subject, setSubject] = useState("");
  const [scope, setScope] = useState("project");
  const [kind, setKind] = useState("fact");
  const [source, setSource] = useState("");
  const m = useMutation({
    mutationFn: () =>
      api.createMemory({
        content, kind, scope, subject_key: subject || undefined,
        provenance: { source_type: "manual", source_ref: source || undefined, created_by: "studio-user" },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memories"] });
      onDone();
    },
  });
  return (
    <Sheet open onOpenChange={(o) => !o && onDone()}>
      <SheetContent side="center">
        <SheetTitle>Add memory</SheetTitle>
        <Label>Content</Label>
        <Textarea value={content} onChange={(e) => setContent(e.target.value)} />
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1"><Label>Subject key (versioning)</Label><Input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="refund_policy" /></div>
          <div className="space-y-1"><Label>Scope</Label><Input value={scope} onChange={(e) => setScope(e.target.value)} /></div>
          <div className="space-y-1"><Label>Kind</Label>
            <Select value={kind} onChange={(e) => setKind(e.target.value)} className="w-full">
              {["fact", "episode", "decision", "strategy"].map((k) => <option key={k}>{k}</option>)}
            </Select>
          </div>
          <div className="space-y-1"><Label>Source reference</Label><Input value={source} onChange={(e) => setSource(e.target.value)} placeholder="docs/handbook.pdf" /></div>
        </div>
        <ErrorNote error={m.error} />
        <div className="flex justify-end"><Button disabled={!content || m.isPending} onClick={() => m.mutate()}>Save memory</Button></div>
      </SheetContent>
    </Sheet>
  );
}

function AgentView({ agents }: { agents: AgentSpec[] }) {
  const [agent, setAgent] = useState("");
  const [query, setQuery] = useState("Customer C-1042 requests a refund for order A-7731 refund policy");
  const name = agent || agents[0]?.name || "";
  const m = useMutation({ mutationFn: () => api.previewContext({ query, agent: name }) });
  return (
    <Panel title="What will the agent see?" icon={Eye} description="Dry-run the context engine for an agent and a query: what it includes, what it drops and why. Not recorded.">
      <div className="space-y-3 p-3">
        <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
          <Select value={name} onChange={(e) => setAgent(e.target.value)} aria-label="agent">
            {agents.map((a) => <option key={a.name}>{a.name}</option>)}
          </Select>
          <Input value={query} onChange={(e) => setQuery(e.target.value)} className="min-w-60 flex-1" aria-label="query" />
          <Button variant="outline" type="submit" data-testid="preview-context" disabled={!name || m.isPending}>Preview</Button>
        </form>
        <ErrorNote error={m.error} />
        {m.data && <ReceiptPanel receipt={m.data} />}
      </div>
    </Panel>
  );
}

const STATUSES = ["active", "superseded", "retracted", "expired"];

export default function MemoryExplorer() {
  const [params, setParams] = useSearchParams();
  const focus = params.get("focus");
  const [q, setQ] = useState("");
  const [semantic, setSemantic] = useState(false);
  const [status, setStatus] = useState("active");
  const [scope, setScope] = useState("");
  const [adding, setAdding] = useState(false);
  const all = useQuery({ queryKey: ["memories", "all"], queryFn: () => api.memories({ limit: 1000 }) });
  const hits = useQuery({
    queryKey: ["memories", "search", q],
    queryFn: () => api.searchMemories(q, true),
    enabled: semantic && q.trim().length > 0,
  });
  const conflicts = useQuery({ queryKey: ["conflicts"], queryFn: api.conflicts });
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const open = (id: string | null) => {
    const p = new URLSearchParams(params);
    if (id) p.set("focus", id);
    else p.delete("focus");
    setParams(p, { replace: true });
  };
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const m of all.data ?? []) c[m.status] = (c[m.status] ?? 0) + 1;
    return c;
  }, [all.data]);
  const scopes = useMemo(() => [...new Set((all.data ?? []).map((m) => m.scope))].sort(), [all.data]);
  const rel = new Map((hits.data ?? []).map((h) => [h.memory.id, h.relevance]));
  const needle = q.trim().toLowerCase();
  const rows = (semantic && needle ? (hits.data ?? []).map((h) => h.memory) : all.data ?? []).filter(
    (m) =>
      (!status || m.status === status) &&
      (!scope || m.scope === scope) &&
      (semantic || !needle || `${m.subject_key ?? ""} ${m.content}`.toLowerCase().includes(needle)),
  );

  return (
    <div className="space-y-3">
      <PageHeader
        title="Memory Explorer"
        description="What agents know, where it came from, who can see it, and how it has changed."
        icon={Brain}
        actions={<Button size="sm" onClick={() => setAdding(true)}><Plus /> Add memory</Button>}
      />
      <div className="grid grid-cols-2 divide-x divide-y rounded-lg border bg-card sm:grid-cols-5 sm:divide-y-0">
        {STATUSES.map((s) => (
          <button key={s} onClick={() => setStatus(status === s ? "" : s)} className={cn("text-left hover:bg-accent/40", status === s && "bg-accent/60")}>
            <Metric label={s} value={counts[s] ?? 0} tone={s === "active" ? undefined : "muted"} />
          </button>
        ))}
        <Metric label="conflicting subjects" value={conflicts.data?.length ?? 0} tone={conflicts.data?.length ? "warn" : "muted"} hint="resolved by trust, then recency" />
      </div>

      {conflicts.data && conflicts.data.length > 0 && (
        <Panel
          title={`Conflict resolution · ${conflicts.data.length} subject${conflicts.data.length === 1 ? "" : "s"}`}
          icon={AlertTriangle}
          description="Active memories disagree about the same subject. The context engine keeps the winner and excludes the rest (conflict_lost); fix it by editing scope or content, or retracting the loser."
          data-testid="conflicts"
        >
          <div className="divide-y">
            {conflicts.data.map((c) => (
              <div key={c.subject_key} className="space-y-1 px-3 py-2">
                <div className="text-xs"><span className="font-mono font-semibold">{c.subject_key}</span> <span className="text-muted-foreground">· winner by {c.rule}</span></div>
                {c.memories.map((m) => (
                  <button key={m.id} onClick={() => open(m.id)} className="flex w-full items-start gap-2 rounded-md px-1.5 py-1 text-left text-xs hover:bg-accent/50">
                    {m.id === c.suggested_winner ? <Badge variant="success">keeps</Badge> : <Badge variant="outline">loses</Badge>}
                    <Badge variant={m.scope === "project" ? "outline" : "info"}>{m.scope}</Badge>
                    <span className="flex-1">{m.content}</span>
                    <span className="shrink-0 text-muted-foreground tabular-nums">trust {m.trust}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </Panel>
      )}

      <div className={cn("grid gap-3", focus && "lg:grid-cols-[minmax(0,1fr)_minmax(380px,40%)]")}>
        <Panel bodyClassName="flex flex-col">
          <div className="flex flex-wrap items-center gap-2 border-b p-2">
            <div className="relative min-w-52 flex-1">
              <Search className="absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={semantic ? "Semantic search (vector + keyword)…" : "Filter by text or subject…"} className="h-7 pl-7 text-xs" data-testid="memory-search" />
            </div>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input type="checkbox" checked={semantic} onChange={(e) => setSemantic(e.target.checked)} className="accent-primary" /> semantic
            </label>
            <Select value={scope} onChange={(e) => setScope(e.target.value)} className="h-7 text-xs" aria-label="scope">
              <option value="">all scopes</option>
              {scopes.map((s) => <option key={s}>{s}</option>)}
            </Select>
            <Select value={status} onChange={(e) => setStatus(e.target.value)} className="h-7 text-xs" aria-label="status">
              <option value="">any status</option>
              {STATUSES.map((s) => <option key={s}>{s}</option>)}
            </Select>
          </div>
          <ErrorNote error={all.error ?? hits.error} />
          <ul className="divide-y">
            {rows.map((m) => (
              <li key={m.id}>
                <button
                  onClick={() => open(m.id)}
                  className={cn("grid w-full grid-cols-[minmax(0,1fr)_auto] gap-x-3 border-l-2 border-transparent px-3 py-1.5 text-left hover:bg-accent/40", focus === m.id && "border-l-primary bg-accent/60")}
                  data-testid="memory-row"
                  data-active={focus === m.id}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <StatusDot status={m.status} />
                    <span className="truncate font-mono text-xs font-medium">{m.subject_key ?? m.kind}</span>
                    <Badge variant={m.scope === "project" ? "outline" : "info"}>{m.scope}</Badge>
                    {m.version > 1 && <span className="text-[11px] text-muted-foreground">v{m.version}</span>}
                  </span>
                  <span className="flex items-center gap-2 text-[11px] text-muted-foreground">
                    {rel.has(m.id) ? <span className="font-mono">rel {rel.get(m.id)!.toFixed(2)}</span> : <span title="times considered by the context engine">used {m.retrieval_count}×</span>}
                    <ScoreBar value={m.trust} className="w-10" />
                    <span className="w-14 text-right">{timeAgo(m.created_at)}</span>
                  </span>
                  <span className={cn("col-span-2 mt-0.5 line-clamp-1 pl-4 text-xs", m.status !== "active" && "text-muted-foreground line-through decoration-muted-foreground/40")}>
                    {m.content}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {rows.length === 0 && !all.isLoading && <EmptyState title="No memories match" icon={Brain} />}
          <div className="border-t px-3 py-1 text-[10.5px] text-muted-foreground">{rows.length} of {all.data?.length ?? 0} memories</div>
        </Panel>
        {focus && <Inspector id={focus} key={focus} agents={agents.data ?? []} onClose={() => open(null)} onNavigate={open} />}
      </div>
      <AgentView agents={agents.data ?? []} />
      {adding && <AddMemory onDone={() => setAdding(false)} />}
    </div>
  );
}
