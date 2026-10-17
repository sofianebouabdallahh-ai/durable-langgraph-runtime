/** "What happened?": a reply's run events as a timeline, in plain words (§4.5). */
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
    .map((e) => ({ seq: e.seq, ts: e.ts, type: e.type, text: eventLine(e.type, e.payload) }))
    .filter((l): l is { seq: number; ts: string; type: string; text: string } => l.text !== null);
  return (
    <div className="rounded-xl border border-stone-200 bg-white p-4 text-sm dark:border-stone-800 dark:bg-stone-900" data-testid="what-happened">
      <ol className="relative space-y-2.5 border-l border-stone-200 pl-5 dark:border-stone-700">
        {lines.map((l) => (
          <li key={l.seq} className="relative">
            <span
              aria-hidden
              className={`absolute top-1.5 -left-[25px] size-2 rounded-full ring-4 ring-white dark:ring-stone-900 ${
                l.type === "run.reclaimed" || l.type === "run.released" ? "bg-amber-500" : l.type === "run.failed" ? "bg-rose-500" : l.type === "run.completed" ? "bg-emerald-500" : "bg-stone-300 dark:bg-stone-600"
              }`}
            />
            <span className="mr-2 font-mono text-[11px] text-stone-500 tabular-nums">{start ? `+${elapsed(start, l.ts)}` : ""}</span>
            <span className="text-stone-700 dark:text-stone-300">{l.text}</span>
          </li>
        ))}
      </ol>
      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 border-t border-stone-100 pt-3 text-xs text-stone-500 dark:border-stone-800">
        <span>Steps: {r.steps}</span>
        <span>Taken over after a crash: {r.reclaims}</span>
        <span>Handed over on shutdown: {r.releases}</span>
        <span className="ml-auto font-mono">run {r.id.slice(0, 8)}</span>
      </div>
    </div>
  );
}

function elapsed(from: string, to: string): string {
  const s = (Date.parse(to) - Date.parse(from)) / 1000;
  return s < 60 ? `${s.toFixed(1)}s` : `${String(Math.floor(s / 60))}m${String(Math.round(s % 60))}s`;
}
