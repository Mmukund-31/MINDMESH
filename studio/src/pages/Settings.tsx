import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { api, DEFAULT_KEY, getApiKey, setApiKey } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ErrorNote, KV, PageHeader } from "@/components/common";
import { timeAgo } from "@/lib/utils";

function Keys() {
  const qc = useQueryClient();
  const keys = useQuery({ queryKey: ["keys"], queryFn: api.keys, retry: false });
  const [name, setName] = useState("");
  const [role, setRole] = useState<"admin" | "read">("read");
  const [created, setCreated] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => api.createKey(name.trim(), role),
    onSuccess: (k) => {
      setCreated(k.key);
      setName("");
      qc.invalidateQueries({ queryKey: ["keys"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api.revokeKey(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>API keys</CardTitle>
        <CardDescription>
          Keys for this project. <b>admin</b> keys have full access; <b>read</b> keys can browse, preview and export but
          change nothing (CI dashboards, teammates, public demos). Revoking takes effect immediately.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) create.mutate();
          }}
        >
          <div className="min-w-40 flex-1 space-y-1">
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. ci or alice-laptop" data-testid="key-name" />
          </div>
          <div className="space-y-1">
            <Label>Role</Label>
            <Select value={role} onChange={(e) => setRole(e.target.value as "admin" | "read")} data-testid="key-role">
              <option value="read">read</option>
              <option value="admin">admin</option>
            </Select>
          </div>
          <Button type="submit" disabled={!name.trim() || create.isPending} data-testid="create-key">
            <Plus /> Create key
          </Button>
        </form>
        {created && (
          <div className="space-y-1 rounded-lg border border-success/40 bg-success/10 p-3 text-xs" data-testid="new-key">
            <div className="font-medium">Copy this key now: it is not shown again.</div>
            <div className="flex items-center gap-2">
              <code className="break-all font-mono">{created}</code>
              <Button size="icon" variant="ghost" aria-label="Copy key" onClick={() => navigator.clipboard?.writeText(created)}>
                <Copy />
              </Button>
            </div>
          </div>
        )}
        <ErrorNote error={keys.error ?? create.error ?? revoke.error} />
        {keys.data && (
          <Table data-testid="keys-table">
            <THead>
              <TR>
                <TH>Name</TH>
                <TH>Role</TH>
                <TH>Key</TH>
                <TH>Last used</TH>
                <TH />
              </TR>
            </THead>
            <TBody>
              {keys.data.map((k) => (
                <TR key={k.id}>
                  <TD>
                    {k.name} {k.current && <Badge variant="info">this browser</Badge>}
                  </TD>
                  <TD>{k.role}</TD>
                  <TD className="font-mono text-xs">{k.prefix ? `${k.prefix}…` : "—"}</TD>
                  <TD className="text-xs text-muted-foreground">{k.last_used_at ? timeAgo(k.last_used_at) : "never"}</TD>
                  <TD className="text-right">
                    <Button size="sm" variant="ghost" disabled={k.current || revoke.isPending}
                      title={k.current ? "This is the key Studio is using" : "Revoke"}
                      onClick={() => confirm(`Revoke key "${k.name}"? Clients using it stop working immediately.`) && revoke.mutate(k.id)}
                      aria-label={`Revoke ${k.name}`}>
                      <Trash2 />
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

export default function Settings() {
  const qc = useQueryClient();
  const [key, setKey] = useState(getApiKey());
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const save = () => {
    setApiKey(key.trim());
    qc.invalidateQueries();
  };
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <PageHeader title="API key & project" description="Studio talks to the MindMesh API with a project-scoped key." icon={KeyRound} />
      <Card>
        <CardHeader>
          <CardTitle>Connection</CardTitle>
          <CardDescription>
            Each key maps to exactly one project; all data shown is isolated to it. Create projects and keys with{" "}
            <code>mindmesh projects create &lt;name&gt;</code> and <code>mindmesh keys create</code>.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <Label>API key</Label>
            <Input value={key} onChange={(e) => setKey(e.target.value)} type="password" className="font-mono" />
            <p className="text-[11px] text-muted-foreground">Stored in this browser only. Default for this deployment: {DEFAULT_KEY}</p>
          </div>
          <div className="flex gap-2">
            <Button onClick={save}>Save & reconnect</Button>
            <Button variant="ghost" onClick={() => setKey(DEFAULT_KEY)}>Use default key</Button>
          </div>
          <ErrorNote error={me.error} />
          {me.data && (
            <div className="rounded-lg border p-3">
              <KV k="project">{me.data.project_name}</KV>
              <KV k="project id">{me.data.project_id}</KV>
              <KV k="access">{me.data.role === "read" ? "read-only" : "full (admin)"}</KV>
            </div>
          )}
        </CardContent>
      </Card>
      {me.data?.role === "admin" && <Keys />}
    </div>
  );
}
