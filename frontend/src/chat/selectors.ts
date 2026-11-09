/**
 * Pure views of the chat state for the components: the transcript grouped into
 * turns, a tool call paired with its result, the approvals a turn waits on.
 */
import type { Message } from "../api/messages";
import { TERMINAL } from "../stream/events";
import type { ChatState, Helper } from "./transcript";

type Of<T extends Message["type"]> = Extract<Message, { type: T }>;

/** Tools the orchestrator gives a main agent: shown as helper cards, not tool cards. */
export const HELPER_TOOLS: ReadonlySet<string> = new Set([
  "spawn_subagent",
  "wait_subagents",
  "subagent_status",
  "cancel_subagent",
]);

export type Item =
  | { kind: "text"; key: string; message: Of<"assistant"> }
  | { kind: "tool"; key: string; call: Of<"tool_call">; result: Of<"tool_result"> | null; awaitingApproval: boolean; ended: boolean }
  | { kind: "helpers"; key: string; helpers: Helper[] }
  | { kind: "approval-request"; key: string; message: Of<"interrupt">; decided: Of<"approval"> | null }
  | { kind: "error"; key: string; message: Of<"error"> }
  | { kind: "retried"; key: string; message: Of<"system"> };

export interface TurnView {
  runId: string;
  user: Of<"user"> | null;
  items: Item[];
  /** The live, not yet persisted reply of this turn. */
  draft: string | null;
  active: boolean;
}

export function turns(state: ChatState): TurnView[] {
  const byRun = new Map<string, Message[]>();
  const order: string[] = [];
  for (const m of state.messages) {
    const runId = m.runId ?? "none";
    let list = byRun.get(runId);
    if (!list) {
      list = [];
      byRun.set(runId, list);
      order.push(runId);
    }
    list.push(m);
  }
  const activeRun = state.turn && !TERMINAL.has(state.turn.status) ? state.turn.runId : null;
  if (activeRun && !byRun.has(activeRun)) {
    byRun.set(activeRun, []); // sent; its user message hasn't arrived yet
    order.push(activeRun);
  }
  if (state.draft && !byRun.has(state.draft.runId)) {
    byRun.set(state.draft.runId, []);
    order.push(state.draft.runId);
  }
  return order.map((runId) => {
    const messages = byRun.get(runId) ?? [];
    return {
      runId,
      user: messages.find((m): m is Of<"user"> => m.type === "user") ?? null,
      items: items(messages, Object.values(state.helpers).filter((h) => h.runId === runId), runId === activeRun),
      draft: state.draft?.runId === runId ? state.draft.text : null,
      active: runId === activeRun,
    };
  });
}

/**
 * The decision of each approval request, by the request's message id. Requests carry
 * their `approvalId` (phase H1): a decision pairs with the request it names. Older
 * requests have none: the first unclaimed decision after one is its own.
 */
function decisionsOf(messages: Message[]): Map<string, Of<"approval">> {
  const asks = messages.filter((m): m is Of<"interrupt"> => m.type === "interrupt");
  const decisions = messages.filter((m): m is Of<"approval"> => m.type === "approval");
  const named = new Set(asks.map((a) => a.approvalId).filter((id): id is string => id !== null));
  const out = new Map<string, Of<"approval">>();
  const claimed = new Set<string>();
  for (const ask of asks) {
    const own =
      ask.approvalId !== null
        ? decisions.find((d) => d.approvalId === ask.approvalId)
        : decisions.find((d) => d.seq > ask.seq && !claimed.has(d.messageId) && !(d.approvalId !== null && named.has(d.approvalId)));
    if (own) {
      out.set(ask.messageId, own);
      claimed.add(own.messageId);
    }
  }
  return out;
}

/** `active`: the turn is still going; in an ended one, a call without a result never finished. */
function items(messages: Message[], helpers: Helper[], active: boolean): Item[] {
  const results = new Map<string, Of<"tool_result">>();
  for (const m of messages) {
    if (m.type === "tool_result") results.set(m.toolCallId, m);
  }
  const decided = decisionsOf(messages);
  // A call held for a person's decision: its approval request has no decision yet. Matched
  // by the call's id; older requests didn't carry it, so by the tool's name.
  const heldCalls = new Set<string>();
  const heldTools = new Set<string>();
  for (const m of messages) {
    if (m.type !== "interrupt" || decided.has(m.messageId)) continue;
    if (m.callId) heldCalls.add(m.callId);
    else if (m.tool) heldTools.add(m.tool);
  }
  const out: Item[] = [];
  let helpersShown = false;
  for (const m of messages) {
    switch (m.type) {
      case "assistant":
        if (m.text.trim()) out.push({ kind: "text", key: m.messageId, message: m });
        break;
      case "tool_call":
        if (HELPER_TOOLS.has(m.tool)) {
          if (!helpersShown && helpers.length > 0) {
            out.push({ kind: "helpers", key: `helpers:${m.messageId}`, helpers });
            helpersShown = true;
          }
        } else {
          const result = results.get(m.toolCallId) ?? null;
          const awaitingApproval = result === null && (heldCalls.has(m.toolCallId) || heldTools.has(m.tool));
          out.push({ kind: "tool", key: m.messageId, call: m, result, awaitingApproval, ended: result === null && !awaitingApproval && !active });
        }
        break;
      case "interrupt":
        out.push({ kind: "approval-request", key: m.messageId, message: m, decided: decided.get(m.messageId) ?? null });
        break;
      case "error":
        out.push({ kind: "error", key: m.messageId, message: m });
        break;
      case "system":
        if (typeof m.retry === "number") out.push({ kind: "retried", key: m.messageId, message: m });
        break; // other system rows are the agent's context (hidden)
      default:
        break; // user (shown as the turn's header), tool_result (paired), approval (paired)
    }
  }
  if (!helpersShown && helpers.length > 0) {
    out.push({ kind: "helpers", key: `helpers:${helpers[0]?.handle ?? ""}`, helpers });
  }
  return out;
}

/** The approvals the active turn waits on: each still needs its own decision. */
export function pendingApprovals(state: ChatState): Of<"interrupt">[] {
  if (state.turn?.status !== "waiting_approval") return [];
  const runId = state.turn.runId;
  const own = state.messages.filter((m) => m.runId === runId);
  const decided = decisionsOf(own);
  return own.filter((m): m is Of<"interrupt"> => m.type === "interrupt" && !decided.has(m.messageId));
}
