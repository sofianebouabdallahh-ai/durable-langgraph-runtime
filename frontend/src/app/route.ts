/**
 * Where you are lives in the URL hash, so a reload, a bookmark or a second tab
 * shows the same place (AC20 relies on it for the chat). No server rewrites, no
 * router library: four routes.
 *   #/            home (start a chat)       #/s/<id>        a chat
 *   #/agents      the agents                #/agents/<name> one agent (/memory: what it remembers)
 *   #/studio/<id> edit one of your agents (the Agent Studio)
 *   #/settings/models  your models and keys
 *   #/settings/tools   what the tools use (web search, sites)    #/settings/privacy  usage counts (opt-in)
 *   #/skills      the skill library
 *   #/start       Getting started: a guided first agent
 *   #/activity    what all agents have been doing    #/activity/turns/<id>  one turn
 *   #/activity/audit   who changed what
 */
import { useCallback, useSyncExternalStore } from "react";

export type Route =
  | { page: "home" }
  | { page: "chat"; sessionId: string }
  | { page: "agents" }
  | { page: "agent"; name: string; section?: "memory" }
  | { page: "studio"; agentId: string }
  | { page: "models" }
  | { page: "tools" }
  | { page: "privacy" }
  | { page: "skills" }
  | { page: "start" }
  | { page: "activity" }
  | { page: "turn"; runId: string }
  | { page: "audit" };

export function parse(hash: string): Route {
  const [, kind, id] = hash.replace(/^#/, "").split("/");
  if (kind === "s" && id) return { page: "chat", sessionId: decodeURIComponent(id) };
  if (kind === "agents" && id) {
    const memory = hash.replace(/^#/, "").split("/")[3] === "memory";
    return memory ? { page: "agent", name: decodeURIComponent(id), section: "memory" } : { page: "agent", name: decodeURIComponent(id) };
  }
  if (kind === "agents") return { page: "agents" };
  if (kind === "studio" && id) return { page: "studio", agentId: decodeURIComponent(id) };
  if (kind === "settings" && id === "models") return { page: "models" };
  if (kind === "settings" && id === "tools") return { page: "tools" };
  if (kind === "settings" && id === "privacy") return { page: "privacy" };
  if (kind === "skills") return { page: "skills" };
  if (kind === "start") return { page: "start" };
  if (kind === "activity" && id === "audit") return { page: "audit" };
  if (kind === "activity") {
    const runId = hash.replace(/^#/, "").split("/")[3];
    return runId ? { page: "turn", runId: decodeURIComponent(runId) } : { page: "activity" };
  }
  return { page: "home" };
}

export function href(route: Route): string {
  switch (route.page) {
    case "home":
      return "#/";
    case "chat":
      return `#/s/${encodeURIComponent(route.sessionId)}`;
    case "agents":
      return "#/agents";
    case "agent":
      return `#/agents/${encodeURIComponent(route.name)}${route.section ? `/${route.section}` : ""}`;
    case "studio":
      return `#/studio/${encodeURIComponent(route.agentId)}`;
    case "models":
      return "#/settings/models";
    case "tools":
      return "#/settings/tools";
    case "privacy":
      return "#/settings/privacy";
    case "skills":
      return "#/skills";
    case "start":
      return "#/start";
    case "activity":
      return "#/activity";
    case "turn":
      return `#/activity/turns/${encodeURIComponent(route.runId)}`;
    case "audit":
      return "#/activity/audit";
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => {
    window.removeEventListener("hashchange", onChange);
  };
}

const read = () => window.location.hash;

export function useRoute(): [Route, (route: Route) => void] {
  const hash = useSyncExternalStore(subscribe, read, () => "");
  const go = useCallback((route: Route) => {
    window.location.hash = href(route);
  }, []);
  return [parse(hash), go];
}
