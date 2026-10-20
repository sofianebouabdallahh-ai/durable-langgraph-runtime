/** Settings → Models: server state and commands. Keys go in, never come back. */
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "../api/client";

export type Connection = Schemas["ConnectionView"];
export type Kind = Connection["kind"];

export const modelKeys = { connections: ["models", "connections"] as const, default: ["models", "default"] as const };

export function useConnections() {
  return useQuery({ queryKey: modelKeys.connections, queryFn: () => unwrap(api.GET("/models/connections")) });
}

export function useDefaultModel() {
  return useQuery({ queryKey: modelKeys.default, queryFn: () => unwrap(api.GET("/models/default")) });
}

export function useModelsRefresh() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["models"] });
    void client.invalidateQueries({ queryKey: ["studio"] }); // publish blockers name models
    void client.invalidateQueries({ queryKey: ["onboarding"] }); // Getting started's model step
  };
}

export const models = {
  add: (body: Schemas["AddConnection"]) => unwrap(api.POST("/models/connections", { body })),
  edit: (id: string, body: Schemas["EditConnection"]) =>
    unwrap(api.PATCH("/models/connections/{connection_id}", { params: { path: { connection_id: id } }, body })),
  remove: (id: string) => api.DELETE("/models/connections/{connection_id}", { params: { path: { connection_id: id } } }),
  test: (id: string, model: string) =>
    unwrap(api.POST("/models/connections/{connection_id}/test", { params: { path: { connection_id: id } }, body: { model } })),
  remoteModels: (id: string) =>
    unwrap(api.GET("/models/connections/{connection_id}/models", { params: { path: { connection_id: id } } })),
  ollama: () => unwrap(api.GET("/models/ollama")),
  setDefault: (connectionId: string | null, model: string | null) =>
    unwrap(api.PUT("/models/default", { body: { connection_id: connectionId, model } })),
};

/** What a person picks in the Studio: a role ("chat" = the default) or `<connection>:<model>`. */
export interface ModelChoice {
  value: string;
  label: string;
  ready: boolean;
}

export function modelChoices(connections: readonly Connection[]): ModelChoice[] {
  return connections.flatMap((c) =>
    c.models.map((m) => ({ value: `${c.name}:${m}`, label: `${c.display_name} · ${m}`, ready: c.test_status === "ready" && c.tested_model !== null })),
  );
}

export const KINDS: Record<Kind, { label: string; blurb: string; url: string; keyLabel: string | null; modelLabel: string; help: string }> = {
  ollama: {
    label: "Ollama",
    blurb: "Free models on this computer",
    url: "http://host.docker.internal:11434",
    keyLabel: null,
    modelLabel: "Model",
    help: "Install Ollama (ollama.com), then pull a model that can use tools, e.g. `ollama pull qwen2.5:7b`.",
  },
  openai: {
    label: "OpenAI",
    blurb: "GPT models with your OpenAI key",
    url: "https://api.openai.com/v1",
    keyLabel: "API key",
    modelLabel: "Model",
    help: "Create a key at platform.openai.com → API keys. It's saved encrypted on this computer and never shown again.",
  },
  azure_foundry: {
    label: "Azure AI Foundry",
    blurb: "A deployment in your Azure resource",
    url: "https://<your-resource>.openai.azure.com",
    keyLabel: "Key",
    modelLabel: "Deployment name",
    help: "In Azure AI Foundry: your resource's endpoint and key (Keys and Endpoint), and the name you gave the deployment.",
  },
  compatible: {
    label: "Other service",
    blurb: "Any OpenAI-compatible API",
    url: "https://",
    keyLabel: "Key (if it needs one)",
    modelLabel: "Model",
    help: "Many services speak the OpenAI API (vLLM, LM Studio, Groq, Together…). Paste its base URL, ending in /v1.",
  },
};
