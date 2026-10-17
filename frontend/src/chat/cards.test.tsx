import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Message } from "../api/messages";
import { call, msg, result } from "../test/fixtures";
import { ApprovalCard, ErrorNote, HelperCards, ToolCard } from "./cards";
import { Composer } from "./ChatView";

type Of<T extends Message["type"]> = Extract<Message, { type: T }>;

describe("ToolCard", () => {
  it("shows plain words, and the input and result as text on demand", async () => {
    const c = call(1, "calculator", "c1", { expression: "<b>6*7</b>" }) as Of<"tool_call">;
    const r = result(2, "calculator", "c1", { value: 42 }) as Of<"tool_result">;
    const { container } = render(<ToolCard call={c} result={r} />);
    expect(screen.getByText("Calculator")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByText(/"value": 42/)).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull(); // tool data is never markup
  });

  it("shows a running and a failed call", () => {
    const c = call(1, "search", "c1") as Of<"tool_call">;
    const { rerender } = render(<ToolCard call={c} result={null} />);
    expect(screen.getByText("working…")).toBeInTheDocument();
    rerender(<ToolCard call={c} result={null} awaitingApproval />);
    expect(screen.getByText("waiting for your OK")).toBeInTheDocument();
    rerender(<ToolCard call={c} result={{ ...(result(2, "search", "c1", null) as Of<"tool_result">), error: "down", cached: true, durationMs: 1500 }} />);
    expect(screen.getByText("reused")).toBeInTheDocument();
    expect(screen.getByText("1.5 s")).toBeInTheDocument();
  });
});

describe("ApprovalCard", () => {
  const ask = msg(3, "interrupt", { kind: "tool_approval", tool: "notify", args: { to: "ops" }, reason: "external" }) as Of<"interrupt">;

  it("approves once, or rejects with a reason", async () => {
    const onDecide = vi.fn();
    const { unmount } = render(<ApprovalCard message={ask} decided={null} pending onDecide={onDecide} />);
    expect(screen.getByText(/wants to use: Notification/)).toBeInTheDocument();
    expect(screen.getByText(/reaches outside this chat/)).toBeInTheDocument(); // plain words, not "external"
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith("approve", null);
    unmount();
    render(<ApprovalCard message={ask} decided={null} pending onDecide={onDecide} />);
    await userEvent.type(screen.getByPlaceholderText("Reason (optional)"), "not now");
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(onDecide).toHaveBeenLastCalledWith("reject", "not now");
  });

  it("shows the decision once made, and no buttons when not pending", () => {
    const decided = msg(4, "approval", { decision: "reject", reason: null }) as Of<"approval">;
    render(<ApprovalCard message={ask} decided={decided} pending={false} />);
    expect(screen.getByText("You rejected this")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });
});

describe("HelperCards and ErrorNote", () => {
  it("shows each helper's progress or result", () => {
    render(<HelperCards helpers={[
      { handle: "a", runId: "r", agent: "researcher", task: "", status: "running", progress: "reading", percent: 40, summary: null },
      { handle: "b", runId: "r", agent: "data-analyst", task: "", status: "completed", progress: null, percent: null, summary: "48." },
    ]} />);
    expect(screen.getByText("reading")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
    expect(screen.getByText("48.")).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  it("says a stop calmly and an error as an alert", () => {
    const { rerender } = render(<ErrorNote message={msg(1, "error", { reason: "cancel_requested", budgetLimited: false }) as Of<"error">} />);
    expect(screen.getByText("Stopped.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    rerender(<ErrorNote message={msg(1, "error", { reason: "max_steps", budgetLimited: true }) as Of<"error">} />);
    expect(screen.getByRole("alert")).toHaveTextContent("reached its limit");
  });
});

describe("Composer", () => {
  it("sends on Enter, keeps Shift+Enter for new lines, and clears once accepted", async () => {
    const onSend = vi.fn().mockResolvedValue(true);
    render(<Composer busy={false} waitingApproval={false} onSend={onSend} onStop={vi.fn()} />);
    const box = screen.getByRole("textbox", { name: "Message" });
    await userEvent.type(box, "line one{Shift>}{Enter}{/Shift}line two{Enter}");
    expect(onSend).toHaveBeenCalledWith("line one\nline two");
    expect(box).toHaveValue("");
  });

  it("keeps the text when the server refuses it, and offers Stop while busy", async () => {
    const onSend = vi.fn().mockResolvedValue(false);
    const onStop = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(<Composer busy={false} waitingApproval={false} onSend={onSend} onStop={onStop} />);
    await userEvent.type(screen.getByRole("textbox"), "hello{Enter}");
    expect(screen.getByRole("textbox")).toHaveValue("hello");
    rerender(<Composer busy waitingApproval={false} onSend={onSend} onStop={onStop} />);
    await userEvent.click(screen.getByRole("button", { name: "Stop the reply" }));
    expect(onStop).toHaveBeenCalled();
  });
});
