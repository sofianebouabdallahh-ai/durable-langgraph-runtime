/** The chat for one session (R12.11): the container that wires data to the cards. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, ApiError, unwrap } from "../api/client";
import type { ConnectionState } from "../stream/connection";
import type { TurnStatus } from "../stream/events";
import { Button, Spinner } from "../ui/primitives";
import { turnLabel } from "../ui/words";
import { Markdown } from "../ui/Markdown";
import { ApprovalCard, ErrorNote, HelperCards, ToolCard } from "./cards";
import { pendingApproval, type TurnView, turns } from "./selectors";
import { isBusy } from "./transcript";
import { useChat } from "./useChat";
import { WhatHappened } from "./WhatHappened";

export function ChatView({ sessionId }: { sessionId: string }) {
  const { state, dispatch, connection } = useChat(sessionId);
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => unwrap(api.GET("/sessions/{session_id}", { params: { path: { session_id: sessionId } } })),
  });
  const busy = isBusy(state);
  const waiting = pendingApproval(state);
  const views = turns(state);

  const send = async (text: string): Promise<boolean> => {
    setNotice(null);
    try {
      const accepted = await unwrap(
        api.POST("/sessions/{session_id}/messages", { params: { path: { session_id: sessionId } }, body: { content: text } }),
      );
      dispatch({ kind: "sent", runId: accepted.run_id });
      if (!session.data?.title) {
        // Name a new chat after its first message, as people expect.
        void api
          .PATCH("/sessions/{session_id}", { params: { path: { session_id: sessionId } }, body: { title: titleFrom(text) } })
          .then(() => queryClient.invalidateQueries({ queryKey: ["sessions"] }));
      }
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

  const decide = async (decision: "approve" | "reject", reason: string | null) => {
    try {
      await unwrap(
        api.POST("/sessions/{session_id}/approve", { params: { path: { session_id: sessionId } }, body: { decision, reason } }),
      );
    } catch (e) {
      setNotice(problemText(e));
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ConnectionBanner state={connection} />
      <MessageList
        views={views}
        waitingId={waiting?.messageId ?? null}
        onDecide={(decision, reason) => void decide(decision, reason)}
        status={state.turn?.status}
      />
      <div className="border-t border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-950">
        {notice && (
          <div role="alert" className="mb-2 text-sm text-rose-700 dark:text-rose-400">
            {notice}
          </div>
        )}
        <Composer busy={busy} onSend={send} onStop={stop} waitingApproval={waiting !== null} />
      </div>
    </div>
  );
}

function MessageList({
  views,
  waitingId,
  onDecide,
  status,
}: {
  views: TurnView[];
  waitingId: string | null;
  onDecide: (decision: "approve" | "reject", reason: string | null) => void;
  status: TurnStatus | undefined;
}) {
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const last = views.at(-1);
  const signature = `${String(views.length)}:${String(last?.items.length ?? 0)}:${String(last?.draft?.length ?? 0)}`;
  useEffect(() => {
    const el = box.current;
    // Follow new content only if the reader is already at the bottom.
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 160) end.current?.scrollIntoView({ block: "end" });
  }, [signature]);
  return (
    <div ref={box} className="min-h-0 flex-1 overflow-y-auto px-4 py-6" data-testid="messages">
      <div className="mx-auto max-w-3xl space-y-8">
        {views.length === 0 && (
          <div className="py-16 text-center text-slate-500">
            <div className="text-lg font-medium text-slate-700 dark:text-slate-200">Start the conversation</div>
            <div className="mt-1 text-sm">Ask a question, or say hello to see what this assistant can do.</div>
          </div>
        )}
        {views.map((v) => (
          <TurnBlock key={v.runId} view={v} waitingId={waitingId} onDecide={onDecide} status={v.active ? status : undefined} />
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
  waitingId,
  onDecide,
  status,
}: {
  view: TurnView;
  waitingId: string | null;
  onDecide: (decision: "approve" | "reject", reason: string | null) => void;
  status: TurnStatus | undefined;
}) {
  const [details, setDetails] = useState(false);
  return (
    <section className="space-y-3" aria-label="Message and reply" data-testid="turn">
      {view.user && (
        <div className="flex justify-end">
          <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2 whitespace-pre-wrap text-white" data-testid="user-message">
            {view.user.text}
          </div>
        </div>
      )}
      <div className="space-y-3">
        {view.items.map((item) => {
          switch (item.kind) {
            case "text":
              return (
                <div key={item.key} data-testid="assistant-message" className="text-slate-800 dark:text-slate-100">
                  <Markdown text={item.message.text} />
                  {item.message.interrupted && <div className="mt-1 text-xs text-slate-500">(stopped before the end)</div>}
                </div>
              );
            case "tool":
              return <ToolCard key={item.key} call={item.call} result={item.result} />;
            case "helpers":
              return <HelperCards key={item.key} helpers={item.helpers} />;
            case "approval-request":
              return (
                <ApprovalCard
                  key={item.key}
                  message={item.message}
                  decided={item.decided}
                  pending={item.message.messageId === waitingId}
                  onDecide={onDecide}
                />
              );
            case "error":
              return <ErrorNote key={item.key} message={item.message} />;
          }
        })}
        {view.draft && (
          <div data-testid="draft" className="text-slate-800 dark:text-slate-100">
            <Markdown text={view.draft} />
          </div>
        )}
        {view.active && status !== "waiting_approval" && <Spinner label={turnLabel(status)} />}
      </div>
      {!view.runId.startsWith("none") && (
        <div>
          <button
            type="button"
            className="text-xs text-slate-500 underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-indigo-500"
            aria-expanded={details}
            onClick={() => {
              setDetails(!details);
            }}
          >
            {details ? "Hide details" : "What happened?"}
          </button>
          {details && (
            <div className="mt-2">
              <WhatHappened runId={view.runId} active={view.active} />
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export function Composer({
  busy,
  waitingApproval,
  onSend,
  onStop,
}: {
  busy: boolean;
  waitingApproval: boolean;
  onSend: (text: string) => Promise<boolean>;
  onStop: () => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const submit = async () => {
    const value = text.trim();
    if (!value || busy || sending) return;
    setSending(true);
    if (await onSend(value)) setText("");
    setSending(false);
  };
  return (
    <form
      className="mx-auto flex max-w-3xl items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label className="flex-1">
        <span className="sr-only">Message</span>
        <textarea
          value={text}
          onChange={(e) => {
            setText(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={Math.min(6, Math.max(1, text.split("\n").length))}
          maxLength={32000}
          placeholder={waitingApproval ? "Approve or reject above to continue…" : "Message the assistant (Enter to send, Shift+Enter for a new line)"}
          className="w-full resize-none rounded-xl border border-slate-300 bg-white px-3 py-2 focus:border-indigo-500 focus:outline-none dark:border-slate-600 dark:bg-slate-900"
        />
      </label>
      {busy ? (
        <Button variant="secondary" onClick={() => void onStop()} aria-label="Stop the reply">
          ■ Stop
        </Button>
      ) : (
        <Button variant="primary" type="submit" disabled={!text.trim() || sending}>
          Send
        </Button>
      )}
    </form>
  );
}

function ConnectionBanner({ state }: { state: ConnectionState }) {
  if (state.status === "open" || state.status === "idle") return null;
  const text =
    state.status === "offline"
      ? "Can't reach the server. Retrying… (is the stack running? ./setup.sh)"
      : state.status === "connecting"
        ? "Connecting…"
        : "Connection lost. Reconnecting…";
  return (
    <div role="status" className={`px-4 py-1.5 text-center text-sm ${state.status === "offline" ? "bg-rose-100 text-rose-900 dark:bg-rose-950 dark:text-rose-200" : "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"}`} data-testid="connection-banner">
      {text}
    </div>
  );
}

function titleFrom(text: string): string {
  const line = text.split("\n")[0]?.trim() ?? "";
  return line.length > 60 ? `${line.slice(0, 57)}…` : line || "New chat";
}

function problemText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.is("turn-active")) return "The assistant is still answering. Wait, or stop it first.";
    if (e.status === 429) return "Too many messages at once. Wait a moment and try again.";
    if (e.is("session-archived")) return "This chat is archived. Start a new one.";
    return e.message;
  }
  return "Couldn't reach the server. Check that the stack is running.";
}
