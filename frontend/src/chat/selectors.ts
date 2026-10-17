/**
 * Pure views of the chat state for the components: the transcript grouped into
 * turns, a tool call paired with its result, the approval a turn waits on.
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
  | { kind: "tool"; key: string; call: Of<"tool_call">; result: Of<"tool_result"> | null; awaitingApproval: boolean }
  | { kind: "helpers"; key: string; helpers: Helper[] }
  | { kind: "approval-request"; key: string; message: Of<"interrupt">; decided: Of<"approval"> | null }
  | { kind: "error"; key: string; message: Of<"error"> };

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
      items: items(messages, Object.values(state.helpers).filter((h) => h.runId === runId)),
      draft: state.draft?.runId === runId ? state.draft.text : null,
      active: runId === activeRun,
    };
  });
}

function items(messages: Message[], helpers: Helper[]): Item[] {
  const results = new Map<string, Of<"tool_result">>();
  const decisions: Of<"approval">[] = [];
  for (const m of messages) {
    if (m.type === "tool_result") results.set(m.toolCallId, m);
    if (m.type === "approval") decisions.push(m);
  }
  // A call held for a person's decision: its approval request has no decision yet.
  const held = new Set<string>();
  for (const m of messages) {
    if (m.type === "interrupt" && m.tool && !decisions.some((d) => d.seq > m.seq)) held.add(m.tool);
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
          out.push({ kind: "tool", key: m.messageId, call: m, result, awaitingApproval: result === null && held.has(m.tool) });
        }
        break;
      case "interrupt": {
        // Approvals are decided in order: the first decision after this request is its own.
        const decided = decisions.find((d) => d.seq > m.seq) ?? null;
        out.push({ kind: "approval-request", key: m.messageId, message: m, decided });
        break;
      }
      case "error":
        out.push({ kind: "error", key: m.messageId, message: m });
        break;
      default:
        break; // user (shown as the turn's header), tool_result (paired), approval (paired), system (hidden)
    }
  }
  if (!helpersShown && helpers.length > 0) {
    out.push({ kind: "helpers", key: `helpers:${helpers[0]?.handle ?? ""}`, helpers });
  }
  return out;
}

/** The approval the active turn waits on, if any. */
export function pendingApproval(state: ChatState): Of<"interrupt"> | null {
  if (state.turn?.status !== "waiting_approval") return null;
  const runId = state.turn.runId;
  let pending: Of<"interrupt"> | null = null;
  for (const m of state.messages) {
    if (m.runId !== runId) continue;
    if (m.type === "interrupt") pending = m;
    if (m.type === "approval") pending = null;
  }
  return pending;
}
