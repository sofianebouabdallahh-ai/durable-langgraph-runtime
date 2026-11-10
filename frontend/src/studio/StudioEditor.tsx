/**
 * The Agent Studio editor: the form on the left, a test chat on the right.
 *
 * The draft is autosaved (a debounced command) and validated by the server's one
 * validator; its issues come back by field. Publishing needs a valid draft and one
 * complete test-chat reply on exactly this draft (R17.3); the checklist says what's
 * missing. Publishing creates an immutable version (AC47).
 */
import { AlertTriangle, ArrowLeft, Check, CircleDashed, Download, History, Loader2, MessageSquarePlus, Pencil, RotateCcw, Send } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, unwrap } from "../api/client";
import { href, type Route } from "../app/route";
import { TestsSection } from "./TestsSection";
import { ChatView } from "../chat/ChatView";
import { problemText } from "../chat/problems";
import { AgentPowerButton } from "../safety/KillSwitch";
import { Dialog, TextField } from "../ui/form";
import { Avatar, Button, Pill, Spinner } from "../ui/primitives";
import { type AgentDocument, documentOf, type Edit, edit, unplaced } from "./editor";
import { studio, type StudioAgent, useCatalog, useStudioAgent, useStudioRefresh } from "./api";
import { BasicsSection, HelpersSection, InstructionsSection, LimitsSection, ModelSection, ProtectionsSection, ToolsSection } from "./sections";
import { ImproveInstructions, SkillsSection } from "./skills";
import { GuideStrip } from "../guide/GuideStrip";

type SaveState = "saved" | "saving" | "pending" | "error";
const AUTOSAVE_MS = 700;

export function StudioEditor({ agentId, go }: { agentId: string; go: (route: Route) => void }) {
  const agent = useStudioAgent(agentId);
  const catalog = useCatalog();
  if (agent.isPending || catalog.isPending) return <Spinner className="m-10" label="Opening the Studio…" />;
  if (agent.isError || catalog.isError) return <div className="m-10 text-rose-600">Couldn't open this agent.</div>;
  return <Editor key={agent.data.id} initial={agent.data} catalog={catalog.data} go={go} />;
}

