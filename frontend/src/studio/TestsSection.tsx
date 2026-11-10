/**
 * The agent's tests (phase H6). Each test is a message and what should happen: the tools
 * it calls (or never calls), the approvals it asks for, what the answer says, and an
 * optional rubric a model grades it against. "Run tests" sends each one in its own test
 * chat (nothing that reaches people is really sent); a worker grades it when it ends. With
 * tests, publishing waits until every one passed on this draft.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, FlaskConical, Loader2, Play, Plus, Trash2, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, type Schemas, unwrap } from "../api/client";
import { problemText } from "../chat/problems";
import { href } from "../app/route";
import { Section, TextArea, TextField } from "../ui/form";
import { Button, Pill } from "../ui/primitives";
import { toolLabel } from "../ui/words";
import { studioKeys } from "./api";

type CaseView = Schemas["CaseView"];
type Case = Schemas["Case"];

const keys = { tests: (id: string) => ["studio", "tests", id] as const };

export function TestsSection({ agentId, tools, editable }: { agentId: string; tools: string[]; editable: boolean }) {
  const client = useQueryClient();
  const tests = useQuery({
    queryKey: keys.tests(agentId),
    queryFn: () => unwrap(api.GET("/studio/agents/{agent_id}/tests", { params: { path: { agent_id: agentId } } })),
    // While a test runs, ask again: a worker grades it when its turn ends.
    refetchInterval: (q) => (q.state.data?.cases.some((c) => c.result?.status === "running") ? 2_000 : false),
  });
  // When the last running test settles, the publish gate may have opened: refresh it.
  const anyRunning = tests.data?.cases.some((c) => c.result?.status === "running") ?? false;
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !anyRunning) void client.invalidateQueries({ queryKey: studioKeys.agent(agentId) });
    wasRunning.current = anyRunning;
  }, [anyRunning, agentId, client]);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const refresh = () => {
    void client.invalidateQueries({ queryKey: keys.tests(agentId) });
    void client.invalidateQueries({ queryKey: studioKeys.agent(agentId) }); // the publish gate
  };
  const path = { params: { path: { agent_id: agentId } } };
  const runAll = async () => {
    setNotice(null);
    setRunning(true);
    try {
      await unwrap(api.POST("/studio/agents/{agent_id}/tests/run", path));
      refresh();
    } catch (e) {
      setNotice(problemText(e));
    } finally {
      setRunning(false);
    }
  };
  const cases = tests.data?.cases ?? [];
  return (
    <Section
      title="Tests"
      description="What it should do, checked on every draft. With tests, publishing waits until each one passes."
      icon={<FlaskConical aria-hidden className="size-4" />}
      testId="section-tests"
      aside={
        cases.length > 0 && (
          <span className="text-xs text-stone-500" data-testid="tests-passing">
            {tests.data?.passing ?? 0} of {cases.length} passed on this draft
          </span>
        )
      }
    >
      <div className="space-y-3">
        {cases.length === 0 && !adding && (
          <p className="text-sm text-stone-500">No tests yet. Add one, or press 👎 on a reply in a chat with it and choose “Make this a test”.</p>
        )}
        {cases.map((c) => (
          <TestRow key={c.id} agentId={agentId} view={c} editable={editable} onChanged={refresh} />
        ))}
        {adding && (
          <NewTest
            agentId={agentId}
            tools={tools}
            onDone={() => {
              setAdding(false);
              refresh();
            }}
          />
        )}
        {notice && (
          <p role="alert" className="text-sm text-rose-700 dark:text-rose-300">
            {notice}
          </p>
        )}
        {editable && (
          <div className="flex flex-wrap gap-2">
            {!adding && (
              <Button
                size="sm"
                onClick={() => {
                  setAdding(true);
                }}
              >
                <Plus aria-hidden className="size-4" /> Add a test
              </Button>
            )}
            {cases.length > 0 && (
              <Button size="sm" variant="primary" disabled={running} onClick={() => void runAll()} data-testid="run-tests">
                {running ? <Loader2 aria-hidden className="size-4 animate-spin motion-reduce:animate-none" /> : <Play aria-hidden className="size-4" />} Run tests
              </Button>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

function Outcome({ view }: { view: CaseView }) {
  const r = view.result;
  if (!r) return <Pill>Not run yet</Pill>;
  if (!r.current) return <Pill>Out of date</Pill>;
  if (r.status === "running") return <Pill tone="sun">Running…</Pill>;
  if (r.status === "passed") return <Pill tone="green">Passed</Pill>;
  if (r.status === "error") return <Pill tone="amber">Couldn't grade</Pill>;
  return <Pill tone="rose">Failed</Pill>;
}

function TestRow({ agentId, view, editable, onChanged }: { agentId: string; view: CaseView; editable: boolean; onChanged: () => void }) {
  const remove = async () => {
    await api.DELETE("/studio/agents/{agent_id}/tests/{case_id}", { params: { path: { agent_id: agentId, case_id: view.id } } });
    onChanged();
  };
  const failed = (view.result?.checks ?? []).filter((c) => !c.ok);
  return (
    <div className="rounded-xl border border-stone-200 p-3 text-sm dark:border-stone-800" data-testid="test-case">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{view.case.name}</span>
        <Outcome view={view} />
        {editable && (
          <button type="button" className="ml-auto rounded-lg p-1 text-stone-400 hover:bg-stone-100 hover:text-rose-600 dark:hover:bg-stone-800" aria-label={`Remove the test ${view.case.name}`} onClick={() => void remove()}>
            <Trash2 aria-hidden className="size-4" />
          </button>
        )}
      </div>
      <p className="mt-1 truncate text-stone-600 dark:text-stone-400">“{view.case.message}”</p>
      <p className="mt-1 text-xs text-stone-500">{expectations(view.case)}</p>
      {view.result?.current && failed.length > 0 && (
        <ul className="mt-2 space-y-1" aria-label="What didn't pass">
          {failed.map((c) => (
            <li key={c.check} className="flex items-start gap-1.5 text-xs">
              {c.error ? <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-amber-600" /> : <XCircle aria-hidden className="mt-0.5 size-3.5 shrink-0 text-rose-600" />}
              <span>
                <strong className="font-medium">{c.check}</strong>
                {c.detail && <>: {c.detail}</>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {view.result?.current && view.result.status === "passed" && (
        <p className="mt-2 inline-flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-400">
          <CheckCircle2 aria-hidden className="size-3.5" /> All {view.result.checks.length} checks passed
        </p>
      )}
      {view.result?.session_id && (
        <a className="mt-1 block text-xs text-stone-500 underline" href={href({ page: "chat", sessionId: view.result.session_id })}>
          See its test chat
        </a>
      )}
    </div>
  );
}

function expectations(c: CaseView["case"]): string {
  const e = c.expect;
  if (!e) return "it finishes";
  const parts: string[] = [];
  if (e.tools?.length) parts.push(`calls ${e.tools.map(toolLabel).join(", ")}`);
  if (e.not_tools?.length) parts.push(`never ${e.not_tools.map(toolLabel).join(", ")}`);
  if (e.approvals?.length) parts.push(`asks before ${e.approvals.map(toolLabel).join(", ")}`);
  if (e.answer_contains?.length) parts.push(`says ${e.answer_contains.map((w) => `“${w}”`).join(", ")}`);
  if (e.judge) parts.push(`a model checks: ${e.judge}`);
  if (e.status !== "completed") parts.push(`ends ${e.status}`);
  if (!c.approve) parts.push("the test rejects what it asks");
  return parts.join(" · ") || "it finishes";
}

function NewTest({ agentId, tools, onDone }: { agentId: string; tools: string[]; onDone: () => void }) {
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [calls, setCalls] = useState<string[]>([]);
  const [says, setSays] = useState("");
  const [judge, setJudge] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setError(null);
    const words = says.split(",").map((w) => w.trim()).filter(Boolean);
    const body: Case = {
      name: name.trim() || message.trim().slice(0, 60),
      message: message.trim(),
      approve: true,
      expect: { status: "completed", tools: calls, answer_contains: words, ...(judge.trim() ? { judge: judge.trim() } : {}) },
    };
    try {
      await unwrap(api.POST("/studio/agents/{agent_id}/tests", { params: { path: { agent_id: agentId } }, body }));
      onDone();
    } catch (e) {
      setError(problemText(e));
    }
  };
  return (
    <div className="space-y-3 rounded-xl border border-stone-200 p-3 dark:border-stone-800" data-testid="new-test">
      <TextField label="Name" value={name} onChange={(e) => { setName(e.target.value); }} placeholder="e.g. finds a hotel and gives its price" />
      <TextArea label="The message" value={message} onChange={(e) => { setMessage(e.target.value); }} rows={2} placeholder="What a person asks it" />
      {tools.length > 0 && (
        <fieldset>
          <legend className="text-sm font-medium">It should use</legend>
          <div className="mt-1 flex flex-wrap gap-3">
            {tools.map((t) => (
              <label key={t} className="inline-flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={calls.includes(t)}
                  onChange={(e) => {
                    setCalls(e.target.checked ? [...calls, t] : calls.filter((x) => x !== t));
                  }}
                />
                {toolLabel(t)}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <TextField label="The answer says (comma-separated, optional)" value={says} onChange={(e) => { setSays(e.target.value); }} placeholder="e.g. price, address" />
      <TextArea label="A model checks the answer against (optional)" value={judge} onChange={(e) => { setJudge(e.target.value); }} rows={2} placeholder="e.g. Gives a price per night and says where it comes from" />
      {error && (
        <p role="alert" className="text-sm text-rose-700 dark:text-rose-300">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button size="sm" variant="primary" disabled={!message.trim()} onClick={() => void save()}>
          Save the test
        </Button>
        <Button size="sm" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
