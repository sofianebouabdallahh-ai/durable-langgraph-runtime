import { describe, expect, it } from "vitest";

import { logsLink, traceLink } from "./trace";

const id = "4bf92f3577b34da6a3ce929d0e0e4736";
const run = "01a15cae-38eb-7183-bbb6-a53d5710e8b1";
const on = { tracing: true, trace_ui_url: "http://localhost:3001/" };

interface Pane {
  datasource: string;
  queries: Record<string, unknown>[];
}

function pane(link: string | null): Pane {
  const url = new URL(link ?? "");
  expect(`${url.origin}${url.pathname}`).toBe("http://localhost:3001/explore");
  const panes = JSON.parse(url.searchParams.get("panes") ?? "{}") as Record<string, Pane>;
  return panes.a ?? { datasource: "", queries: [] };
}

describe("traceLink", () => {
  it("opens the run's trace in Grafana (Tempo) when tracing is on", () => {
    const a = pane(traceLink(on, id));
    expect(a.datasource).toBe("tempo");
    expect(a.queries[0]).toMatchObject({ queryType: "traceql", query: id });
  });
  it("shows nothing when tracing is off, unlinked or the run has no trace", () => {
    expect(traceLink({ tracing: false, trace_ui_url: "http://localhost:3001" }, id)).toBeNull();
    expect(traceLink({ tracing: true, trace_ui_url: null }, id)).toBeNull();
    expect(traceLink(on, null)).toBeNull();
    expect(traceLink(undefined, id)).toBeNull();
  });
  it("never builds a link from something that isn't a trace id", () => {
    expect(traceLink(on, "../../admin")).toBeNull();
  });
});

describe("logsLink", () => {
  it("opens every line of the run in Grafana (Loki)", () => {
    const a = pane(logsLink(on, run));
    expect(a.datasource).toBe("loki");
    expect(a.queries[0]).toMatchObject({ expr: `{service_name=~".+"} | run_id="${run}"` });
  });
  it("never puts anything but a run id into the query", () => {
    expect(logsLink(on, `${run}"} or {x="`)).toBeNull();
    expect(logsLink({ tracing: false, trace_ui_url: "http://g" }, run)).toBeNull();
  });
});
