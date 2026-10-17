/**
 * Plain words for people who don't code (local-release §4.5): no "run", "epoch",
 * "lease" or tool identifiers on the main screens. The "What happened?" panel is
 * where the system's own vocabulary is allowed.
 */
import type { TurnStatus } from "../stream/events";

const TOOLS: Record<string, string> = {
  calculator: "Calculator",
  search: "Search",
  retrieve: "Documents",
  save_note: "Saved a note",
  notify: "Notification",
};

/** An agent's display name. The general assistant is Nuria herself. */
export function agentLabel(name: string | null | undefined): string {
  if (!name || name === "chat") return "Nuria";
  return name.replaceAll(/[-_]/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function toolLabel(tool: string): string {
  return TOOLS[tool] ?? tool.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** What a tool does, in a few words (the Agents page). */
export function toolPurpose(tool: string): string {
  switch (tool) {
    case "calculator":
      return "Exact arithmetic";
    case "search":
      return "Searches the documents it was given";
    case "retrieve":
      return "Reads from the knowledge base";
    case "save_note":
      return "Keeps notes you want to remember";
    case "notify":
      return "Sends messages to people, only with your approval";
    default:
      return "";
  }
}

/** An agent's limits, in plain words. */
export function limitLines(limits: Record<string, unknown>, maxTurns?: number): string[] {
  const out: string[] = [];
  if (typeof maxTurns === "number") out.push(`Up to ${String(maxTurns)} steps per message`);
  if (typeof limits.max_tool_calls === "number") out.push(`At most ${String(limits.max_tool_calls)} tool uses per message`);
  if (typeof limits.timeout_s === "number") {
    const m = Math.round(limits.timeout_s / 60);
    out.push(m >= 1 ? `Stops after ${String(m)} minute${m === 1 ? "" : "s"}` : `Stops after ${String(limits.timeout_s)} seconds`);
  }
  return out;
}

export function turnLabel(status: TurnStatus | undefined): string {
  switch (status) {
    case "queued":
      return "Waiting for a free worker…";
    case "running":
      return "Thinking…";
    case "waiting_approval":
      return "Waiting for your approval";
    default:
      return "";
  }
}

export function errorText(reason: string, budgetLimited: boolean): string {
  if (reason === "cancel_requested") return "Stopped.";
  if (budgetLimited) return "Stopped early: it reached its limit for one message.";
  if (reason.startsWith("timeout")) return "Stopped: it took too long.";
  return `Something went wrong (${reason}).`;
}

/** Why an action waits for a person, without the policy's vocabulary. */
export function approvalReason(reason: string | null): string {
  if (reason?.includes("external")) return "It reaches outside this chat (real people or systems), so it waits for your OK.";
  return "It needs your OK before it runs.";
}

export function helperStatusLabel(status: string): string {
  switch (status) {
    case "running":
      return "Working";
    case "completed":
      return "Done";
    case "timed_out":
      return "Took too long";
    case "cancelled":
      return "Stopped";
    case "failed":
      return "Failed";
    default:
      return status;
  }
}

const text = (v: unknown): string => (typeof v === "string" ? v : "");

/** One line of "What happened?" for a run event, or null to hide it. */
export function eventLine(type: string, payload: Record<string, unknown>): string | null {
  const worker = typeof payload.worker === "string" ? ` (${payload.worker})` : "";
  switch (type) {
    case "run.created":
      return "Your message was queued";
    case "run.started":
      return `A worker picked it up${worker}`;
    case "tool.called":
      return `Used ${toolLabel(text(payload.tool) || "a tool")}`;
    case "tool.completed":
      return payload.cached === true ? "…reused the earlier result (no second side effect)" : null;
    case "interrupt.raised":
      return "Paused for your approval (no worker is held while it waits)";
    case "approval.decided":
      return `You ${payload.decision === "approve" ? "approved" : "rejected"} it`;
    case "run.resumed":
      return "Back in the queue after your decision";
    case "run.reclaimed":
      return "A worker stopped unexpectedly: another one took over and continued from the last saved step";
    case "run.released":
      return "A worker was shutting down and handed the message over";
    case "subagent.spawned":
      return `Started the helper ${text(payload.agent)}`;
    case "subagent.completed":
      return `The helper ${text(payload.agent)} finished (${helperStatusLabel(text(payload.status))})`;
    case "policy.decision":
      return `A safety rule applied: ${text(payload.decision)}`;
    case "run.completed":
      return "Done";
    case "run.failed":
      return `Failed: ${text(payload.reason)}`;
    case "run.cancelled":
      return "Stopped";
    default:
      return null;
  }
}
