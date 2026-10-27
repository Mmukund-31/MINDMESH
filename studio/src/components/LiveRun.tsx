import { useEffect, useRef, type ElementType } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Bot, CheckCircle2, Circle, Cpu, History, Info, Radio, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { MODE_TEXT, modelName, narrate, runMode, type Tone } from "@/lib/narrate";
import type { MMEvent, Run } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/common";
import { useRunStream } from "@/hooks/useRunStream";
import { cn, shortId } from "@/lib/utils";

const MODE_STYLE = {
  demo: { variant: "info", icon: Bot },
  live: { variant: "default", icon: Cpu },
  replay: { variant: "warning", icon: History },
} as const;

/** Labels a run as demo (scripted model), live model or replay. */
export function RunModeBadge({ run, className }: { run: { kind: string; model?: string | null }; className?: string }) {
  const mode = runMode(run);
  const { variant, icon: Icon } = MODE_STYLE[mode];
  const text = mode === "live" ? `${MODE_TEXT.live.label} · ${modelName(run.model)}` : MODE_TEXT[mode].label;
  return (
    <Badge variant={variant} className={className} title={MODE_TEXT[mode].help} data-testid={`mode-${mode}`}>
      <Icon /> {text}
    </Badge>
  );
}

const TONE: Record<Tone, { icon: ElementType; className: string }> = {
  info: { icon: Info, className: "text-info" },
  good: { icon: CheckCircle2, className: "text-success" },
  bad: { icon: XCircle, className: "text-destructive" },
  warn: { icon: AlertTriangle, className: "text-warning" },
  muted: { icon: Circle, className: "text-muted-foreground" },
};

/** Plain-language event log; follows the newest line while a run streams. */
export function EventFeed({ events, live, className }: { events: MMEvent[]; live?: boolean; className?: string }) {
  const end = useRef<HTMLDivElement>(null);
  const lines = events.map((e) => ({ e, n: narrate(e) })).filter((x) => x.n);
  useEffect(() => {
    if (live) end.current?.scrollIntoView({ block: "nearest" });
  }, [lines.length, live]);
  return (
    <div className={cn("max-h-80 space-y-1 overflow-auto pr-1", className)} data-testid="event-feed">
      {lines.map(({ e, n }) => {
        const { icon: Icon, className: tone } = TONE[n!.tone];
        return (
          <div key={e.id} className="flex items-start gap-2 text-xs" data-testid="feed-line">
            <Icon className={cn("mt-0.5 size-3.5 shrink-0", tone)} />
            <div className="min-w-0">
              <div className={cn("break-words", n!.tone === "muted" && "text-muted-foreground")}>{n!.text}</div>
              {n!.detail && <div className="break-words text-[11px] text-muted-foreground">{n!.detail}</div>}
            </div>
          </div>
        );
      })}
      {lines.length === 0 && <div className="text-xs text-muted-foreground">Waiting for the first event…</div>}
      <div ref={end} />
    </div>
  );
}

/** Polls a run while it is active (["runs", "one", id] is refreshed by the stream's run messages). */
export function useLiveRun(runId: string | undefined) {
  const run = useQuery({
    queryKey: ["runs", "one", runId],
    queryFn: () => api.run(runId!),
    enabled: !!runId,
    refetchInterval: (q) => (q.state.data && ["pending", "running"].includes(q.state.data.status) ? 1000 : false),
  });
  const { live, events: streamed } = useRunStream(run.data);
  const stored = useQuery({
    queryKey: ["events", runId, run.data?.status],
    queryFn: () => api.events(runId!),
    enabled: !!runId && !live,
  });
  // Streamed events while live; the stored log afterwards (complete even if the stream was missed).
  const events = live || !stored.data ? streamed : stored.data;
  return { run: run.data, events, live, error: run.error };
}

/** A run's live narration, status and answer: what the guided experiment shows while the agent works. */
export function LiveRun({ runId, title, expect }: { runId: string; title?: string; expect?: (r: Run) => boolean }) {
  const { run, events, live } = useLiveRun(runId);
  if (!run) return <div className="h-24 animate-pulse rounded-lg bg-muted/50" />;
  const done = !["pending", "running"].includes(run.status);
  const answer = run.result?.answer ?? run.error;
  const ok = done && expect ? expect(run) : undefined;
  return (
    <div
      className="space-y-2 rounded-lg border p-3"
      data-testid={`live-run-${run.label?.startsWith("experiment:") ? run.label : run.kind}`}
    >
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        {title && <span className="font-medium">{title}</span>}
        <RunModeBadge run={{ kind: run.kind, model: run.config.agent_spec?.model }} />
        <StatusBadge status={run.status} />
        {live && (
          <Badge variant="info">
            <Radio className="animate-pulse" /> streaming
          </Badge>
        )}
        <Link to={`/runs/${run.id}`} className="ml-auto font-mono text-[11px] text-primary hover:underline">
          {shortId(run.id)} · full trace
        </Link>
      </div>
      <EventFeed events={events} live={live} className="max-h-56" />
      {done && answer && (
        <div
          className={cn(
            "rounded-md border p-2 text-sm font-medium",
            ok === true && "border-success/40 bg-success/8",
            ok === false && "border-destructive/40 bg-destructive/8",
          )}
          data-testid="live-answer"
        >
          {answer}
        </div>
      )}
    </div>
  );
}
