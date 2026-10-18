/** The Studio's server state (TanStack Query) and its commands. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "../api/client";
import type { AgentDocument } from "./editor";

export type StudioAgent = Schemas["StudioAgentView"];
export type DraftProposal = Schemas["DraftProposal"];
export interface InstructionsProposal {
  instructions: string;
  what_changed: string;
}

export const studioKeys = {
  catalog: ["studio", "catalog"] as const,
  agents: ["studio", "agents"] as const,
  agent: (id: string) => ["studio", "agent", id] as const,
};

export function useCatalog() {
  return useQuery({ queryKey: studioKeys.catalog, queryFn: () => unwrap(api.GET("/studio/catalog")), staleTime: Infinity });
}

export function useStudioAgents() {
  return useQuery({ queryKey: studioKeys.agents, queryFn: () => unwrap(api.GET("/studio/agents")) });
}

export function useStudioAgent(id: string) {
  return useQuery({
    queryKey: studioKeys.agent(id),
    queryFn: () => unwrap(api.GET("/studio/agents/{agent_id}", { params: { path: { agent_id: id } } })),
  });
}

/** After any change: the agent, the lists (Studio, chat-able agents) are stale. */
export function useStudioRefresh() {
  const client = useQueryClient();
  return (agent?: StudioAgent) => {
    if (agent) client.setQueryData(studioKeys.agent(agent.id), agent);
    void client.invalidateQueries({ queryKey: studioKeys.agents });
    void client.invalidateQueries({ queryKey: ["agents"] });
  };
}

export const studio = {
  create: (body: { display_name: string; description: string; copy_of: string | null }) =>
    unwrap(api.POST("/studio/agents", { body })),
  save: (id: string, document: AgentDocument) =>
    unwrap(api.PUT("/studio/agents/{agent_id}/draft", { params: { path: { agent_id: id } }, body: document })),
  edit: (id: string) => unwrap(api.POST("/studio/agents/{agent_id}/edit", { params: { path: { agent_id: id } } })),
  discard: (id: string) => unwrap(api.DELETE("/studio/agents/{agent_id}/draft", { params: { path: { agent_id: id } } })),
  publish: (id: string, changelog: string | null) =>
    unwrap(api.POST("/studio/agents/{agent_id}/publish", { params: { path: { agent_id: id } }, body: { changelog } })),
  restore: (id: string, number: number) =>
    unwrap(api.POST("/studio/agents/{agent_id}/versions/{number}/restore", { params: { path: { agent_id: id, number } } })),
  archive: (id: string) => unwrap(api.POST("/studio/agents/{agent_id}/archive", { params: { path: { agent_id: id } } })),
  testChat: (id: string) => unwrap(api.POST("/studio/agents/{agent_id}/test-chat", { params: { path: { agent_id: id } } })),
  /** The raw file is the body (no multipart): small, and checked by the server. */
  importFile: async (file: File): Promise<StudioAgent> => {
    const response = await fetch(`/api/studio/import?filename=${encodeURIComponent(file.name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    });
    const body = (await response.json()) as StudioAgent & { detail?: string };
    if (!response.ok) throw new Error(body.detail ?? `import failed (HTTP ${String(response.status)})`);
    return body;
  },
  /** The builder agents (R17.3): each returns a run whose answer `assist` reads. */
  describe: (description: string) => unwrap(api.POST("/studio/describe", { body: { description } })),
  improve: (id: string) => unwrap(api.POST("/studio/agents/{agent_id}/improve", { params: { path: { agent_id: id } } })),
  fromProposal: (proposal: DraftProposal) => unwrap(api.POST("/studio/agents/from-proposal", { body: proposal })),
  exportUrl: (id: string, version?: number) =>
    `/api/studio/agents/${encodeURIComponent(id)}/export${version ? `?version=${String(version)}` : ""}`,
};

export function useCreateAgent(onDone: (agent: StudioAgent) => void) {
  const refresh = useStudioRefresh();
  return useMutation({
    mutationFn: studio.create,
    onSuccess: (agent) => {
      refresh(agent);
      onDone(agent);
    },
  });
}

/** A builder's answer: polled while it works (a second or two offline, longer on a model). */
export function useAssist(runId: string | null) {
  return useQuery({
    queryKey: ["studio", "assist", runId ?? ""],
    queryFn: () => unwrap(api.GET("/studio/assist/{run_id}", { params: { path: { run_id: runId ?? "" } } })),
    enabled: runId !== null,
    refetchInterval: (query) => (query.state.data?.status === "working" || query.state.data === undefined ? 1000 : false),
  });
}
