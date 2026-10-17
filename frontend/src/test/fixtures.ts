import type { Message } from "../api/messages";

let next = 0;
export const RUN = "11111111-1111-1111-1111-111111111111";
export const RUN2 = "22222222-2222-2222-2222-222222222222";

type Body<T extends Message["type"]> = Omit<Extract<Message, { type: T }>, "seq" | "messageId" | "runId" | "createdAt" | "type">;

export function msg<T extends Message["type"]>(seq: number, type: T, body: Body<T>, runId: string = RUN): Message {
  next += 1;
  return { seq, messageId: `m${String(seq)}-${type}`, runId, createdAt: `2026-10-17T12:00:${String(next % 60).padStart(2, "0")}Z`, type, ...body } as unknown as Message;
}

export const user = (seq: number, text: string, runId = RUN) => msg(seq, "user", { text }, runId);
export const reply = (seq: number, text: string, runId = RUN, extra: Partial<Body<"assistant">> = {}) =>
  msg(seq, "assistant", { text, model: "scripted", interrupted: false, budgetLimited: false, ...extra }, runId);
export const call = (seq: number, tool: string, id: string, args: Record<string, unknown> = {}, runId = RUN) =>
  msg(seq, "tool_call", { toolCallId: id, tool, args }, runId);
export const result = (seq: number, tool: string, id: string, value: unknown, runId = RUN) =>
  msg(seq, "tool_result", { toolCallId: id, tool, result: value, error: null, cached: false, durationMs: 12 }, runId);