function Editor({ initial, catalog, go }: { initial: StudioAgent; catalog: NonNullable<ReturnType<typeof useCatalog>["data"]>; go: (route: Route) => void }) {
  const refresh = useStudioRefresh();
  const server = useStudioAgent(initial.id);
  const state = server.data ?? initial;
  const editable = state.draft !== null;
  const [doc, setDoc] = useState<AgentDocument>(() => documentOf(state));
  const latest = useRef(doc);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [save, setSave] = useState<SaveState>("saved");
  const [notice, setNotice] = useState<string | null>(null);
  const [testChat, setTestChat] = useState<string | null>(null);
  // Back in the Studio: the test chat you were in is still there.
  useEffect(() => {
    let current = true;
    studio
      .lastTestChat(initial.id)
      .then((found) => {
        if (current && found) setTestChat((shown) => shown ?? found.id);
      })
      .catch(() => undefined); // no test chat to show: the panel offers to start one
    return () => {
      current = false;
    };
  }, [initial.id]);
  const [publishing, setPublishing] = useState(false);
  const [history, setHistory] = useState(false);

  /** Show a document from the server (after edit, restore, discard): no save. */
  const show = (next: AgentDocument) => {
    clearTimeout(timer.current);
    latest.current = next;
    setDoc(next);
    setSave("saved");
  };

  /** One edit: apply it, then autosave after a pause in typing (a debounced command). */
  const dispatch = (e: Edit) => {
    const next = edit(latest.current, e);
    latest.current = next;
    setDoc(next);
    setSave("pending");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setSave("saving");
      studio
        .save(state.id, next)
        .then((saved) => {
          refresh(saved);
          if (latest.current === next) setSave("saved");
        })
        .catch(() => {
          setSave("error");
        });
    }, AUTOSAVE_MS);
  };

  // A finished test reply may have just made the draft "tested": ask the server.
  const recheck = useCallback(() => {
    void unwrap(api.GET("/studio/agents/{agent_id}", { params: { path: { agent_id: state.id } } })).then((fresh) => {
      refresh(fresh);
    });
  }, [refresh, state.id]);

  const run = useCallback(
    async (action: () => Promise<StudioAgent>, after?: (a: StudioAgent) => void) => {
      setNotice(null);
      try {
        const updated = await action();
        refresh(updated);
        after?.(updated);
      } catch (e) {
        setNotice(problemText(e));
      }
    },
    [refresh],
  );

  const startTest = async () => {
    setTestChat(null); // clear the panel at once: a new test starts empty
    try {
      const session = await studio.testChat(state.id);
      setTestChat(session.id);
    } catch (e) {
      setNotice(problemText(e));
    }
  };

  const chatWithIt = async () => {
    try {
      const session = await unwrap(api.POST("/sessions", { body: { agent: state.name } }));
      go({ page: "chat", sessionId: session.id });
    } catch (e) {
      setNotice(problemText(e));
    }
  };

  const issues = state.draft?.issues ?? [];
  const props = { doc, issues, dispatch, catalog, readOnly: !editable };
  const loose = unplaced(issues, (doc.helpers ?? []).map((h) => h.name));
  const name = doc.display_name ?? state.display_name;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-stone-200/70 bg-stone-50/80 px-5 py-3 backdrop-blur dark:border-stone-800/70 dark:bg-stone-950/80">
        <a href={href({ page: "agents" })} className="rounded-lg p-1.5 text-stone-500 hover:bg-stone-200/60 hover:text-stone-900 dark:hover:bg-stone-800" aria-label="Back to agents">
          <ArrowLeft aria-hidden className="size-4" />
        </a>
        <Avatar name={name} size="sm" />
        <h1 className="truncate font-display text-lg font-medium">{name}</h1>
        <StatusPill agent={state} />
        {editable && <SaveIndicator state={save} />}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <AgentPowerButton agent={state.name} label={name} />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setHistory(true);
            }}
          >
            <History aria-hidden className="size-4" /> History
          </Button>
          <a
            href={studio.exportUrl(state.id)}
            download
            className="inline-flex h-8 items-center gap-1.5 rounded-xl px-3 text-[13px] font-medium text-stone-600 hover:bg-stone-100 hover:text-stone-900 dark:text-stone-300 dark:hover:bg-stone-800"
          >
            <Download aria-hidden className="size-4" /> Export
          </a>
          {state.published && (
            <Button variant="secondary" size="sm" onClick={() => void chatWithIt()}>
              <MessageSquarePlus aria-hidden className="size-4" /> Chat with it
            </Button>
          )}
          {editable ? (
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                setPublishing(true);
              }}
            >
              <Send aria-hidden className="size-4" /> Publish
            </Button>
          ) : (
            <Button variant="primary" size="sm" onClick={() => void run(() => studio.edit(state.id), (a) => { show(documentOf(a)); })}>
              <Pencil aria-hidden className="size-4" /> Edit
            </Button>
          )}
        </div>
      </header>

      {notice && (
        <div role="alert" className="mx-5 mt-3 rounded-xl bg-rose-50 px-4 py-2 text-sm text-rose-800 ring-1 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900">
          {notice}
        </div>
      )}

      <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="scrollbar-thin min-h-0 overflow-y-auto px-5 py-6">
          <div className="mx-auto max-w-3xl space-y-5">
            <GuideStrip steps={["tool", "helper", "try"]} agentId={state.id} />
            {!editable && (
              <div className="flex items-center gap-3 rounded-2xl border border-stone-200 bg-white p-4 text-sm dark:border-stone-800 dark:bg-stone-900">
                <Check aria-hidden className="size-4 text-emerald-600" />
                Version {state.published?.number} is live. <span className="text-stone-500">Click Edit to change it; chats keep working while you edit.</span>
              </div>
            )}
            {loose.length > 0 && (
              <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
                {loose.map((i) => (
                  <div key={`${i.where}:${i.field ?? ""}:${i.message}`}>{i.message}</div>
                ))}
              </div>
            )}
            <BasicsSection {...props} />
            <InstructionsSection
              {...props}
              aside={
                editable && (
                  <ImproveInstructions
                    agentId={state.id}
                    current={doc.instructions}
                    disabled={save !== "saved"}
                    onAccept={(value) => {
                      dispatch({ kind: "set", field: "instructions", value });
                    }}
                  />
                )
              }
            />
            <ToolsSection {...props} />
            <SkillsSection {...props} />
            <HelpersSection {...props} />
            <LimitsSection {...props} />
            <ProtectionsSection {...props} />
            <ModelSection {...props} />
            <TestsSection agentId={state.id} tools={(doc.tools ?? []).map((t) => t.name)} editable={editable} />
            {editable && state.published && (
              <div className="flex justify-end">
                <Button variant="ghost" size="sm" onClick={() => void run(() => studio.discard(state.id), (a) => { show(documentOf(a)); })}>
                  <RotateCcw aria-hidden className="size-4" /> Discard changes
                </Button>
              </div>
            )}
          </div>
        </div>

        <aside className="flex min-h-[28rem] flex-col border-t border-stone-200 bg-stone-100/50 lg:border-t-0 lg:border-l dark:border-stone-800 dark:bg-stone-900/30" aria-label="Test chat" data-testid="test-chat">
          <div className="flex items-center gap-2 border-b border-stone-200 px-4 py-3 dark:border-stone-800">
            <span className="text-sm font-medium">Test chat</span>
            {state.draft?.tested ? <Pill tone="green">Tested</Pill> : <Pill>Not tested yet</Pill>}
            {testChat && (
              <Button variant="ghost" size="sm" className="ml-auto" onClick={() => void startTest()}>
                New test
              </Button>
            )}
          </div>
          {testChat ? (
            <div className="min-h-0 flex-1">
              <ChatView key={testChat} sessionId={testChat} compact agentName={name} onTurnEnd={recheck} />
            </div>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
              <p className="text-sm text-stone-600 dark:text-stone-400">
                Try your changes before anyone else sees them. Test chats have a small budget, and nothing that reaches people is really sent.
              </p>
              <Button variant="primary" onClick={() => void startTest()} disabled={issues.length > 0}>
                Start a test chat
              </Button>
              {issues.length > 0 && <p className="text-xs text-stone-500">Fix the highlighted fields first.</p>}
            </div>
          )}
        </aside>
      </div>

      <PublishDialog
        open={publishing}
        agent={state}
        onClose={() => {
          setPublishing(false);
        }}
        onPublish={(changelog) =>
          run(
            () => studio.publish(state.id, changelog),
            () => {
              setPublishing(false);
            },
          )
        }
      />
      <HistoryDialog
        open={history}
        agent={state}
        onClose={() => {
          setHistory(false);
        }}
        onRestore={(n) =>
          run(
            () => studio.restore(state.id, n),
            (a) => {
              show(documentOf(a));
              setHistory(false);
            },
          )
        }
      />
    </div>
  );
}

