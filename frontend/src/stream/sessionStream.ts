/**
 * The session stream behind a small interface (Pattern: Adapter), so the reducer
 * and the components never touch EventSource.
 *
 * Resuming without loss or duplicates (AC20):
 * - a new connection asks for `?after_seq=<the last message we hold>`;
 * - the browser's own reconnects send `Last-Event-ID` (the last `id:` it saw), which
 *   the server prefers;
 * - `event: reconnect` (the API replica is shutting down) and a closed connection
 *   (e.g. HTTP 503 while draining) → we reconnect ourselves, from our last message,
 *   after a jittered backoff. The proxy then routes us to a healthy replica.
 * Replayed messages we already hold are dropped by the reducer (by seq), so
 * at-least-once delivery shows each message exactly once.
 */
import { API_BASE } from "../api/client";
import { backoffMs, type ConnectionEvent } from "./connection";
import { decode, EVENT_NAMES, type StreamAction } from "./events";

export interface StreamHandlers {
  onAction: (action: StreamAction) => void;
  onConnection: (event: ConnectionEvent) => void;
  /** The last persisted message held: where a new connection resumes. */
  lastSeq: () => number;
}

type EventSourceFactory = (url: string) => EventSource;

export function openSessionStream(
  sessionId: string,
  handlers: StreamHandlers,
  create: EventSourceFactory = (url) => new EventSource(url),
): () => void {
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let attempts = 0;
  let closed = false;

  const connect = () => {
    if (closed) return;
    const url = `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/stream?after_seq=${handlers.lastSeq()}`;
    const es = create(url);
    source = es;
    es.onopen = () => {
      attempts = 0;
      handlers.onConnection({ type: "opened" });
    };
    es.onerror = () => {
      handlers.onConnection({ type: "dropped" });
      if (es.readyState === EventSource.CLOSED) retry(); // the browser gave up: our turn
    };
    for (const name of EVENT_NAMES) {
      es.addEventListener(name, (e: MessageEvent<string>) => {
        const action = decode(name, e.data);
        if (action) handlers.onAction(action);
      });
    }
    es.addEventListener("reconnect", () => {
      handlers.onConnection({ type: "drain" });
      es.close();
      retry(0);
    });
  };

  const retry = (delay?: number) => {
    source?.close();
    attempts += 1;
    clearTimeout(timer);
    timer = setTimeout(connect, delay ?? backoffMs(attempts));
  };

  handlers.onConnection({ type: "connect" });
  connect();
  return () => {
    closed = true;
    clearTimeout(timer);
    source?.close();
    handlers.onConnection({ type: "close" });
  };
}
