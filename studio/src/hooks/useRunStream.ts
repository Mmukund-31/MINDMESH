import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { streamUrl } from "@/lib/api";
import type { MMEvent, Run } from "@/lib/types";

/** Subscribes to a run's server-sent events while it is live; refreshes cached queries on change. */
export function useRunStream(run: Run | undefined) {
  const qc = useQueryClient();
  const [live, setLive] = useState(false);
  const [events, setEvents] = useState<MMEvent[]>([]);
  const runId = run?.id;
  const active = run && ["pending", "running"].includes(run.status);
  const lastSeq = useRef(0);

  useEffect(() => {
    setEvents([]);
    lastSeq.current = 0;
  }, [runId]);

  useEffect(() => {
    if (!runId || !active || typeof EventSource === "undefined") return;
    let es: EventSource | undefined;
    let cancelled = false;
    const refresh = () => {
      qc.invalidateQueries({ queryKey: ["trace", runId] });
      qc.invalidateQueries({ queryKey: ["runs"] });
    };
    streamUrl(runId, lastSeq.current)
      .then((url) => {
        if (cancelled) return;
        es = new EventSource(url);
        setLive(true);
        es.addEventListener("event", (m) => {
          const ev = JSON.parse((m as MessageEvent).data) as MMEvent;
          lastSeq.current = Math.max(lastSeq.current, ev.seq);
          setEvents((prev) => [...prev, ev]);
          qc.invalidateQueries({ queryKey: ["trace", runId] });
        });
        es.addEventListener("run", refresh);
        const stop = () => {
          es?.close();
          setLive(false);
          refresh();
        };
        es.addEventListener("end", stop);
        es.addEventListener("timeout", stop);
        // tokens are single-connection: let the query refetch instead of EventSource's auto-reconnect
        es.onerror = stop;
      })
      .catch(() => {
        /* no stream token (auth/network): queries still poll */
      });
    return () => {
      cancelled = true;
      es?.close();
      setLive(false);
    };
  }, [runId, active, qc]);

  return { live, events };
}
