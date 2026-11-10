/** The chat for one session (R12.11): the container that wires data to the cards. */
import { useQuery } from "@tanstack/react-query";
import { Download, Info, Loader2, WifiOff } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { api, API_BASE, ApiError, unwrap } from "../api/client";
import type { Message } from "../api/messages";
import { sendMessage } from "../api/send";
import type { ConnectionState } from "../stream/connection";
import type { TurnStatus } from "../stream/events";
import { Markdown } from "../ui/Markdown";
import { Avatar, Typing } from "../ui/primitives";
import { agentLabel, turnLabel } from "../ui/words";
import { ApprovalCard, ErrorNote, HelperCards, RetriedNote, StepList, ToolCard } from "./cards";
import { Composer } from "./Composer";
import { problemText } from "./problems";
import { type Item, pendingApprovals, type TurnView, turns } from "./selectors";
import { isBusy } from "./transcript";
import { useChat } from "./useChat";
import { ReplyRating } from "./ReplyRating";
import { WhatHappened } from "./WhatHappened";

type Interrupt = Extract<Message, { type: "interrupt" }>;
type Decide = (request: Interrupt, decision: "approve" | "reject", reason: string | null) => void;

/** An agent's display name: from the agents list ("Nuria", "Trip planner"), else its id. */
export function useAgentName(name: string | null): string {
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => unwrap(api.GET("/agents")), staleTime: 30_000 });
  return agents.data?.find((a) => a.name === name)?.display_name ?? agentLabel(name);
}

/** Is it one of your own agents (Studio)? Only those have tests a reply can become (H6). */
function useIsOwnAgent(name: string | null): boolean {
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => unwrap(api.GET("/agents")), staleTime: 30_000 });
  return agents.data?.find((a) => a.name === name)?.source === "user";
}

export function ChatView({
  sessionId,
  compact = false,
  agentName,
  onTurnEnd,
}: {
  sessionId: string;
  compact?: boolean;
  agentName?: string;
  onTurnEnd?: () => void; // e.g. the Studio: a finished test reply marks the draft tested
}) {
  const { state, dispatch, connection } = useChat(sessionId);
  const [notice, setNotice] = useState<string | null>(null);
  const [sentCount, setSentCount] = useState(0); // the list follows a message you send
  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => unwrap(api.GET("/sessions/{session_id}", { params: { path: { session_id: sessionId } } })),
  });
  const agentId = session.data?.agent ?? null;
  const listedName = useAgentName(agentId);
  const label = agentName ?? listedName;
  const ownAgent = useIsOwnAgent(agentId);
  const busy = isBusy(state);
  const waiting = pendingApprovals(state);
  const ended = state.turn && !busy ? `${state.turn.runId}:${state.turn.status}` : null;
  useEffect(() => {
    if (ended) onTurnEnd?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per turn end
  }, [ended]);
  const views = turns(state);

  const send = async (text: string): Promise<boolean> => {
    setNotice(null);
    try {
      const accepted = await sendMessage(sessionId, text);
      dispatch({ kind: "sent", runId: accepted.run_id });
      setSentCount((n) => n + 1);
      return true;
    } catch (e) {
      setNotice(problemText(e));
      return false;
    }
  };

  const stop = async () => {
    try {
      await unwrap(api.POST("/sessions/{session_id}/cancel", { params: { path: { session_id: sessionId } } }));
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 409)) setNotice(problemText(e)); // 409: it just ended
    }
  };

  // A failed turn, tried again from its last saved step (phase H4). The turn is live
  // again BEFORE the request: its first stream events and tokens can arrive before the
  // 202, and a turn still marked failed would drop them. Refused: it's failed again.
  const retry = async (runId: string) => {
    setNotice(null);
    const before = state.turn;
    dispatch({ kind: "sent", runId });
    try {
      await unwrap(api.POST("/runs/{run_id}/redrive", { params: { path: { run_id: runId } } }));
    } catch (e) {
      dispatch({ kind: "turn", runId, status: "failed", reason: before?.runId === runId ? before.reason : null });
      setNotice(problemText(e));
    }
  };

  const decide = async (request: Interrupt, decision: "approve" | "reject", reason: string | null) => {
    // The approval's own id: you decide the call you were shown, even with several waiting.
    const body = { decision, reason, ...(request.approvalId ? { approval_id: request.approvalId } : {}) };
    try {
      await unwrap(api.POST("/sessions/{session_id}/approve", { params: { path: { session_id: sessionId } }, body }));
    } catch (e) {
      setNotice(problemText(e));
    }
  };

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <header className={`${compact ? "hidden" : "flex"} h-14 shrink-0 items-center gap-3 border-b border-stone-200/70 bg-stone-50/80 px-5 backdrop-blur dark:border-stone-800/70 dark:bg-stone-950/80`}>
        <h1 className="truncate text-[15px] font-medium">{session.data?.title ?? "New chat"}</h1>
        {agentId && (
          <span className="flex items-center gap-1.5 rounded-full bg-white py-0.5 pr-2.5 pl-0.5 text-xs text-stone-600 ring-1 ring-stone-200 dark:bg-stone-900 dark:text-stone-300 dark:ring-stone-800">
            <Avatar name={label} size="sm" brand={agentId === "chat"} />
            {label}
          </span>
        )}
        <a
          href={`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/export`}
          download
          className="ml-auto inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-stone-600 hover:bg-stone-100 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-100"
          data-testid="download-chat"
          title="Download this chat as Markdown: replies, reasoning, every tool call and its result"
        >
          <Download aria-hidden className="size-3.5" /> Download
        </a>
      </header>
      <ConnectionBanner state={connection} />
      <MessageList
        views={views}
        agent={label}
        brand={agentId === "chat"}
        waitingIds={new Set(waiting.map((m) => m.messageId))}
        onDecide={(request, decision, reason) => void decide(request, decision, reason)}
        onRetry={busy ? undefined : (runId) => void retry(runId)}
        canTest={ownAgent}
        status={state.turn?.status}
        sentCount={sentCount}
      />
      <div className="shrink-0 px-4 pb-4">
        <div className="mx-auto max-w-3xl">
          {notice && (
            <div role="alert" className="mb-2 rounded-xl bg-rose-50 px-4 py-2 text-sm text-rose-800 ring-1 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900">
              {notice}
            </div>
          )}
          <Composer
            busy={busy}
            waitingApproval={waiting.length > 0}
            onSend={send}
            onStop={stop}
            placeholder={`Message ${label}…`}
            leading={compact ? undefined : <span className="px-2 text-xs text-stone-500">Enter to send · Shift+Enter for a new line</span>}
          />
        </div>
      </div>
    </div>
  );
}

