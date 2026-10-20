import { ApiError } from "../api/client";

/** A chat's title from its first message, as people expect. */
export function titleFrom(text: string): string {
  const line = text.split("\n")[0]?.trim() ?? "";
  return line.length > 60 ? `${line.slice(0, 57)}…` : line || "New chat";
}

/** An API failure in plain words. */
export function problemText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.is("turn-active")) return "Nuria is still answering. Wait, or stop it first.";
    if (e.status === 429) return "Too many messages at once. Wait a moment and try again.";
    if (e.is("session-archived")) return "This chat is archived. Start a new one.";
    if (e.is("chat-limit")) return e.message; // "…reached its limit of N messages: start a new chat."
    if (e.is("agent-off")) return "This agent is switched off. Turn it back on (Agents, or its page in the Studio) to chat with it.";
    if (e.is("paused")) return "Every agent is stopped. Turn them back on (the banner at the top) to chat.";
    return e.message;
  }
  return "Couldn't reach the server. Check that Nuria is running (./setup.sh).";
}
