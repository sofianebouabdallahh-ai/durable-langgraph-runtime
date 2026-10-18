import { describe, expect, it } from "vitest";

import { traceLink } from "./trace";

const id = "4bf92f3577b34da6a3ce929d0e0e4736";

describe("traceLink", () => {
  it("links to the run's trace when tracing is on", () => {
    expect(traceLink({ tracing: true, trace_ui_url: "http://localhost:16686/" }, id)).toBe(`http://localhost:16686/trace/${id}`);
  });
  it("shows nothing when tracing is off, unlinked or the run has no trace", () => {
    expect(traceLink({ tracing: false, trace_ui_url: "http://localhost:16686" }, id)).toBeNull();
    expect(traceLink({ tracing: true, trace_ui_url: null }, id)).toBeNull();
    expect(traceLink({ tracing: true, trace_ui_url: "http://j" }, null)).toBeNull();
    expect(traceLink(undefined, id)).toBeNull();
  });
  it("never builds a link from something that isn't a trace id", () => {
    expect(traceLink({ tracing: true, trace_ui_url: "http://j" }, "../../admin")).toBeNull();
  });
});
