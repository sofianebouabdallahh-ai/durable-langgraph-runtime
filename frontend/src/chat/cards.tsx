/** Presentational cards (Pattern: container / presentational): props in, markup out. */
import { useState } from "react";

import type { Message } from "../api/messages";
import { Badge, Button, DataBlock } from "../ui/primitives";
import { errorText, helperStatusLabel, toolLabel } from "../ui/words";
import type { Helper } from "./transcript";

type Of<T extends Message["type"]> = Extract<Message, { type: T }>;

export function ToolCard({ call, result }: { call: Of<"tool_call">; result: Of<"tool_result"> | null }) {
  const [open, setOpen] = useState(false);
  const state = result === null ? "running" : result.error ? "failed" : "done";
  return (
    <div className="rounded-lg border border-slate-200 bg-white text-sm dark:border-slate-700 dark:bg-slate-900" data-testid="tool-card">
      <button
        type="button"
        onClick={() => {
          setOpen(!open);
        }}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left focus-visible:outline-2 focus-visible:outline-indigo-500"
      >
        <span aria-hidden>{state === "running" ? "⏳" : state === "failed" ? "⚠️" : "🛠️"}</span>
        <span className="font-medium">{toolLabel(call.tool)}</span>
        {state === "running" && <span className="text-slate-500">working…</span>}
        {result?.cached && <Badge tone="indigo">reused</Badge>}
        {result?.durationMs != null && <span className="ml-auto text-xs text-slate-500">{formatMs(result.durationMs)}</span>}
      </button>
      {open && (
        <div className="space-y-2 border-t border-slate-200 px-3 py-2 dark:border-slate-700">
          <div>
            <div className="mb-1 text-xs font-medium text-slate-500">Input</div>
            <DataBlock value={call.args} />
          </div>
          {result && (
            <div>
              <div className="mb-1 text-xs font-medium text-slate-500">{result.error ? "Error" : "Result"}</div>
              <DataBlock value={result.error ?? result.result} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function HelperCards({ helpers }: { helpers: Helper[] }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2" aria-label="Helpers">
      {helpers.map((h) => (
        <div key={h.handle} className="rounded-lg border border-slate-200 bg-white p-3 text-sm dark:border-slate-700 dark:bg-slate-900" data-testid="helper-card">
          <div className="flex items-center gap-2">
            <span aria-hidden>🧑‍💼</span>
            <span className="font-medium">Helper: {h.agent}</span>
            <span className="ml-auto">
              <Badge tone={h.status === "running" ? "amber" : h.status === "completed" ? "green" : "rose"}>{helperStatusLabel(h.status)}</Badge>
            </span>
          </div>
          {h.status === "running" && (
            <div className="mt-2">
              {h.progress && <div className="text-slate-600 dark:text-slate-300">{h.progress}</div>}
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={h.percent ?? undefined} aria-label={`${h.agent} progress`}>
                <div className="h-full bg-amber-500 transition-all motion-reduce:transition-none" style={{ width: `${String(h.percent ?? 10)}%` }} />
              </div>
            </div>
          )}
          {h.summary && <p className="mt-2 text-slate-700 dark:text-slate-300">{h.summary}</p>}
        </div>
      ))}
    </div>
  );
}

export function ApprovalCard({
  message,
  decided,
  pending,
  onDecide,
}: {
  message: Of<"interrupt">;
  decided: Of<"approval"> | null;
  pending: boolean;
  onDecide?: (decision: "approve" | "reject", reason: string | null) => void;
}) {
  const [reason, setReason] = useState("");
  const [sent, setSent] = useState(false);
  const what = message.tool ? toolLabel(message.tool) : "an action";
  return (
    <div className="rounded-lg border-2 border-amber-400 bg-amber-50 p-3 text-sm dark:border-amber-600 dark:bg-amber-950/30" data-testid="approval-card">
      <div className="font-medium">The assistant wants to use: {what}</div>
      {message.reason && <div className="mt-1 text-slate-600 dark:text-slate-300">{message.reason}</div>}
      <div className="mt-2">
        <DataBlock value={message.args} />
      </div>
      {decided ? (
        <div className="mt-2">
          <Badge tone={decided.decision === "approve" ? "green" : "rose"}>{decided.decision === "approve" ? "You approved this" : "You rejected this"}</Badge>
        </div>
      ) : pending && onDecide ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            disabled={sent}
            onClick={() => {
              setSent(true);
              onDecide("approve", null);
            }}
          >
            Approve
          </Button>
          <Button
            variant="danger"
            disabled={sent}
            onClick={() => {
              setSent(true);
              onDecide("reject", reason.trim() || null);
            }}
          >
            Reject
          </Button>
          <label className="flex min-w-48 flex-1 items-center gap-2">
            <span className="sr-only">Reason (optional)</span>
            <input
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
              }}
              placeholder="Reason (optional)"
              maxLength={2000}
              className="w-full rounded-md border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
            />
          </label>
        </div>
      ) : null}
    </div>
  );
}

export function ErrorNote({ message }: { message: Of<"error"> }) {
  const stopped = message.reason === "cancel_requested";
  return (
    <div role={stopped ? undefined : "alert"} className={`text-sm ${stopped ? "text-slate-500" : "text-rose-700 dark:text-rose-400"}`}>
      {errorText(message.reason, message.budgetLimited)}
    </div>
  );
}

function formatMs(ms: number): string {
  return ms < 1000 ? `${String(Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`;
}