function MessageList({
  views,
  agent,
  brand,
  waitingIds,
  onDecide,
  onRetry,
  canTest,
  status,
  sentCount,
}: {
  views: TurnView[];
  agent: string;
  brand: boolean;
  waitingIds: ReadonlySet<string>;
  onDecide: Decide;
  /** Only the latest turn can be tried again, and only while nothing runs. */
  onRetry: ((runId: string) => void) | undefined;
  canTest: boolean;
  status: TurnStatus | undefined;
  sentCount: number;
}) {
  const end = useRef<HTMLDivElement>(null);
  // Follow new content while the reader is at the bottom; stop once they scroll up to
  // read. Measured on scroll, before new content changes the height.
  const pinned = useRef(true);
  const last = views.at(-1);
  const signature = `${String(views.length)}:${String(last?.items.length ?? 0)}:${String(last?.draft?.length ?? 0)}:${String(last?.active)}`;
  useEffect(() => {
    if (pinned.current) end.current?.scrollIntoView({ block: "end" });
  }, [signature]);
  useEffect(() => {
    if (sentCount === 0) return;
    pinned.current = true; // you just sent: show it, and what follows
    end.current?.scrollIntoView({ block: "end" });
  }, [sentCount]);
  return (
    <div
      className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 pt-8 pb-4"
      data-testid="messages"
      onScroll={(e) => {
        const el = e.currentTarget;
        pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      }}
    >
      <div className="mx-auto max-w-3xl space-y-10">
        {views.length === 0 && (
          <div className="py-24 text-center">
            <div className="font-display text-2xl">Start the conversation</div>
            <div className="mt-2 text-sm text-stone-500">Ask a question, or say hello to see what {agent} can do.</div>
          </div>
        )}
        {views.map((v) => (
          <TurnBlock
            key={v.runId}
            view={v}
            agent={agent}
            brand={brand}
            waitingIds={waitingIds}
            onDecide={onDecide}
            onRetry={v === last && onRetry ? () => { onRetry(v.runId); } : undefined}
            canTest={canTest}
            status={v.active ? status : undefined}
          />
        ))}
        <div ref={end} />
      </div>
      <div aria-live="polite" className="sr-only">
        {last && !last.active && last.items.some((i) => i.kind === "text") ? "Reply finished" : ""}
      </div>
    </div>
  );
}

