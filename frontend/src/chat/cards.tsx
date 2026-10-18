/** Presentational cards (Pattern: container / presentational): props in, markup out. */
import { AlertTriangle, Check, ChevronDown, CircleStop, Hand, Hourglass, Users } from "lucide-react";
import { type ReactNode, useState } from "react";

import type { Message } from "../api/messages";
import { ToolIcon } from "../ui/icons";
import { Avatar, Button, DataBlock, Pill } from "../ui/primitives";
import { agentLabel, approvalReason, errorText, helperStatusLabel, toolLabel } from "../ui/words";
import type { Helper } from "./transcript";

type Of<T extends Message["type"]> = Extract<Message, { type: T }>;

/** Consecutive tool steps share one frame. */
export function StepList({ children }: { children: ReactNode }) {
  return (
    <div className="divide-y divide-stone-100 overflow-hidden rounded-xl border border-stone-200 bg-white dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900">
      {children}
    </div>
  );
}

export function ToolCard({
  call,
  result,
  awaitingApproval = false,
}: {
  call: Of<"tool_call">;
  result: Of<"tool_result"> | null;
  awaitingApproval?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const state = result === null ? (awaitingApproval ? "held" : "running") : result.error ? "failed" : "done";
  return (
    <div data-testid="tool-card">
      <button
        type="button"
        onClick={() => {
          setOpen(!open);
        }}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm transition hover:bg-stone-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-sun-500 dark:hover:bg-stone-800/50"
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-300">
          <ToolIcon tool={call.tool} className="size-3.5" />
        </span>
        <span className="font-medium text-stone-800 dark:text-stone-200">{toolLabel(call.tool)}</span>
        {state === "running" && <span className="text-stone-500">working…</span>}
        {state === "held" && <span className="text-amber-600 dark:text-amber-400">waiting for your OK</span>}
        {result?.cached && <Pill tone="blue">reused</Pill>}
        <span className="ml-auto flex items-center gap-2 text-xs text-stone-500">
          {result?.durationMs != null && <span className="tabular-nums">{formatMs(result.durationMs)}</span>}
          {state === "done" && <Check aria-hidden className="size-4 text-emerald-500" />}
          {state === "failed" && <AlertTriangle aria-hidden className="size-4 text-amber-500" />}
          {state === "held" && <Hourglass aria-hidden className="size-4 text-amber-500" />}
          {state === "running" && <span aria-hidden className="size-3.5 animate-spin rounded-full border-2 border-stone-300 border-t-sun-500 motion-reduce:animate-none" />}
          <ChevronDown aria-hidden className={`size-4 transition ${open ? "rotate-180" : ""}`} />
        </span>
      </button>
      {open && (
        <div className="grid gap-3 border-t border-stone-100 bg-stone-50/50 px-3 py-3 sm:grid-cols-2 dark:border-stone-800 dark:bg-stone-950/30">
          <div>
            <div className="mb-1.5 text-[11px] font-semibold tracking-wider text-stone-500 uppercase">Input</div>
            <DataBlock value={call.args} />
          </div>
          {result && (
            <div>
              <div className="mb-1.5 text-[11px] font-semibold tracking-wider text-stone-500 uppercase">{result.error ? "Error" : "Result"}</div>
              <DataBlock value={result.error ?? result.result} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function HelperCards({ helpers }: { helpers: Helper[] }) {
  const working = helpers.filter((h) => h.status === "running").length;
  const count = (n: number) => `${String(n)} helper${n === 1 ? "" : "s"}`;
  return (
    <div aria-label="Helpers" className="@container">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-stone-500">
        <Users aria-hidden className="size-3.5" />
        {working > 0 ? `${count(working)} working${working > 1 ? " in parallel" : ""}` : `${count(helpers.length)} finished`}
      </div>
      <div className="grid gap-2.5 @lg:grid-cols-2">
        {helpers.map((h) => (
          <div key={h.handle} className="rounded-xl border border-stone-200 bg-white p-3.5 text-sm shadow-soft dark:border-stone-800 dark:bg-stone-900" data-testid="helper-card">
            <div className="flex items-center gap-2.5">
              <Avatar name={agentLabel(h.agent)} size="sm" />
              <span className="font-medium">Helper: {agentLabel(h.agent)}</span>
              <span className="ml-auto">
                <Pill tone={h.status === "running" ? "sun" : h.status === "completed" ? "green" : "rose"}>{helperStatusLabel(h.status)}</Pill>
              </span>
            </div>
            {h.status === "running" && (
              <div className="mt-3">
                {h.progress && <div className="mb-1.5 text-[13px] text-stone-600 dark:text-stone-300">{h.progress}</div>}
                <div
                  className="h-1 overflow-hidden rounded-full bg-stone-100 dark:bg-stone-800"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={h.percent ?? undefined}
                  aria-label={`${h.agent} progress`}
                >
                  <div className="bg-brand h-full rounded-full transition-all duration-500 motion-reduce:transition-none" style={{ width: `${String(h.percent ?? 12)}%` }} />
                </div>
              </div>
            )}
            {h.summary && <p className="mt-2.5 text-[13px] leading-relaxed text-stone-600 dark:text-stone-300">{h.summary}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ApprovalCard({
  message,
  decided,
  pending,
  agent,
  onDecide,
}: {
  message: Of<"interrupt">;
  decided: Of<"approval"> | null;
  pending: boolean;
  agent?: string | null;
  onDecide?: (decision: "approve" | "reject", reason: string | null) => void;
}) {
  const [reason, setReason] = useState("");
  const [sent, setSent] = useState(false);
  const what = message.tool ? toolLabel(message.tool) : "an action";
  const live = !decided && pending && onDecide;
  return (
    <div
      className={`overflow-hidden rounded-2xl border bg-white text-sm dark:bg-stone-900 ${live ? "border-amber-300 shadow-lift ring-4 ring-amber-100 dark:border-amber-700 dark:ring-amber-900/30" : "border-stone-200 dark:border-stone-800"}`}
      data-testid="approval-card"
    >
      <div className="flex items-start gap-3 p-4">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
          <Hand aria-hidden className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-semibold tracking-wider text-amber-700 uppercase dark:text-amber-400">Needs your approval</div>
          <div className="mt-0.5 font-medium text-stone-900 dark:text-stone-100">
            {agent ?? agentLabel(agent)} wants to use: {what}
          </div>
          <div className="mt-1 text-stone-500 dark:text-stone-400">{approvalReason(message.reason)}</div>
          <div className="mt-3">
            <DataBlock value={message.args} />
          </div>
        </div>
      </div>
      {decided ? (
        <div className="border-t border-stone-100 px-4 py-2.5 dark:border-stone-800">
          <Pill tone={decided.decision === "approve" ? "green" : "rose"}>{decided.decision === "approve" ? "You approved this" : "You rejected this"}</Pill>
        </div>
      ) : live ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-amber-100 bg-amber-50/50 px-4 py-3 dark:border-amber-900/40 dark:bg-amber-950/20">
          <Button
            variant="primary"
            size="sm"
            disabled={sent}
            onClick={() => {
              setSent(true);
              onDecide("approve", null);
            }}
          >
            <Check aria-hidden className="size-4" /> Approve
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={sent}
            onClick={() => {
              setSent(true);
              onDecide("reject", reason.trim() || null);
            }}
          >
            Reject
          </Button>
          <label className="min-w-48 flex-1">
            <span className="sr-only">Reason (optional)</span>
            <input
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
              }}
              placeholder="Reason (optional)"
              maxLength={2000}
              className="h-8 w-full rounded-lg border border-stone-200 bg-white px-2.5 text-[13px] placeholder:text-stone-400 focus:border-sun-400 focus:ring-2 focus:ring-sun-100 focus:outline-none dark:border-stone-700 dark:bg-stone-900"
            />
          </label>
        </div>
      ) : null}
    </div>
  );
}

export function ErrorNote({ message }: { message: Of<"error"> }) {
  if (message.reason === "cancel_requested") {
    return (
      <div className="inline-flex items-center gap-1.5 text-sm text-stone-500">
        <CircleStop aria-hidden className="size-4" /> {errorText(message.reason, message.budgetLimited)}
      </div>
    );
  }
  return (
    <div role="alert" className="flex items-start gap-2 rounded-xl bg-rose-50 px-3.5 py-2.5 text-sm text-rose-800 ring-1 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900">
      <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
      {errorText(message.reason, message.budgetLimited)}
    </div>
  );
}

function formatMs(ms: number): string {
  return ms < 1000 ? `${String(Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`;
}
