/**
 * The chat's imperative shell (Pattern: Observer): the only place with side
 * effects. It feeds the pure reducer from
 * - the session stream (replay, then live), resumed from the last message held;
 * - GET /sessions/{id} on every (re)connect and every 10 s during a turn: turn
 *   status events are transient, so this is the safety net for a lost one;
 * - GET /runs/{id} for the turns that used helpers (their results, after a reload).
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useReducer, useRef } from "react";

import { api, unwrap } from "../api/client";
import { connection, initialConnection } from "../stream/connection";
import { TERMINAL, type HelperStatus } from "../stream/events";
import { openSessionStream } from "../stream/sessionStream";
import { HELPER_TOOLS } from "./selectors";
import { chat, initialChat, isBusy } from "./transcript";

export const SAFETY_NET_MS = 10_000;

export function useChat(sessionId: string) {
  const [state, dispatch] = useReducer(chat, initialChat);
  const [conn, dispatchConn] = useReducer(connection, initialConnection);
  const queryClient = useQueryClient();
  const lastSeq = useRef(0); // read by the stream when it (re)connects
  useEffect(() => {
    lastSeq.current = state.lastSeq;
  }, [state.lastSeq]);

  const refreshSession = useCallback(async () => {
    try {
      const s = await unwrap(api.GET("/sessions/{session_id}", { params: { path: { session_id: sessionId } } }));
      dispatch({ kind: "session", activeRunId: s.active_run_id ?? null, activeRunStatus: s.active_run_status ?? null });
      queryClient.setQueryData(["session", sessionId], s);
    } catch {
      // the stream's own reconnects report the outage; nothing to add here
    }
  }, [queryClient, sessionId]);

  useEffect(
    () =>
      openSessionStream(sessionId, {
        onAction: dispatch,
        onConnection: (event) => {
          dispatchConn(event);
          if (event.type === "opened") void refreshSession();
        },
        lastSeq: () => lastSeq.current,
      }),
    [sessionId, refreshSession],
  );

  const busy = isBusy(state);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void refreshSession(), SAFETY_NET_MS);
    return () => {
      clearInterval(timer);
    };
  }, [busy, refreshSession]);

  // A turn ended: the sidebar's order and the session's totals changed.
  const turnStatus = state.turn?.status;
  useEffect(() => {
    if (turnStatus && TERMINAL.has(turnStatus)) void queryClient.invalidateQueries({ queryKey: ["sessions"] });
  }, [turnStatus, queryClient]);

  // Helpers' results live on the run: load them for turns that used helpers, once
  // the turn is over (live progress comes from the stream meanwhile).
  const loaded = useRef(new Set<string>());
  const activeRun = busy ? state.turn?.runId : undefined;
  useEffect(() => {
    const runs = new Set<string>();
    for (const m of state.messages) {
      if (m.type === "tool_call" && HELPER_TOOLS.has(m.tool) && m.runId && m.runId !== activeRun) runs.add(m.runId);
    }
    for (const runId of runs) {
      if (loaded.current.has(runId)) continue;
      loaded.current.add(runId);
      void unwrap(api.GET("/runs/{run_id}", { params: { path: { run_id: runId } } }))
        .then((run) => {
          dispatch({
            kind: "helpers",
            runId,
            helpers: (run.subagents ?? []).map((s) => ({
              handle: s.handle,
              agent: s.agent,
              task: "",
              status: s.status as HelperStatus,
              progress: s.progress ?? null,
              percent: s.percent ?? null,
              summary: typeof s.result?.summary === "string" ? s.result.summary : null,
            })),
          });
        })
        .catch(() => loaded.current.delete(runId)); // try again on the next change
    }
  }, [state.messages, activeRun]);

  return { state, dispatch, connection: conn, refreshSession };
}
