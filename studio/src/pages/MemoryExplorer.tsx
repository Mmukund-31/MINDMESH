import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Brain, GitBranch, History, Pencil, Plus, Search, Trash2, Eye } from "lucide-react";
import { api } from "@/lib/api";
import type { Memory } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, ErrorNote, KV, Mono, PageHeader, ScoreBar, StatusBadge } from "@/components/common";
import { ReceiptPanel, REASON_TEXT } from "@/components/ReceiptPanel";
import { cn, shortId, timeAgo } from "@/lib/utils";

function MemoryDrawer({ id, onClose, onNavigate }: { id: string; onClose: () => void; onNavigate: (id: string) => void }) {
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
    qc.invalidateQueries({ queryKey: ["memories"] });
    qc.invalidateQueries({ queryKey: ["conflicts"] });
    qc.invalidateQueries({ queryKey: ["memory"] });
    qc.invalidateQueries({ queryKey: ["versions"] });
    setMode("view");
    setReason("");
    if (next && next.id !== id) onNavigate(next.id);
  };
  const save = useMutation({
    mutationFn: () =>
      api.updateMemory(id, {
        ...(content !== m.data?.content ? { content } : {}),
        ...(scope !== m.data?.scope ? { scope } : {}),
        ...(trust !== m.data?.trust ? { trust } : {}),
        reason: reason || undefined,
        edited_by: "studio-user",
      }),
    onSuccess: refresh,
  });
  const retract = useMutation({ mutationFn: () => api.retractMemory(id, reason), onSuccess: () => refresh() });
  const mem = m.data;

  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent>
        {!mem ? (
          <ErrorNote error={m.error} />
        ) : (
          <>
            <SheetTitle className="flex items-center gap-2">
              {mem.subject_key ?? "memory"} <Badge variant="outline">v{mem.version}</Badge> <StatusBadge status={mem.status} />
            </SheetTitle>
            <SheetDescription>
              <Mono>{mem.id}</Mono> · {mem.kind} · scope <b>{mem.scope}</b>
            </SheetDescription>
            <p className="rounded-lg border bg-card p-3 text-sm leading-relaxed">{mem.content}</p>
            {mem.status_reason && <p className="text-xs text-muted-foreground">status: {mem.status_reason}</p>}

            {mode === "view" && mem.status === "active" && (
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => setMode("edit")} data-testid="edit-memory">
                  <Pencil /> Edit (new version)
                </Button>
                <Button size="sm" variant="outline" onClick={() => setMode("retract")} data-testid="retract-memory">
                  <Trash2 /> Retract
                </Button>
              </div>
            )}
            {mode === "edit" && (
              <Card className="space-y-2 p-3">
                <Label>Content</Label>
                <Textarea value={content} onChange={(e) => setContent(e.target.value)} rows={4} />
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label>Scope</Label>
                    <Input value={scope} onChange={(e) => setScope(e.target.value)} data-testid="scope-input" />
                  </div>
                  <div className="space-y-1">
                    <Label>Trust ({trust.toFixed(2)})</Label>
                    <input type="range" min={0} max={1} step={0.05} value={trust} onChange={(e) => setTrust(Number(e.target.value))} className="w-full" />
                  </div>
                </div>
                <Label>Reason for change (kept in provenance)</Label>
                <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. policy applies to all agents" />
                <ErrorNote error={save.error} />
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
                  <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending} data-testid="save-memory">
                    Save as v{mem.version + 1}
                  </Button>
                </div>
              </Card>
            )}
            {mode === "retract" && (
              <Card className="space-y-2 p-3">
                <Label>Why is this memory wrong or unsafe?</Label>
                <Input value={reason} onChange={(e) => setReason(e.target.value)} />
                <ErrorNote error={retract.error} />
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
                  <Button size="sm" variant="destructive" disabled={!reason || retract.isPending} onClick={() => retract.mutate()}>
                    Retract
                  </Button>
                </div>
              </Card>
            )}

            <Tabs defaultValue="provenance">
              <TabsList>
                <TabsTrigger value="provenance">Provenance</TabsTrigger>
                <TabsTrigger value="versions">
                  <GitBranch /> Versions ({versions.data?.length ?? "…"})
                </TabsTrigger>
                <TabsTrigger value="retrievals">
                  <History /> Retrievals ({retrievals.data?.length ?? "…"})
                </TabsTrigger>
              </TabsList>
              <TabsContent value="provenance">
                <KV k="source">{mem.source_type}{mem.source_ref ? ` · ${mem.source_ref}` : ""}</KV>
                <KV k="created by">{mem.created_by}</KV>
                <KV k="from run">{mem.run_id ? <Link className="text-primary hover:underline" to={`/runs/${mem.run_id}`}>{shortId(mem.run_id)}</Link> : "–"}</KV>
                <KV k="valid from">{new Date(mem.valid_from).toLocaleString()}</KV>
                <KV k="expires">{mem.expires_at ? new Date(mem.expires_at).toLocaleString() : "never"}</KV>
                <KV k="trust / importance">{mem.trust.toFixed(2)} / {mem.importance.toFixed(2)}</KV>
                <KV k="tags">{mem.tags.join(", ") || "–"}</KV>
                <KV k="supersedes">{mem.supersedes_id ? <button className="text-primary hover:underline" onClick={() => onNavigate(mem.supersedes_id!)}>{shortId(mem.supersedes_id)}</button> : "–"}</KV>
              </TabsContent>
              <TabsContent value="versions">
                <ol className="relative space-y-3 border-l pl-4">
                  {versions.data?.slice().reverse().map((v) => (
                    <li key={v.id} className="relative">
                      <span className={cn("absolute -left-[21px] top-1 size-2.5 rounded-full border-2 border-background", v.status === "active" ? "bg-success" : "bg-muted-foreground")} />
                      <button className={cn("w-full rounded-md border p-2 text-left hover:bg-muted/50", v.id === id && "border-primary/50")} onClick={() => onNavigate(v.id)}>
                        <div className="flex items-center gap-2 text-xs">
                          <b>v{v.version}</b> <StatusBadge status={v.status} /> <Badge variant="outline">{v.scope}</Badge>
                          <span className="ml-auto text-muted-foreground">{timeAgo(v.created_at)} · {v.created_by}</span>
                        </div>
                        <p className="mt-1 line-clamp-2 text-xs">{v.content}</p>
                        {v.status_reason && <p className="mt-0.5 text-[10.5px] text-muted-foreground">{v.status_reason}</p>}
                      </button>
                    </li>
                  ))}
                </ol>
              </TabsContent>
              <TabsContent value="retrievals">
                {retrievals.data?.length === 0 && <EmptyState title="Never retrieved yet" />}
                <ul className="space-y-1.5">
                  {retrievals.data?.map((r) => (
                    <li key={r.id} className="rounded-md border p-2 text-xs" data-testid="retrieval-row">
                      <div className="flex items-center gap-2">
                        {r.included ? <Badge variant="success">included</Badge> : <Badge variant="destructive">excluded: {r.reason}</Badge>}
                        <span className="text-muted-foreground">score {r.score.toFixed(2)}</span>
                        {r.run_id && <Link className="ml-auto font-mono text-primary hover:underline" to={`/runs/${r.run_id}`}>{shortId(r.run_id)}</Link>}
                      </div>
                      {r.reason && <div className="mt-0.5 text-muted-foreground">{REASON_TEXT[r.reason]}</div>}
                      <div className="mt-0.5 line-clamp-1 text-muted-foreground">query: {r.query}</div>
                    </li>
                  ))}
                </ul>
              </TabsContent>
            </Tabs>
          </>
        )}
      </SheetContent>
    </Sheet>
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

