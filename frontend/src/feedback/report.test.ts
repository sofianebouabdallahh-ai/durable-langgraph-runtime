import { describe, expect, it } from "vitest";

import { browserName, details, feedbackIssueUrl, feedbackMarkdown, replyIssueUrl } from "./report";

const f = { doing: "Building an agent", happened: "The test chat\nwas slow", feeling: 4 };

describe("feedback", () => {
  it("pre-fills the issue form, field by field, with only what was typed", () => {
    const url = new URL(feedbackIssueUrl(f, ""));
    expect(url.origin + url.pathname).toBe("https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime/issues/new");
    const p = url.searchParams;
    expect(p.get("template")).toBe("feedback.yml");
    expect(p.get("title")).toBe("Feedback: The test chat");
    expect(p.get("doing")).toBe("Building an agent");
    expect(p.get("feeling")).toBe("4 – Good");
    expect(p.has("details")).toBe(false); // nothing ticked: nothing about the installation
  });

  it("keeps the URL under the limit browsers and GitHub accept", () => {
    const long = { doing: "x".repeat(20_000), happened: "y".repeat(20_000), feeling: 1 };
    const url = feedbackIssueUrl(long, "z".repeat(20_000));
    expect(url.length).toBeLessThan(8000);
    expect(new URL(url).searchParams.get("doing")).toContain("(cut: download the full text)");
    expect(feedbackMarkdown(long, "")).toContain("x".repeat(20_000)); // the download keeps it all
  });

  it("adds the installation and usage only when given", () => {
    const d = details({ version: "0.1.0", model_provider: "ollama", browser: "Firefox on Linux" }, { chats: 3 });
    expect(d).toBe('Nuria 0.1.0 · model: ollama · Firefox on Linux\nUsage counts: {"chats":3}');
    expect(details(null, null)).toBe("");
    expect(new URL(feedbackIssueUrl(f, d)).searchParams.get("details")).toBe(d);
  });

  it("reports a reply with its run and version, never its text", () => {
    const p = new URL(replyIssueUrl("run-1", "0.1.0", "trip planner")).searchParams;
    expect(p.get("template")).toBe("agent-behaviour.yml");
    expect(p.get("run")).toBe("run-1 · Nuria 0.1.0");
  });

  it("names the browser and OS in plain words", () => {
    expect(browserName("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15")).toBe("Safari on macOS");
    expect(browserName("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36 Edg/140.0")).toBe("Edge on Windows");
  });
});
