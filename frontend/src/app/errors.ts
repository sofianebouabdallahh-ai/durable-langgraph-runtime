/**
 * Errors in this page go to the API's log (phase L7a): POST /api/client-errors, logged
 * with the server's lines as `component=ui`. Nothing leaves the machine.
 *
 * Best effort and quiet: never throws, never retries, the same error once per page load,
 * at most MAX per page load (the API rate-limits too).
 */
import { API_BASE, ApiError } from "../api/client";

type Kind = "error" | "unhandledrejection" | "render";

const MAX = 20;
const seen = new Set<string>();

export function reportError(kind: Kind, error: unknown): void {
  const message = (error instanceof Error ? `${error.name}: ${error.message}` : String(error)).slice(0, 2000);
  const key = `${kind}:${message}`;
  if (seen.has(key) || seen.size >= MAX) return;
  seen.add(key);
  const body = {
    kind,
    message,
    stack: error instanceof Error && error.stack ? error.stack.slice(0, 8000) : null,
    route: window.location.hash.slice(0, 200) || "#/",
    failed_request_id: error instanceof ApiError ? error.requestId : null,
  };
  try {
    void globalThis
      .fetch(`${API_BASE}/client-errors`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        keepalive: true, // still sent if the page is closing
      })
      .catch(() => undefined);
  } catch {
    // reporting must never be the second error
  }
}

/** Uncaught errors and rejected promises, from anywhere in the page. */
export function installErrorReporting(): void {
  window.addEventListener("error", (e) => {
    reportError("error", e.error ?? e.message);
  });
  window.addEventListener("unhandledrejection", (e) => {
    reportError("unhandledrejection", e.reason);
  });
}
