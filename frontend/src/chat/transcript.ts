/**
 * The live chat state as a pure reducer (Patterns: Reducer / event sourcing,
 * functional core). Every input (a replayed message, a live one, a token, a turn's
 * status, a helper's progress, a refetched session) is an action; the state is a
 * fold over them.
 *
 * Invariants (the client half of "exactly-once display", AC20):
 * - each message appears once, in seq order, whatever the delivery order or how
 *   often it is delivered (replays after reconnects, the server's back-fill);
 * - `lastSeq` is the highest seq with no hole below it: a reconnect resumes there,
 *   so a missing message is always asked for again;
 * - the streamed draft of a reply is replaced by the persisted reply, never shown
 *   twice; a stopped reply is kept (the server persists it as `interrupted`).
 */
import type { Message } from "../api/messages";
import { type HelperStatus, type StreamAction, TERMINAL, type TurnStatus } from "../stream/events";

export interface Turn {
  runId: string;
  status: TurnStatus;
  reason: string | null;
}

export interface Helper {
  handle: string;
  runId: string;
  agent: string;
  task: string;
  status: HelperStatus;
  progress: string | null;
  percent: number | null;
  summary: string | null;
}

export interface ChatState {
  messages: readonly Message[]; // ordered by seq, unique
  lastSeq: number;
  draft: { runId: string; text: string } | null;
  turn: Turn | null;
  helpers: Readonly<Record<string, Helper>>;
}

export type ChatAction =
  | StreamAction
  /** The composer's message was accepted: this run is the new turn. */
  | { kind: "sent"; runId: string }
  /** GET /sessions/{id}: the server's view of the active turn (the safety net). */
  | { kind: "session"; activeRunId: string | null; activeRunStatus: string | null }
  /** GET /runs/{id}: the helpers the run has, with their results (after a reload). */
  | { kind: "helpers"; runId: string; helpers: readonly Omit<Helper, "runId">[] };

export const initialChat: ChatState = { messages: [], lastSeq: 0, draft: null, turn: null, helpers: {} };

export function isBusy(state: ChatState): boolean {
  return state.turn !== null && !TERMINAL.has(state.turn.status);
}

export function chat(state: ChatState, action: ChatAction): ChatState {
  switch (action.kind) {
    case "message":
      return addMessage(state, action.message);
    case "token":
      return addToken(state, action.runId, action.text);
    case "turn": {
      const current = state.turn;
      if (current && current.runId !== action.runId && TERMINAL.has(action.status)) {
        return state; // late news of an earlier turn
      }
      if (current?.runId === action.runId && TERMINAL.has(current.status) && !TERMINAL.has(action.status)) {
        return state; // out of order: this turn has already ended
      }
      return { ...state, turn: { runId: action.runId, status: action.status, reason: action.reason } };
    }
    case "sent":
      return {
        ...state,
        turn: { runId: action.runId, status: "queued", reason: null },
        draft: null,
      };
    case "session":
      return reconcile(state, action.activeRunId, action.activeRunStatus);
    case "helper":
      return updateHelper(state, action);
    case "helpers": {
      const helpers = { ...state.helpers };
      for (const h of action.helpers) {
        // The run view is the source of truth for results; live progress may be newer.
        const live = helpers[h.handle];
        helpers[h.handle] = {
          ...h,
          runId: action.runId,
          progress: live?.status === "running" && h.status === "running" ? live.progress : h.progress,
        };
      }
      return { ...state, helpers };
    }
  }
}

function addMessage(state: ChatState, message: Message): ChatState {
  const { messages } = state;
  if (message.seq <= state.lastSeq) return state; // held already: no hole below lastSeq
  // Insert in seq order (almost always at the end); drop a duplicate.
  let i = messages.length;
  while (i > 0 && (messages[i - 1]?.seq ?? 0) > message.seq) i--;
  if (messages[i - 1]?.seq === message.seq) return state;
  const next = [...messages.slice(0, i), message, ...messages.slice(i)];
  let lastSeq = state.lastSeq;
  for (let j = i; j < next.length && next[j]?.seq === lastSeq + 1; j++) lastSeq += 1;
  const replacesDraft = message.type === "assistant" && state.draft?.runId === message.runId;
  return { ...state, messages: next, lastSeq, draft: replacesDraft ? null : state.draft };
}

function addToken(state: ChatState, runId: string, text: string): ChatState {
  const { turn, draft } = state;
  if (turn?.runId === runId && TERMINAL.has(turn.status)) return state; // a late token
  if (draft?.runId === runId) return { ...state, draft: { runId, text: draft.text + text } };
  return { ...state, draft: { runId, text } };
}

function reconcile(state: ChatState, activeRunId: string | null, activeRunStatus: string | null): ChatState {
  if (activeRunId === null) {
    // No active turn on the server: whatever we thought was running is over.
    if (state.turn && !TERMINAL.has(state.turn.status)) {
      return { ...state, turn: { ...state.turn, status: "ended" } };
    }
    return state;
  }
  const status = toTurnStatus(activeRunStatus);
  if (state.turn?.runId === activeRunId && state.turn.status === status) return state;
  return { ...state, turn: { runId: activeRunId, status, reason: null } };
}

function toTurnStatus(runStatus: string | null): TurnStatus {
  switch (runStatus) {
    case "running":
    case "waiting_approval":
    case "queued":
      return runStatus;
    case "waiting_children":
      return "running";
    default:
      return "queued";
  }
}

function updateHelper(state: ChatState, a: Extract<StreamAction, { kind: "helper" }>): ChatState {
  const prev = state.helpers[a.handle];
  const helper: Helper = {
    handle: a.handle,
    runId: a.runId,
    agent: a.agent ?? prev?.agent ?? "helper",
    task: a.task ?? prev?.task ?? "",
    status: a.status ?? prev?.status ?? "running",
    progress: a.progress ?? prev?.progress ?? null,
    percent: a.percent ?? prev?.percent ?? null,
    summary: prev?.summary ?? null,
  };
  return { ...state, helpers: { ...state.helpers, [a.handle]: helper } };
}
