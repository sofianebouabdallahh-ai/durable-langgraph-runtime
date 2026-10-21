/**
 * Sending a message, retry-safe: one Idempotency-Key per message, and a retry on a
 * transient failure (a replica restarting: 502/503/504, or a dropped connection)
 * reuses it, so the server returns the turn it already created instead of a second
 * one. Anything else (409 "still answering", 422, 429) is the caller's to show.
 */
import { api, ApiError, type Schemas, unwrap } from "./client";

const TRANSIENT = new Set([502, 503, 504]);
export const SEND_ATTEMPTS = 4;

export function newKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16)); // non-secure origins (a LAN address)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export async function sendMessage(
  sessionId: string,
  content: string,
  { key = newKey(), sleep = (ms: number) => new Promise((r) => setTimeout(r, ms)) } = {},
): Promise<Schemas["TurnAccepted"]> {
  for (let attempt = 1; ; attempt++) {
    try {
      return await unwrap(
        api.POST("/sessions/{session_id}/messages", {
          params: { path: { session_id: sessionId }, header: { "idempotency-key": key } },
          body: { content },
        }),
      );
    } catch (e) {
      // A 503 from a restarting replica passes; "every agent is stopped" (the kill switch) doesn't.
      const transient =
        (e instanceof ApiError && ((TRANSIENT.has(e.status) && !e.is("paused")) || e.is("duplicate-send"))) || e instanceof TypeError; // TypeError: the connection dropped
      if (!transient || attempt >= SEND_ATTEMPTS) throw e;
      await sleep(400 * 2 ** (attempt - 1));
    }
  }
}
