/**
 * Where you are lives in the URL hash, so a reload, a bookmark or a second tab
 * shows the same place (AC20 relies on it for the chat). No server rewrites, no
 * router library: four routes.
 *   #/            home (start a chat)       #/s/<id>        a chat
 *   #/agents      the agents                #/agents/<name> one agent
 *   #/studio/<id> edit one of your agents (the Agent Studio)
 *   #/settings/models  your models and keys
 *   #/skills      the skill library
 */
import { useCallback, useSyncExternalStore } from "react";

export type Route =
  | { page: "home" }
  | { page: "chat"; sessionId: string }
  | { page: "agents" }
  | { page: "agent"; name: string }
  | { page: "studio"; agentId: string }
  | { page: "models" }
  | { page: "skills" };

export function parse(hash: string): Route {
  const [, kind, id] = hash.replace(/^#/, "").split("/");
  if (kind === "s" && id) return { page: "chat", sessionId: decodeURIComponent(id) };
  if (kind === "agents") return id ? { page: "agent", name: decodeURIComponent(id) } : { page: "agents" };
  if (kind === "studio" && id) return { page: "studio", agentId: decodeURIComponent(id) };
  if (kind === "settings" && id === "models") return { page: "models" };
  if (kind === "skills") return { page: "skills" };
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
      return `#/agents/${encodeURIComponent(route.name)}`;
    case "studio":
      return `#/studio/${encodeURIComponent(route.agentId)}`;
    case "models":
      return "#/settings/models";
    case "skills":
      return "#/skills";
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
