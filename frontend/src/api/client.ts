/**
 * The API client: types generated from the backend's OpenAPI spec (`make ui-api`),
 * a typed `fetch` (openapi-fetch), and one error type for problem+json responses.
 * Pattern: Adapter. Components never build URLs or parse errors themselves.
 */
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type SessionView = Schemas["SessionView"];
export type AgentView = Schemas["AgentView"];
export type RunView = Schemas["RunView"];
export type EventView = Schemas["EventView"];
export type AboutView = Schemas["AboutView"];

/** Same origin: nginx (or Vite in dev) proxies /api to the API, so there is no CORS. */
export const API_BASE = "/api";

export const api = createClient<paths>({ baseUrl: API_BASE });

/** RFC 9457 problem details, as the API returns them. */
interface Problem {
  type?: string;
  title?: string;
  detail?: string;
  status?: number;
}

export class ApiError extends Error {
  readonly status: number;
  readonly problemType: string | undefined;

  constructor(status: number, problem: Problem | undefined) {
    super(problem?.detail ?? problem?.title ?? `request failed (HTTP ${status})`);
    this.name = "ApiError";
    this.status = status;
    this.problemType = problem?.type;
  }

  /** e.g. `turn-active`, `session-archived`, from the problem's type URI. */
  is(kind: string): boolean {
    return this.problemType?.endsWith(`/${kind}`) ?? false;
  }
}

/** The data of a response, or an ApiError. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok || data === undefined) {
    throw new ApiError(response.status, isProblem(error) ? error : undefined);
  }
  return data;
}

function isProblem(value: unknown): value is Problem {
  return typeof value === "object" && value !== null;
}
