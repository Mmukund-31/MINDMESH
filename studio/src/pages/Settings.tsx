import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { api, DEFAULT_KEY, getApiKey, setApiKey } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { ErrorNote, KV, PageHeader } from "@/components/common";

export default function Settings() {
  const qc = useQueryClient();
  const [key, setKey] = useState(getApiKey());
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const save = () => {
    setApiKey(key.trim());
    qc.invalidateQueries();
  };
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="API key & project" description="Studio talks to the MindMesh API with a project-scoped key." icon={KeyRound} />
      <Card>
        <CardHeader>
          <CardTitle>Connection</CardTitle>
          <CardDescription>
            Each key maps to exactly one project; all data shown is isolated to it. Create keys with{" "}
            <code>mindmesh create-key --project &lt;name&gt;</code>.
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
    </div>
  );
}
