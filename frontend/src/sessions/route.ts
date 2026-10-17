/**
 * The open chat lives in the URL (`#/s/<session id>`), so a reload, a bookmark or a
 * second tab shows the same conversation (AC20). A hash route needs no server
 * rewrite rules and no router library.
 */
import { useCallback, useSyncExternalStore } from "react";

const PREFIX = "#/s/";

function read(): string | null {
  const hash = window.location.hash;
  return hash.startsWith(PREFIX) ? decodeURIComponent(hash.slice(PREFIX.length)) || null : null;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => {
    window.removeEventListener("hashchange", onChange);
  };
}

export function useSessionRoute(): [string | null, (id: string | null) => void] {
  const current = useSyncExternalStore(subscribe, read, () => null);
  const go = useCallback((id: string | null) => {
    window.location.hash = id ? `${PREFIX}${encodeURIComponent(id)}` : "";
  }, []);
  return [current, go];
}
