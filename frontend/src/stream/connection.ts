/**
 * The stream connection's lifecycle, as a pure state machine (Pattern: State).
 * The adapter feeds it what EventSource reports; the UI shows one plain banner.
 *
 *   idle ─connect─► connecting ─opened─► open
 *   connecting|open ─dropped─► reconnecting ─opened─► open
 *   open ─drain─► connecting           (the server asked us to move: event: reconnect)
 *   reconnecting ─dropped (n times)─► offline ─opened─► open
 *   any ─close─► idle
 */
export type ConnectionState =
  | { status: "idle" }
  | { status: "connecting" }
  | { status: "open" }
  | { status: "reconnecting"; attempts: number }
  | { status: "offline"; attempts: number };

export type ConnectionEvent =
  | { type: "connect" }
  | { type: "opened" }
  | { type: "dropped" }
  | { type: "drain" }
  | { type: "close" };

/** After this many failed attempts in a row, say we're offline (and keep trying). */
export const OFFLINE_AFTER = 4;

export const initialConnection: ConnectionState = { status: "idle" };

export function connection(state: ConnectionState, event: ConnectionEvent): ConnectionState {
  switch (event.type) {
    case "connect":
      return state.status === "idle" ? { status: "connecting" } : state;
    case "opened":
      return state.status === "idle" ? state : { status: "open" };
    case "drain":
      return state.status === "idle" ? state : { status: "connecting" };
    case "dropped": {
      if (state.status === "idle") return state;
      const attempts = state.status === "reconnecting" || state.status === "offline" ? state.attempts + 1 : 1;
      return attempts >= OFFLINE_AFTER ? { status: "offline", attempts } : { status: "reconnecting", attempts };
    }
    case "close":
      return { status: "idle" };
  }
}

/** Delay before our own reconnect (not the browser's): exponential, capped, full jitter. */
export function backoffMs(attempts: number, random: () => number = Math.random): number {
  const cap = Math.min(10_000, 500 * 2 ** Math.max(0, attempts - 1));
  return Math.round(random() * cap);
}
