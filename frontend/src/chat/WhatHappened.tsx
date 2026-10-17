/** "What happened?": a turn's run events in plain words, for the curious (R6, §4.5). */
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "../api/client";
import { Spinner } from "../ui/primitives";
import { eventLine } from "../ui/words";

export function WhatHappened({ runId, active }: { runId: string; active: boolean }) {
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => unwrap(api.GET("/runs/{run_id}", { params: { path: { run_id: runId } } })),
    refetchInterval: active ? 2000 : false,
  });
  const events = useQuery({
    queryKey: ["run-events", runId],
    queryFn: () => unwrap(api.GET("/runs/{run_id}/events", { params: { path: { run_id: runId }, query: { limit: 500 } } })),
    refetchInterval: active ? 2000 : false,
  });
  if (run.isPending || events.isPending) return <Spinner label="Loading…" />;
  if (run.isError || events.isError) return <div className="text-sm text-rose-600">Couldn't load the details.</div>;
  const r = run.data;
  const start = events.data.events[0]?.ts;
  const lines = events.data.events
    .map((e) => ({ seq: e.seq, ts: e.ts, text: eventLine(e.type, e.payload) }))
    .filter((l): l is { seq: number; ts: string; text: string } => l.text !== null);
  return (
    <div className="space-y-2 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-900" data-testid="what-happened">
      <ol className="space-y-1">
        {lines.map((l) => (
          <li key={l.seq} className="flex gap-3">
            <span className="w-14 shrink-0 text-right text-xs text-slate-500 tabular-nums">{start ? `+${elapsed(start, l.ts)}` : ""}</span>
            <span>{l.text}</span>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-200 pt-2 text-xs text-slate-500 dark:border-slate-700">
        <span>Steps: {r.steps}</span>
        <span>Taken over after a crash: {r.reclaims}</span>
        <span>Handed over on shutdown: {r.releases}</span>
        <span className="font-mono">run {r.id.slice(0, 8)}</span>
      </div>
    </div>
  );
}

function elapsed(from: string, to: string): string {
  const s = (Date.parse(to) - Date.parse(from)) / 1000;
  return s < 60 ? `${s.toFixed(1)}s` : `${String(Math.floor(s / 60))}m${String(Math.round(s % 60))}s`;
}
