/**
 * The kill switch (phase L6): stop one agent, or every agent, now. What is running stops
 * at once (its model call, tool, code and helpers too); nothing new starts until it's
 * turned back on. Every agent: the sidebar's "Stop all agents" and a banner while off.
 * One agent: "Turn off" in the Studio and on the Agents page.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { OctagonX, Power } from "lucide-react";
import { useState } from "react";

import { api, type Schemas, unwrap } from "../api/client";
import { problemText } from "../chat/problems";
import { Dialog } from "../ui/form";
import { Button, Pill } from "../ui/primitives";

type State = Schemas["KillSwitchView"];

const killSwitch = {
  get: () => unwrap(api.GET("/kill-switch")),
  stop: (agent: string | null) => unwrap(api.POST("/kill-switch/stop", { body: { agent } })),
  resume: (agent: string | null) => unwrap(api.POST("/kill-switch/resume", { body: { agent } })),
};

const KEY = ["kill-switch"] as const;

/** What is switched off; checked every few seconds (another tab, or the API, may switch). */
export function useKillSwitch() {
  return useQuery({ queryKey: KEY, queryFn: killSwitch.get, refetchInterval: 5_000 });
}

/** Run a switch and show its new state everywhere at once. */
function useSwitch() {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (action: () => Promise<State>): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      client.setQueryData(KEY, await action());
      await client.invalidateQueries({ queryKey: ["sessions"] }); // stopped turns
      return true;
    } catch (e) {
      setError(problemText(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

function since(at: string | null | undefined): string {
  return at ? ` since ${new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "";
}

/** The sidebar's emergency stop: every agent, after one confirmation. */
export function StopAllButton() {
  const state = useKillSwitch();
  const { busy, error, run } = useSwitch();
  const [asking, setAsking] = useState(false);
  if (state.data?.all_off) return null; // the banner offers to turn them back on
  return (
    <>
      <button
        type="button"
        onClick={() => {
          setAsking(true);
        }}
        className="flex h-8 w-full items-center gap-2 rounded-lg px-2 text-xs font-medium text-rose-700 hover:bg-rose-50 dark:text-rose-400 dark:hover:bg-rose-950/40"
        data-testid="stop-all"
      >
        <OctagonX aria-hidden className="size-3.5" /> Stop all agents
      </button>
      <Dialog
        open={asking}
        onClose={() => {
          setAsking(false);
        }}
        title="Stop every agent now?"
      >
        <div className="space-y-3 text-sm">
          <p>Every reply in progress stops at once, with its helpers and any code it is running. Nothing new starts until you turn agents back on.</p>
          {error && (
            <p role="alert" className="text-rose-600">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button
              onClick={() => {
                setAsking(false);
              }}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => {
                void run(() => killSwitch.stop(null)).then((ok) => {
                  if (ok) setAsking(false);
                });
              }}
            >
              <OctagonX aria-hidden className="size-4" /> Stop all agents
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}

/** While every agent is stopped: said at the top of every page, with the way back. */
export function KillSwitchBanner() {
  const state = useKillSwitch();
  const { busy, error, run } = useSwitch();
  if (!state.data?.all_off) return null;
  return (
    <div role="status" className="flex flex-wrap items-center gap-3 border-b border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-900 dark:border-rose-900 dark:bg-rose-950/50 dark:text-rose-200" data-testid="kill-switch-banner">
      <OctagonX aria-hidden className="size-4 shrink-0" />
      <span className="min-w-0 flex-1">
        <strong>Every agent is stopped</strong>
        {since(state.data.since)}. Nothing new starts until you turn them back on.
      </span>
      {error && <span role="alert">{error}</span>}
      <Button
        size="sm"
        disabled={busy}
        onClick={() => {
          void run(() => killSwitch.resume(null));
        }}
      >
        <Power aria-hidden className="size-4" /> Turn agents back on
      </Button>
    </div>
  );
}

/** Is this agent switched off on its own? */
export function useAgentOff(agent: string): Schemas["SwitchView"] | null {
  const state = useKillSwitch();
  return state.data?.agents.find((s) => s.agent === agent) ?? null;
}

/** "Switched off" for an agent's card. */
export function OffPill({ agent }: { agent: string }) {
  return useAgentOff(agent) ? <Pill tone="rose">Switched off</Pill> : null;
}

/** Turn one agent off (after a confirmation) or back on. */
export function AgentPowerButton({ agent, label, className = "" }: { agent: string; label: string; className?: string }) {
  const off = useAgentOff(agent);
  const { busy, error, run } = useSwitch();
  const [asking, setAsking] = useState(false);
  if (off) {
    return (
      <span className={`inline-flex items-center gap-2 ${className}`}>
        <Pill tone="rose">Switched off{since(off.since)}</Pill>
        <Button
          size="sm"
          disabled={busy}
          onClick={() => {
            void run(() => killSwitch.resume(agent));
          }}
        >
          <Power aria-hidden className="size-4" /> Turn on
        </Button>
        {error && (
          <span role="alert" className="text-xs text-rose-600">
            {error}
          </span>
        )}
      </span>
    );
  }
  return (
    <>
      <Button
        size="sm"
        variant="ghost"
        className={className}
        onClick={() => {
          setAsking(true);
        }}
      >
        <Power aria-hidden className="size-4" /> Turn off
      </Button>
      <Dialog
        open={asking}
        onClose={() => {
          setAsking(false);
        }}
        title={`Turn off ${label}?`}
      >
        <div className="space-y-3 text-sm">
          <p>Its replies stop now, in every chat and test chat, with its helpers and any code it is running. New messages to it are refused until you turn it back on.</p>
          {error && (
            <p role="alert" className="text-rose-600">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button
              onClick={() => {
                setAsking(false);
              }}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => {
                void run(() => killSwitch.stop(agent)).then((ok) => {
                  if (ok) setAsking(false);
                });
              }}
            >
              <Power aria-hidden className="size-4" /> Turn off now
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}
