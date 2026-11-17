/**
 * The session stream's wire format (GET /sessions/{id}/stream, SSE), decoded into
 * actions for the transcript reducer. The events' types are the spec's own
 * (`SessionStreamEvent`, CR-007 R19.1), so a change in the server's events is a type
 * error here. One SSE event's data is `{run_id, seq, after_seq, ts, epoch, type, payload}`;
 * `seq` is null for transient events (tokens, turn status, helpers' progress), which are
 * never replayed. The data still comes from the network, so every field is checked.
 */
import type { Schemas } from "../api/client";
import { type Message, parseMessage } from "../api/messages";

/** One event of the session stream, as the spec describes it. */
export type SessionEvent = Schemas["SessionStreamEvent"];

/** The spec's turn statuses, plus the UI's own `ended`: over, outcome unknown (learned
 * from the session, not the stream). */
export type TurnStatus = Schemas["TurnStatus"] | "ended";

export const TERMINAL: ReadonlySet<TurnStatus> = new Set(["completed", "failed", "cancelled", "ended"]);

export type HelperStatus = Schemas["HelperStatus"];

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

// Records over the spec's unions: a type the spec adds and this file doesn't list fails
// `tsc`, so the UI can't silently miss an event or a status.
const HANDLED: Record<SessionEvent["type"], true> = {
  "message.created": true,
  token: true,
  "turn.status": true,
  "subagent.spawned": true,
  "subagent.progress": true,
  "subagent.completed": true,
};
const TURN_STATUSES: Record<Schemas["TurnStatus"], true> = {
  queued: true,
  running: true,
  waiting_approval: true,
  completed: true,
  failed: true,
  cancelled: true,
};
const HELPER_END: Record<Exclude<HelperStatus, "running">, true> = {
  completed: true,
  failed: true,
  cancelled: true,
  timed_out: true,
};

/** The SSE event names the session stream sends (EventSource needs each by name). */
export const EVENT_NAMES = Object.keys(HANDLED) as readonly SessionEvent["type"][];

interface Wire {
  run_id: string;
  seq: number | null;
  type: string;
  payload: Record<string, unknown>;
}

function isWire(v: unknown): v is Wire {
  if (typeof v !== "object" || v === null) return false;
  const w = v as Record<string, unknown>;
  return typeof w.run_id === "string" && typeof w.payload === "object" && w.payload !== null;
}

function isTurnStatus(v: unknown): v is Schemas["TurnStatus"] {
  return typeof v === "string" && Object.hasOwn(TURN_STATUSES, v);
}

function isHelperEnd(v: unknown): v is Exclude<HelperStatus, "running"> {
  return typeof v === "string" && Object.hasOwn(HELPER_END, v);
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
      if (!isTurnStatus(p.status)) return null;
      return {
        kind: "turn",
        runId: typeof p.run_id === "string" ? p.run_id : wire.run_id,
        status: p.status,
        reason: typeof p.reason === "string" ? p.reason : null,
      };
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
      if (name === "subagent.completed" && isHelperEnd(p.status)) action.status = p.status;
      return action;
    }
    default:
      return null;
  }
}