function ContextPreview() {
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const [agent, setAgent] = useState("support");
  const [query, setQuery] = useState("Customer C-1042 requests a refund for order A-7731 refund policy");
  const m = useMutation({ mutationFn: () => api.previewContext({ query, agent }) });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Eye className="size-4" /> What would the agent see?</CardTitle>
        <CardDescription>Dry-run the context engine for an agent and query (not recorded).</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex gap-2">
          <Select value={agent} onChange={(e) => setAgent(e.target.value)}>
            {(agents.data ?? []).map((a) => <option key={a.name}>{a.name}</option>)}
          </Select>
          <Input value={query} onChange={(e) => setQuery(e.target.value)} />
          <Button variant="outline" onClick={() => m.mutate()} data-testid="preview-context">Preview</Button>
        </div>
        <ErrorNote error={m.error} />
        {m.data && <ReceiptPanel receipt={m.data} />}
      </CardContent>
    </Card>
  );
}

export default function MemoryExplorer() {
  const [params, setParams] = useSearchParams();
  const focus = params.get("focus");
  const [q, setQ] = useState("");
  const [semantic, setSemantic] = useState(false);
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [adding, setAdding] = useState(false);
  const list = useQuery({
    queryKey: ["memories", q, semantic, status, kind],
    queryFn: async () =>
      semantic && q
        ? (await api.searchMemories(q, true)).map((h) => ({ ...h.memory, _rel: h.relevance }))
        : (await api.memories({ q, status, kind, limit: 500 })).map((m) => ({ ...m, _rel: undefined as number | undefined })),
  });
  const conflicts = useQuery({ queryKey: ["conflicts"], queryFn: api.conflicts });
  const open = (id: string | null) => {
    const p = new URLSearchParams(params);
    if (id) p.set("focus", id);
    else p.delete("focus");
    setParams(p, { replace: true });
  };
  const rows = (list.data ?? []).filter((m) => (!status || m.status === status) && (!kind || m.kind === kind));

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <PageHeader
        title="Memory Explorer"
        description="Search, inspect, edit, version and retract memories — with provenance and retrieval history."
        icon={Brain}
        actions={<Button onClick={() => setAdding(true)}><Plus /> Add memory</Button>}
      />
      {conflicts.data && conflicts.data.length > 0 && (
        <Card className="border-warning/50 bg-warning/5" data-testid="conflicts">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-warning"><AlertTriangle className="size-4" /> {conflicts.data.length} conflicting subject(s)</CardTitle>
            <CardDescription>Active memories disagree about the same subject across scopes. Resolve by editing scope/content or retracting the loser.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {conflicts.data.map((c) => (
              <div key={c.subject_key} className="space-y-1">
                <div className="text-xs font-semibold">{c.subject_key} <span className="font-normal text-muted-foreground">· suggested winner by {c.rule}</span></div>
                {c.memories.map((m) => (
                  <button key={m.id} onClick={() => open(m.id)} className="flex w-full items-start gap-2 rounded-md border bg-card p-2 text-left text-xs hover:bg-muted/50">
                    {m.id === c.suggested_winner ? <Badge variant="success">winner</Badge> : <Badge variant="outline">loser</Badge>}
                    <Badge variant="outline">{m.scope}</Badge>
                    <span className="flex-1">{m.content}</span>
                    <span className="text-muted-foreground">trust {m.trust}</span>
                  </button>
                ))}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      <Card>
        <CardContent className="space-y-3 pt-4">
          <div className="flex flex-wrap gap-2">
            <div className="relative min-w-60 flex-1">
              <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={semantic ? "Semantic search (vector + keyword)…" : "Filter by text or subject…"} className="pl-8" data-testid="memory-search" />
            </div>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input type="checkbox" checked={semantic} onChange={(e) => setSemantic(e.target.checked)} /> semantic
            </label>
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">any status</option>
              {["active", "superseded", "retracted", "expired"].map((s) => <option key={s}>{s}</option>)}
            </Select>
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">any kind</option>
              {["fact", "episode", "decision", "strategy"].map((s) => <option key={s}>{s}</option>)}
            </Select>
          </div>
          <ErrorNote error={list.error} />
          <Table>
            <THead>
              <TR>
                <TH>Subject</TH><TH>Content</TH><TH>Scope</TH><TH>Status</TH><TH>Ver</TH><TH>Trust</TH><TH>Used</TH><TH>Source</TH><TH>Age</TH>
              </TR>
            </THead>
            <TBody>
              {rows.map((m) => (
                <TR key={m.id} onClick={() => open(m.id)} className="cursor-pointer" data-active={focus === m.id} data-testid="memory-row">
                  <TD className="font-medium whitespace-nowrap">{m.subject_key ?? <span className="text-muted-foreground">{m.kind}</span>}</TD>
                  <TD className="max-w-md"><div className={cn("line-clamp-2 text-xs", m.status !== "active" && "text-muted-foreground line-through decoration-muted-foreground/40")}>{m.content}</div></TD>
                  <TD><Badge variant={m.scope === "project" ? "outline" : "info"}>{m.scope}</Badge></TD>
                  <TD><StatusBadge status={m.status} /></TD>
                  <TD className="text-xs">v{m.version}</TD>
                  <TD><ScoreBar value={m.trust} /></TD>
                  <TD className="text-xs tabular-nums">{m._rel !== undefined ? `rel ${m._rel.toFixed(2)}` : m.retrieval_count}</TD>
                  <TD className="max-w-40 truncate text-xs text-muted-foreground">{m.source_ref ?? m.source_type}</TD>
                  <TD className="whitespace-nowrap text-xs text-muted-foreground">{timeAgo(m.created_at)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {rows.length === 0 && !list.isLoading && <EmptyState title="No memories match" icon={Brain} />}
        </CardContent>
      </Card>
      <ContextPreview />
      {focus && <MemoryDrawer id={focus} onClose={() => open(null)} onNavigate={open} />}
      {adding && <AddMemory onDone={() => setAdding(false)} />}
    </div>
  );
}