function TurnBlock({
  view,
  agent,
  brand,
  waitingIds,
  onDecide,
  onRetry,
  canTest,
  status,
}: {
  view: TurnView;
  agent: string;
  brand: boolean;
  waitingIds: ReadonlySet<string>;
  onDecide: Decide;
  onRetry: (() => void) | undefined;
  canTest: boolean;
  status: TurnStatus | undefined;
}) {
  const [details, setDetails] = useState(false);
  const hasReply = view.items.length > 0 || view.draft !== null || view.active;
  return (
    <section className="space-y-5" aria-label="Message and reply" data-testid="turn">
      {view.user && (
        <div className="flex justify-end">
          <div
            className="max-w-[80%] rounded-2xl rounded-br-md bg-stone-200/70 px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-stone-900 dark:bg-stone-800 dark:text-stone-100"
            data-testid="user-message"
          >
            {view.user.text}
          </div>
        </div>
      )}
      {hasReply && (
        <div className="flex gap-3.5">
          <Avatar name={agent} brand={brand} />
          <div className="min-w-0 flex-1 space-y-3.5 pt-1">
            <div className="text-sm font-semibold">
              {agent}
              {answeredBy(view) && <span className="ml-1.5 text-xs font-normal text-stone-500" data-testid="answered-by">· {answeredBy(view)}</span>}
            </div>
            {renderItems(view.items, agent, waitingIds, onDecide, view.active ? undefined : onRetry)}
            {view.draft && (
              <div data-testid="draft">
                <Markdown text={view.draft} />
              </div>
            )}
            {view.active && status !== "waiting_approval" && !view.draft && <Typing label={turnLabel(status)} />}
            {!view.runId.startsWith("none") && !view.active && (
              <div>
                <div className="flex flex-wrap items-center gap-1">
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 rounded-lg px-1.5 py-1 text-xs text-stone-500 transition hover:bg-stone-100 hover:text-stone-700 focus-visible:outline-2 focus-visible:outline-sun-500 dark:hover:bg-stone-800 dark:hover:text-stone-200"
                  aria-expanded={details}
                  onClick={() => {
                    setDetails(!details);
                  }}
                >
                  <Info aria-hidden className="size-3.5" />
                  {details ? "Hide details" : "What happened?"}
                </button>
                <ReplyRating runId={view.runId} canTest={canTest} />
                </div>
                {details && (
                  <div className="mt-2">
                    <WhatHappened runId={view.runId} active={view.active} />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

/** Which model wrote the turn's reply (not shown for the offline demo model). */
function answeredBy(view: TurnView): string | null {
  for (const item of view.items) {
    if (item.kind === "text" && item.message.model && item.message.model !== "scripted") return item.message.model;
  }
  return null;
}

/** Items in order; consecutive tool steps share one frame. */
function renderItems(
  items: Item[],
  agent: string,
  waitingIds: ReadonlySet<string>,
  onDecide: Decide,
  onRetry: (() => void) | undefined,
): ReactNode[] {
  const out: ReactNode[] = [];
  const lastError = items.findLast((i) => i.kind === "error");
  // Try again: on the turn's last error, if nothing came after it (not tried already).
  const retryable = lastError?.kind === "error" && lastError.message.canRetry && items.at(-1) === lastError;
  let steps: Extract<Item, { kind: "tool" }>[] = [];
  const flush = () => {
    if (steps.length === 0) return;
    const group = steps;
    out.push(
      <StepList key={`steps:${group[0]?.key ?? ""}`}>
        {group.map((s) => (
          <ToolCard key={s.key} call={s.call} result={s.result} awaitingApproval={s.awaitingApproval} ended={s.ended} />
        ))}
      </StepList>,
    );
    steps = [];
  };
  for (const item of items) {
    if (item.kind === "tool") {
      steps.push(item);
      continue;
    }
    flush();
    switch (item.kind) {
      case "text":
        out.push(
          <div key={item.key} data-testid="assistant-message">
            <Markdown text={item.message.text} />
            {item.message.interrupted && <div className="mt-1 text-xs text-stone-500">(stopped before the end)</div>}
          </div>,
        );
        break;
      case "helpers":
        out.push(<HelperCards key={item.key} helpers={item.helpers} />);
        break;
      case "approval-request":
        out.push(
          <ApprovalCard
            key={item.key}
            message={item.message}
            decided={item.decided}
            pending={waitingIds.has(item.message.messageId)}
            agent={agent}
            onDecide={(decision, reason) => {
              onDecide(item.message, decision, reason);
            }}
          />,
        );
        break;
      case "error":
        out.push(<ErrorNote key={item.key} message={item.message} onRetry={retryable && item === lastError ? onRetry : undefined} />);
        break;
      case "retried":
        out.push(<RetriedNote key={item.key} />);
        break;
    }
  }
  flush();
  return out;
}

function ConnectionBanner({ state }: { state: ConnectionState }) {
  if (state.status === "open" || state.status === "idle") return null;
  const offline = state.status === "offline";
  const text = offline
    ? "Can't reach Nuria. Retrying… (is it running? ./setup.sh)"
    : state.status === "connecting"
      ? "Connecting…"
      : "Connection lost. Reconnecting…";
  return (
    <div className="pointer-events-none absolute inset-x-0 top-16 z-10 flex justify-center px-4">
      <div
        role="status"
        className={`flex items-center gap-2 rounded-full px-4 py-1.5 text-sm shadow-lift ring-1 ${offline ? "bg-rose-50 text-rose-800 ring-rose-200 dark:bg-rose-950 dark:text-rose-200 dark:ring-rose-900" : "bg-white text-stone-700 ring-stone-200 dark:bg-stone-900 dark:text-stone-200 dark:ring-stone-700"}`}
        data-testid="connection-banner"
      >
        {offline ? <WifiOff aria-hidden className="size-4" /> : <Loader2 aria-hidden className="size-4 animate-spin motion-reduce:animate-none" />}
        {text}
      </div>
    </div>
  );
}
