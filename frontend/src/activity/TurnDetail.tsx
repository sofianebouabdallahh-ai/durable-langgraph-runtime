/** One turn (Activity → a turn): its outcome, its model calls per model, and its timeline. */
import { ArrowLeft, ArrowRight } from "lucide-react";

import { ApiError } from "../api/client";
import { href } from "../app/route";
import { WhatHappened } from "../chat/WhatHappened";
import { Pill, Spinner } from "../ui/primitives";
import { agentLabel, failureReason } from "../ui/words";
import { Cost, money, seconds } from "./ActivityPage";
import { useTurn } from "./api";
import { compact } from "./charts";

export function TurnDetail({ runId }: { runId: string }) {
  const turn = useTurn(runId);
  const t = turn.data;
  return (
    <div className="mx-auto max-w-4xl px-6 py-10" data-testid="turn-detail">
      <a href={href({ page: "activity" })} className="inline-flex items-center gap-1 text-sm text-stone-500 hover:text-stone-900 dark:hover:text-stone-100">
        <ArrowLeft aria-hidden className="size-4" /> Activity
      </a>
      {turn.isError && (
        <p className="mt-6 text-rose-600">{turn.error instanceof ApiError && turn.error.status === 404 ? "There's no such turn." : `Couldn't load the turn: ${turn.error.message}`}</p>
      )}
      {!t ? (
        !turn.isError && <Spinner className="mt-10" label="Loading the turn…" />
      ) : (
        <>
          <h1 className="mt-3 font-display text-3xl font-medium tracking-tight">
            {agentLabel(t.agent)}
            {t.agent_version ? <span className="text-stone-400"> v{t.agent_version}</span> : null}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-stone-500">
            {t.status === "completed" ? <Pill tone="green">Done</Pill> : t.status === "failed" ? <Pill tone="rose">{failureReason(t.reason)}</Pill> : <Pill>{t.status}</Pill>}
            <span>{new Date(t.created_at).toLocaleString()}</span>
            <span>{seconds(t.duration_s)}</span>
            <span>{t.steps} steps · {t.tool_calls} tool calls · {t.model_calls} model calls</span>
            <span>{compact(t.tokens)} tokens · {money(t.cost)}</span>
            {t.reclaims > 0 && <span className="text-amber-600">taken over after a crash ×{t.reclaims}</span>}
            {t.session_id && (
              <a href={href({ page: "chat", sessionId: t.session_id })} className="ml-auto inline-flex items-center gap-1 font-medium text-stone-700 underline-offset-2 hover:underline dark:text-stone-300">
                Open the chat <ArrowRight aria-hidden className="size-3.5" />
              </a>
            )}
          </div>

          {t.usage.length > 0 && (
            <table className="mt-6 w-full text-sm" data-testid="turn-models">
              <thead>
                <tr className="text-left text-xs text-stone-500">
                  <th className="py-2 pr-4 font-medium">Model</th><th className="py-2 pr-4 font-medium">Calls</th><th className="py-2 pr-4 font-medium">Tokens in · out</th><th className="py-2 pr-4 font-medium">Time</th><th className="py-2 pr-4 font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {t.usage.map((u) => (
                  <tr key={u.model} className="border-t border-stone-100 tabular-nums dark:border-stone-800">
                    <td className="py-2 pr-4 font-mono text-[13px]">{u.model}</td>
                    <td className="py-2 pr-4">{u.calls}</td>
                    <td className="py-2 pr-4">{compact(u.tokens_in)} · {compact(u.tokens_out)}</td>
                    <td className="py-2 pr-4">{seconds(u.duration_ms / 1000)}</td>
                    <td className="py-2 pr-4">
                      <Cost value={u.cost} estimated={u.estimated} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h2 className="mt-8 mb-3 font-display text-lg font-medium">What happened</h2>
          <WhatHappened runId={runId} active={t.status === "running" || t.status === "queued"} />
        </>
      )}
    </div>
  );
}
