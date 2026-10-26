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
    const es = new EventSource(streamUrl(runId, lastSeq.current));
    setLive(true);
    es.addEventListener("event", (m) => {
      const ev = JSON.parse((m as MessageEvent).data) as MMEvent;
      lastSeq.current = Math.max(lastSeq.current, ev.seq);
      setEvents((prev) => [...prev, ev]);
      qc.invalidateQueries({ queryKey: ["trace", runId] });
    });
    es.addEventListener("run", () => {
      qc.invalidateQueries({ queryKey: ["trace", runId] });
      qc.invalidateQueries({ queryKey: ["runs"] });
    });
    const stop = () => {
      es.close();
      setLive(false);
      qc.invalidateQueries({ queryKey: ["trace", runId] });
      qc.invalidateQueries({ queryKey: ["runs"] });
    };
    es.addEventListener("end", stop);
    es.onerror = stop;
    return () => {
      es.close();
      setLive(false);
    };
  }, [runId, active, qc]);

  return { live, events };
}
