/** The Activity page's data (GET /activity…), cached by range and filters. */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, ApiError, type Schemas, unwrap } from "../api/client";

export type Range = "24h" | "7d" | "30d";
export type Activity = Schemas["ActivityView"];
export type Turn = Schemas["TurnRow"];

export interface Filters {
  range: Range;
  agent: string | null;
  tests: boolean;
}

const query = (f: Filters) => ({ range: f.range, agent: f.agent, include_tests: f.tests });

/** Refetch keeps the frame: the previous numbers stay (dimmed) while new ones load. */
export function useActivity(f: Filters) {
  return useQuery({
    queryKey: ["activity", f],
    queryFn: () => unwrap(api.GET("/activity", { params: { query: query(f) } })),
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  });
}

export function useSessions(f: Filters) {
  return useQuery({
    queryKey: ["activity", "sessions", f],
    queryFn: () => unwrap(api.GET("/activity/sessions", { params: { query: { ...query(f), limit: 20 } } })),
    placeholderData: keepPreviousData,
  });
}

export const turnsPage = (f: Filters, before?: string) =>
  unwrap(api.GET("/activity/turns", { params: { query: { ...query(f), limit: 25, before: before ?? null } } }));

export function useTurn(runId: string) {
  return useQuery({
    queryKey: ["activity", "turn", runId],
    queryFn: () => unwrap(api.GET("/activity/turns/{run_id}", { params: { path: { run_id: runId } } })),
    retry: (failures, error) => !(error instanceof ApiError && error.status === 404) && failures < 2,
  });
}
