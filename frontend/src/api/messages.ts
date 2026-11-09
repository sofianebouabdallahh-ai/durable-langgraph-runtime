/**
 * Transcript messages with typed content. The OpenAPI spec types `content` as an
 * open object (it depends on the message type), so this module narrows it once, at
 * the edge, and every component works with exact types. Unknown message types are
 * dropped rather than crashing the view (forward compatible).
 */
import type { Schemas } from "./client";

type Json = Record<string, unknown>;

interface Base {
  seq: number;
  messageId: string;
  runId: string | null;
  createdAt: string;
}

export type Message =
  | (Base & { type: "user"; text: string })
  | (Base & {
      type: "assistant";
      text: string;
      model: string | null;
      interrupted: boolean;
      budgetLimited: boolean;
    })
  | (Base & { type: "tool_call"; toolCallId: string; tool: string; args: Json })
  | (Base & {
      type: "tool_result";
      toolCallId: string;
      tool: string;
      result: unknown;
      error: string | null;
      cached: boolean;
      durationMs: number | null;
    })
  | (Base & {
      type: "interrupt";
      kind: string | null;
      /** Which approval this asks (null on messages written before phase H1). */
      approvalId: string | null;
      callId: string | null;
      tool: string | null;
      args: Json;
      reason: string | null;
    })
  | (Base & { type: "approval"; approvalId: string | null; decision: "approve" | "reject"; reason: string | null })
  | (Base & { type: "error"; reason: string; budgetLimited: boolean })
  | (Base & { type: "system"; text: string });

export type MessageType = Message["type"];

const str = (v: unknown): string => (typeof v === "string" ? v : "");
const strOrNull = (v: unknown): string | null => (typeof v === "string" ? v : null);
const obj = (v: unknown): Json =>
  typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Json) : {};

/** A message from the API or the stream, or null if its type is unknown. */
export function parseMessage(view: Schemas["MessageView"]): Message | null {
  const base: Base = {
    seq: view.seq,
    messageId: view.message_id,
    runId: view.run_id ?? null,
    createdAt: view.created_at,
  };
  const c = view.content;
  switch (view.type) {
    case "user":
      return { ...base, type: "user", text: str(c.text) };
    case "assistant":
      return {
        ...base,
        type: "assistant",
        text: str(c.text),
        model: strOrNull(c.model),
        interrupted: c.interrupted === true,
        budgetLimited: c.budget_limited === true,
      };
    case "tool_call":
      return { ...base, type: "tool_call", toolCallId: str(c.tool_call_id), tool: str(c.tool), args: obj(c.args) };
    case "tool_result":
      return {
        ...base,
        type: "tool_result",
        toolCallId: str(c.tool_call_id),
        tool: str(c.tool),
        result: c.result,
        error: strOrNull(c.error),
        cached: c.cached === true,
        durationMs: typeof c.duration_ms === "number" ? c.duration_ms : null,
      };
    case "interrupt": {
      const payload = obj(c.payload);
      return {
        ...base,
        type: "interrupt",
        kind: strOrNull(c.interrupt_type),
        approvalId: strOrNull(payload.approval_id),
        callId: strOrNull(payload.call_id),
        tool: strOrNull(payload.tool),
        args: obj(payload.args),
        reason: strOrNull(payload.reason),
      };
    }
    case "approval":
      return {
        ...base,
        type: "approval",
        approvalId: strOrNull(c.approval_id),
        decision: c.decision === "approve" ? "approve" : "reject",
        reason: strOrNull(c.reason),
      };
    case "error":
      return { ...base, type: "error", reason: str(c.reason), budgetLimited: c.budget_limited === true };
    case "system":
      return { ...base, type: "system", text: str(c.text) };
    default:
      return null;
  }
}
