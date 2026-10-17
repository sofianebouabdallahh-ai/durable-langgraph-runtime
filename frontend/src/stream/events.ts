/**
 * The session stream's wire format (GET /sessions/{id}/stream, SSE), decoded into
 * actions for the transcript reducer. One SSE event's data is
 * `{run_id, seq, after_seq, ts, epoch, type, payload}`; `seq` is null for transient
 * events (tokens, turn status, helpers' progress), which are never replayed.
 */
import type { Schemas } from "../api/client";
import { type Message, parseMessage } from "../api/messages";

export type TurnStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "completed"
  | "failed"
  | "cancelled"
  | "ended"; // over, outcome unknown (learned from the session, not the stream)

export const TERMINAL: ReadonlySet<TurnStatus> = new Set(["completed", "failed", "cancelled", "ended"]);

export type HelperStatus = "running" | "completed" | "failed" | "cancelled" | "timed_out";

export type StreamAction =
  | { kind: "message"; message: Message }
  | { kind: "token"; runId: string; text: string }
  | { kind: "turn"; runId: string; status: TurnStatus; reason: string | null }
  | {
      kind: "helper";
      runId: string;
      handle: string;
      agent?: string;
      task?: string;
      progress?: string;
      percent?: number;
      status?: HelperStatus;
    };

/** The SSE event names the session stream sends (EventSource needs each by name). */
export const EVENT_NAMES = [
  "message.created",
  "token",
  "turn.status",
  "subagent.spawned",
  "subagent.progress",
  "subagent.completed",
] as const;

interface Wire {
  run_id: string;
  seq: number | null;
  type: string;
  payload: Record<string, unknown>;
}

const TURN_STATUSES = new Set<string>(["queued", "running", "waiting_approval", "completed", "failed", "cancelled"]);
const HELPER_END = new Set<string>(["completed", "failed", "cancelled", "timed_out"]);

function isWire(v: unknown): v is Wire {
  if (typeof v !== "object" || v === null) return false;
  const w = v as Record<string, unknown>;
  return typeof w.run_id === "string" && typeof w.payload === "object" && w.payload !== null;
}

/** One SSE event → an action, or null (malformed, or a type this UI doesn't know). */
export function decode(name: string, data: string): StreamAction | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (!isWire(parsed)) return null;
  const wire = parsed;
  const p = wire.payload;
  switch (name) {
    case "message.created": {
      const message = parseMessage(p as unknown as Schemas["MessageView"]);
      return message ? { kind: "message", message } : null;
    }
    case "token":
      return typeof p.text === "string" ? { kind: "token", runId: wire.run_id, text: p.text } : null;
    case "turn.status": {
      const status = typeof p.status === "string" && TURN_STATUSES.has(p.status) ? (p.status as TurnStatus) : null;
      if (!status) return null;
      return { kind: "turn", runId: typeof p.run_id === "string" ? p.run_id : wire.run_id, status, reason: typeof p.reason === "string" ? p.reason : null };
    }
    case "subagent.spawned":
    case "subagent.progress":
    case "subagent.completed": {
      if (typeof p.handle !== "string") return null;
      const action: StreamAction = { kind: "helper", runId: wire.run_id, handle: p.handle };
      if (typeof p.agent === "string") action.agent = p.agent;
      if (typeof p.task === "string") action.task = p.task;
      if (typeof p.message === "string") action.progress = p.message;
      if (typeof p.percent === "number") action.percent = p.percent;
      if (name === "subagent.spawned") action.status = "running";
      if (name === "subagent.completed" && typeof p.status === "string" && HELPER_END.has(p.status)) {
        action.status = p.status as HelperStatus;
      }
      return action;
    }
    default:
      return null;
  }
}
