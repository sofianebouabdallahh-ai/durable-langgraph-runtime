/**
 * Feedback, as text the person sees before anything leaves (phase L5, §4.8).
 *
 * A GitHub issue form is pre-filled from the URL: one query parameter per field
 * (`?template=feedback.yml&title=…&doing=…`). Nothing is sent: the browser opens
 * GitHub's page, and the person reviews and submits it there. URLs longer than
 * ~8 KB are cut by browsers and GitHub, so each field is capped, and "Download"
 * keeps the full text.
 */
export const REPO = "https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime";
const FIELD_MAX = 1500; // × 4 fields + details < 8 KB, encoded

export interface Feedback {
  doing: string;
  happened: string;
  feeling: number | null; // 1–5
}

export interface Installation {
  version: string | null;
  model_provider: string;
  browser: string;
}

export const FEELINGS = ["", "Frustrating", "Annoying", "Okay", "Good", "Delightful"] as const;

export function details(installation: Installation | null, usage: Record<string, unknown> | null): string {
  const lines: string[] = [];
  if (installation) {
    lines.push(`Nuria ${installation.version ?? "(unknown version)"} · model: ${installation.model_provider} · ${installation.browser}`);
  }
  if (usage) lines.push("Usage counts: " + JSON.stringify(usage));
  return lines.join("\n");
}

function cap(text: string): string {
  return text.length <= FIELD_MAX ? text : text.slice(0, FIELD_MAX) + " … (cut: download the full text)";
}

export function feedbackTitle(f: Feedback): string {
  const first = (f.happened || f.doing).trim().split(/\n/)[0] ?? "";
  return `Feedback: ${first.slice(0, 70) || "(no summary)"}`;
}

/** The issue page, pre-filled. Only what the person typed or ticked. */
export function feedbackIssueUrl(f: Feedback, detailsText: string): string {
  const params = new URLSearchParams({ template: "feedback.yml", title: feedbackTitle(f) });
  if (f.doing.trim()) params.set("doing", cap(f.doing.trim()));
  if (f.happened.trim()) params.set("happened", cap(f.happened.trim()));
  if (f.feeling) params.set("feeling", `${String(f.feeling)} – ${FEELINGS[f.feeling]}`);
  if (detailsText) params.set("details", cap(detailsText));
  return `${REPO}/issues/new?${params.toString()}`;
}

/** The same report as a file, for email (nothing cut). */
export function feedbackMarkdown(f: Feedback, detailsText: string): string {
  return [
    `# ${feedbackTitle(f)}`,
    "",
    "## What were you doing?",
    f.doing.trim() || "—",
    "",
    "## What happened?",
    f.happened.trim() || "—",
    "",
    "## How did it feel?",
    f.feeling ? `${String(f.feeling)}/5 – ${FEELINGS[f.feeling]}` : "—",
    ...(detailsText ? ["", "## Details", detailsText] : []),
    "",
  ].join("\n");
}

/** "Report this reply": the issue for an agent that didn't do what was expected. */
export function replyIssueUrl(runId: string, version: string | null, agent: string): string {
  const params = new URLSearchParams({
    template: "agent-behaviour.yml",
    title: `Agent "${agent}" didn't do what I expected`,
    run: `${runId} · Nuria ${version ?? "(unknown)"}`,
  });
  return `${REPO}/issues/new?${params.toString()}`;
}

export function browserName(ua: string): string {
  const os = ua.includes("Mac OS X") ? "macOS" : ua.includes("Windows") ? "Windows" : ua.includes("Linux") ? "Linux" : "another OS";
  const browser = ua.includes("Edg/") ? "Edge" : ua.includes("Firefox/") ? "Firefox" : ua.includes("Chrome/") ? "Chrome" : ua.includes("Safari/") ? "Safari" : "a browser";
  return `${browser} on ${os}`;
}