function StatusPill({ agent }: { agent: StudioAgent }) {
  if (agent.status === "draft") return <Pill tone="sun">Draft</Pill>;
  if (agent.status === "changes") return <Pill tone="amber">v{agent.published?.number} live · unpublished changes</Pill>;
  return <Pill tone="green">Published v{agent.published?.number}</Pill>;
}

function SaveIndicator({ state }: { state: SaveState }) {
  const content = {
    saved: (
      <>
        <Check aria-hidden className="size-3.5" /> Saved
      </>
    ),
    saving: (
      <>
        <Loader2 aria-hidden className="size-3.5 animate-spin motion-reduce:animate-none" /> Saving…
      </>
    ),
    pending: (
      <>
        <CircleDashed aria-hidden className="size-3.5" /> Editing…
      </>
    ),
    error: (
      <>
        <AlertTriangle aria-hidden className="size-3.5" /> Not saved: check your connection
      </>
    ),
  }[state];
  return (
    <span role="status" className={`inline-flex items-center gap-1 text-xs ${state === "error" ? "text-rose-600" : "text-stone-500"}`} data-testid="save-state">
      {content}
    </span>
  );
}

function PublishDialog({
  open,
  agent,
  onClose,
  onPublish,
}: {
  open: boolean;
  agent: StudioAgent;
  onClose: () => void;
  onPublish: (changelog: string | null) => Promise<void>;
}) {
  const [changelog, setChangelog] = useState("");
  const [busy, setBusy] = useState(false);
  const blockers = agent.draft?.blockers ?? ["There are no changes to publish"];
  const next = agent.draft?.number ?? 1;
  return (
    <Dialog open={open} onClose={onClose} title={`Publish version ${String(next)}`}>
      {blockers.length > 0 ? (
        <div>
          <p className="text-sm text-stone-600 dark:text-stone-400">Almost there:</p>
          <ul className="mt-2 space-y-1.5" data-testid="publish-blockers">
            {blockers.map((b) => (
              <li key={b} className="flex items-start gap-2 text-sm">
                <CircleDashed aria-hidden className="mt-0.5 size-4 text-amber-500" /> {b}
              </li>
            ))}
          </ul>
          <div className="mt-5 flex justify-end">
            <Button onClick={onClose}>OK</Button>
          </div>
        </div>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setBusy(true);
            void onPublish(changelog.trim() || null).finally(() => {
              setBusy(false);
              setChangelog("");
            });
          }}
        >
          <p className="mb-4 text-sm text-stone-600 dark:text-stone-400">
            New chats use it right away. Chats already running finish on the version they started with. You can always restore an earlier version.
          </p>
          <TextField
            label="What changed? (optional)"
            value={changelog}
            maxLength={500}
            placeholder="Added a flight-finder helper"
            onChange={(e) => {
              setChangelog(e.target.value);
            }}
          />
          <div className="mt-5 flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" type="submit" disabled={busy}>
              <Send aria-hidden className="size-4" /> Publish
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}

function HistoryDialog({
  open,
  agent,
  onClose,
  onRestore,
}: {
  open: boolean;
  agent: StudioAgent;
  onClose: () => void;
  onRestore: (n: number) => Promise<void>;
}) {
  return (
    <Dialog open={open} onClose={onClose} title="History">
      <ol className="max-h-96 space-y-2 overflow-y-auto" data-testid="history">
        {agent.versions.map((v) => (
          <li key={v.number} className="flex items-start gap-3 rounded-xl border border-stone-200 p-3 dark:border-stone-700">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-sm font-medium">
                Version {v.number}
                <Pill tone={v.state === "draft" ? "sun" : v.state === "published" ? "green" : "stone"}>{v.state}</Pill>
              </div>
              <div className="mt-0.5 text-xs text-stone-500">
                {v.changelog ?? (v.state === "draft" ? "Your changes, not published yet" : "No note")} ·{" "}
                {new Date(v.published_at ?? v.created_at).toLocaleString()}
              </div>
            </div>
            {v.state !== "draft" && (
              <div className="flex shrink-0 gap-1">
                <a href={studio.exportUrl(agent.id, v.number)} download className="rounded-lg p-1.5 text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800" aria-label={`Download version ${String(v.number)}`}>
                  <Download aria-hidden className="size-4" />
                </a>
                <Button variant="secondary" size="sm" onClick={() => void onRestore(v.number)}>
                  Restore
                </Button>
              </div>
            )}
          </li>
        ))}
      </ol>
      <div className="mt-5 flex justify-end">
        <Button onClick={onClose}>Close</Button>
      </div>
    </Dialog>
  );
}
