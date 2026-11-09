/**
 * Settings → Models (phase L3b): the models your agents can use, and the default.
 * Add one per kind (Ollama, OpenAI, Azure AI Foundry, any OpenAI-compatible service),
 * test it (it must answer and use tools), set the default. A key goes in once: it is
 * saved encrypted on this computer and never shown again (only "a key is saved").
 */
import { CheckCircle2, Cloud, Cpu, KeyRound, Loader2, Pencil, Plus, Server, Trash2, XCircle, Zap } from "lucide-react";
import { useState } from "react";

import { problemText } from "../chat/problems";
import { GuideStrip } from "../guide/GuideStrip";
import { useAbout } from "../sessions/ModelStatus";
import { Dialog, Section, TextField } from "../ui/form";
import { Button, Pill, Spinner } from "../ui/primitives";
import { type Connection, KINDS, type Kind, models, type Price, useConnections, useDefaultModel, useModelsRefresh } from "./api";

const KIND_ICON: Record<Kind, typeof Cpu> = { ollama: Cpu, openai: Cloud, azure_foundry: Cloud, compatible: Server };

export function ModelsPage() {
  const connections = useConnections();
  const about = useAbout();
  const fromSetup = about.data && !about.data.demo_model ? about.data : null; // a real model, set up already
  const [adding, setAdding] = useState(false);
  const list = connections.data ?? [];
  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <div className="flex flex-wrap items-end gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-4xl font-medium tracking-tight">Models</h1>
          <p className="mt-2 max-w-2xl text-stone-500 dark:text-stone-400">
            The AI models your agents can use. Keys stay on this computer, encrypted, and are never shown again.
          </p>
        </div>
        <Button
          variant="primary"
          onClick={() => {
            setAdding(true);
          }}
        >
          <Plus aria-hidden className="size-4" /> Add a model
        </Button>
      </div>
      <div className="mt-8 space-y-5">
        <GuideStrip steps={["model"]} />
        <DefaultModel connections={list} />
        {connections.isPending && <Spinner label="Loading models…" />}
        {list.length === 0 && connections.isSuccess && (
          <div className="rounded-2xl border border-dashed border-stone-300 p-8 text-center dark:border-stone-700">
            {fromSetup ? (
              <>
                <p className="font-display text-xl">Your agents use {setupModel(fromSetup.model_provider, fromSetup.chat_model)}</p>
                <p className="mt-1 text-sm text-stone-500">Chosen in setup. Add another to try it or to give an agent its own: Ollama, or a hosted one with your key.</p>
              </>
            ) : (
              <>
                <p className="font-display text-xl">Connect your first model</p>
                <p className="mt-1 text-sm text-stone-500">A free local one with Ollama, or a hosted one with your key.</p>
              </>
            )}
          </div>
        )}
        {list.map((c) => (
          <ConnectionCard key={c.id} connection={c} />
        ))}
      </div>
      <AddDialog
        open={adding}
        onClose={() => {
          setAdding(false);
        }}
      />
    </div>
  );
}

function DefaultModel({ connections }: { connections: readonly Connection[] }) {
  const current = useDefaultModel();
  const about = useAbout();
  const refresh = useModelsRefresh();
  const [error, setError] = useState<string | null>(null);
  const ready = connections.filter((c) => c.test_status === "ready");
  const value = current.data?.connection ? `${current.data.connection.id}|${current.data.model ?? ""}` : "";
  return (
    <Section title="Default model" description="Used by every agent and helper that doesn't pick its own." icon={<Zap aria-hidden className="size-4" />} testId="default-model">
      <label className="block text-sm">
        <span className="sr-only">Default model</span>
        <select
          value={value}
          onChange={(e) => {
            const [id = "", model = ""] = e.target.value.split("|");
            setError(null);
            models
              .setDefault(id === "" ? null : id, model === "" ? null : model) // "": back to the setup's model
              .then(refresh)
              .catch((err: unknown) => {
                setError(problemText(err));
              });
          }}
          className="h-10 w-full rounded-xl border border-stone-200 bg-white px-3 dark:border-stone-700 dark:bg-stone-950"
          aria-label="Default model"
        >
          <option value="">The model chosen in setup ({setupModel(current.data?.setup_provider, about.data?.chat_model)})</option>
          {ready.flatMap((c) =>
            c.models.map((m) => (
              <option key={`${c.id}|${m}`} value={`${c.id}|${m}`}>
                {c.display_name} · {m}
              </option>
            )),
          )}
        </select>
      </label>
      {ready.length === 0 && <p className="mt-2 text-xs text-stone-500">Models appear here once they pass their test.</p>}
      {error && <p role="alert" className="mt-2 text-sm text-rose-600">{error}</p>}
    </Section>
  );
}

function StatusPill({ c }: { c: Connection }) {
  if (c.test_status === "ready") return <Pill tone="green">Ready</Pill>;
  if (c.test_status === "failed") return <Pill tone="rose">Not working</Pill>;
  return <Pill tone="amber">Not tested</Pill>;
}

function ConnectionCard({ connection: c }: { connection: Connection }) {
  const refresh = useModelsRefresh();
  const [model, setModel] = useState(c.tested_model ?? c.models[0] ?? "");
  const [testing, setTesting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const Icon = KIND_ICON[c.kind];
  const test = async () => {
    setTesting(true);
    try {
      await models.test(c.id, model);
    } finally {
      setTesting(false);
      refresh();
    }
  };
  return (
    <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-soft dark:border-stone-800 dark:bg-stone-900" data-testid="connection-card">
      <div className="flex flex-wrap items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-stone-100 text-stone-700 dark:bg-stone-800 dark:text-stone-300">
          <Icon aria-hidden className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-display text-lg font-medium">{c.display_name}</span>
            <StatusPill c={c} />
            <span className="text-xs text-stone-500">{KINDS[c.kind].label}</span>
          </div>
          <div className="mt-0.5 truncate font-mono text-xs text-stone-500" title="In agent files: model: <id>:<model>">
            {c.name} · {c.base_url}
          </div>
          <div className="mt-1 flex items-center gap-1.5 text-xs text-stone-500">
            {c.has_key ? (
              <>
                <KeyRound aria-hidden className="size-3.5" /> A key is saved · fingerprint <code className="font-mono">{c.key_fingerprint}</code>
              </>
            ) : (
              "No key"
            )}
          </div>
        </div>
        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setEditing(true);
            }}
            aria-label={`Edit ${c.display_name}`}
          >
            <Pencil aria-hidden className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setConfirm(true);
            }}
            aria-label={`Remove ${c.display_name}`}
          >
            <Trash2 aria-hidden className="size-4" />
          </Button>
        </div>
      </div>
      {c.test_detail && (
        <div
          className={`mt-3 flex items-start gap-2 rounded-xl px-3 py-2 text-sm ${c.test_status === "ready" ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200" : "bg-rose-50 text-rose-800 dark:bg-rose-950/40 dark:text-rose-200"}`}
          data-testid="test-result"
        >
          {c.test_status === "ready" ? <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0" /> : <XCircle aria-hidden className="mt-0.5 size-4 shrink-0" />}
          <span>
            {c.test_detail}
            {c.tested_model ? ` (${c.tested_model})` : ""}
          </span>
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-end gap-2">
        <label className="min-w-48 flex-1 text-sm">
          <span className="mb-1 block font-medium">{KINDS[c.kind].modelLabel}</span>
          <input
            value={model}
            list={`models-${c.id}`}
            onChange={(e) => {
              setModel(e.target.value);
            }}
            className="h-9 w-full rounded-xl border border-stone-200 bg-white px-3 dark:border-stone-700 dark:bg-stone-950"
          />
          <datalist id={`models-${c.id}`}>
            {c.models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </label>
        <Button variant="secondary" size="sm" disabled={!model.trim() || testing} onClick={() => void test()}>
          {testing ? <Loader2 aria-hidden className="size-4 animate-spin" /> : <Zap aria-hidden className="size-4" />} Test
        </Button>
      </div>
      <Prices connection={c} />
      <EditDialog
        open={editing}
        connection={c}
        onClose={() => {
          setEditing(false);
        }}
      />
      <Dialog
        open={confirm}
        onClose={() => {
          setConfirm(false);
        }}
        title={`Remove ${c.display_name}?`}
      >
        <p className="text-sm text-stone-600 dark:text-stone-400">
          Its saved key is deleted with it. Agents that use it will need another model before their next message.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button
            onClick={() => {
              setConfirm(false);
            }}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              void models.remove(c.id).then(() => {
                setConfirm(false);
                refresh();
              });
            }}
          >
            Remove
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

const PRICE_SOURCE: Record<Price["source"], string> = {
  connection: "set here",
  settings: "from MODEL_PRICES in .env",
  "built-in": "Nuria's price list",
  local: "free: runs on your machine or network",
  estimate: "unknown: a deliberately high estimate",
};

/**
 * What a call to each model costs (phase H2): budgets in dollars use it. A price set
 * here wins; without one, Nuria's price list, free for a local model, or a high
 * estimate so a budget still stops a runaway agent.
 */
function Prices({ connection: c }: { connection: Connection }) {
  const entries = Object.entries(c.prices);
  if (entries.length === 0) return null;
  return (
    <div className="mt-4" data-testid="model-prices">
      <div className="mb-1 text-sm font-medium">Prices, per 1 million tokens</div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-stone-500">
            <th className="py-1 pr-3 font-medium">Model</th>
            <th className="py-1 pr-3 font-medium">Input</th>
            <th className="py-1 pr-3 font-medium">Output</th>
            <th className="py-1 pr-3 font-medium">From</th>
            <th className="py-1" />
          </tr>
        </thead>
        <tbody>
          {entries.map(([model, price]) => (
            <PriceRow key={model} connection={c} model={model} price={price} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PriceRow({ connection: c, model, price }: { connection: Connection; model: string; price: Price }) {
  const refresh = useModelsRefresh();
  const [editing, setEditing] = useState(false);
  const [input, setInput] = useState(String(price.input_per_mtok));
  const [output, setOutput] = useState(String(price.output_per_mtok));
  const [error, setError] = useState<string | null>(null);
  const save = async (value: { input_per_mtok: number; output_per_mtok: number } | null) => {
    setError(null);
    try {
      await models.edit(c.id, { prices: { [model]: value } });
      setEditing(false);
      refresh();
    } catch (e) {
      setError(problemText(e));
    }
  };
  const valid = [input, output].every((v) => v.trim() !== "" && Number.isFinite(Number(v)) && Number(v) >= 0);
  const cell = "h-8 w-24 rounded-lg border border-stone-200 bg-white px-2 dark:border-stone-700 dark:bg-stone-950";
  return (
    <tr className="border-t border-stone-100 tabular-nums dark:border-stone-800">
      <td className="py-1.5 pr-3 font-mono text-[13px]">{model}</td>
      {editing ? (
        <>
          <td className="py-1.5 pr-3">
            <input aria-label={`Input price of ${model}`} inputMode="decimal" value={input} onChange={(e) => { setInput(e.target.value); }} className={cell} />
          </td>
          <td className="py-1.5 pr-3">
            <input aria-label={`Output price of ${model}`} inputMode="decimal" value={output} onChange={(e) => { setOutput(e.target.value); }} className={cell} />
          </td>
          <td className="py-1.5 pr-3 text-xs text-rose-700 dark:text-rose-300">{error}</td>
          <td className="py-1.5 text-right whitespace-nowrap">
            <Button size="sm" variant="primary" disabled={!valid} onClick={() => void save({ input_per_mtok: Number(input), output_per_mtok: Number(output) })}>
              Save
            </Button>{" "}
            <Button size="sm" onClick={() => { setEditing(false); }}>
              Cancel
            </Button>
          </td>
        </>
      ) : (
        <>
          <td className="py-1.5 pr-3">${price.input_per_mtok}</td>
          <td className="py-1.5 pr-3">${price.output_per_mtok}</td>
          <td className={`py-1.5 pr-3 text-xs ${price.source === "estimate" ? "text-amber-700 dark:text-amber-400" : "text-stone-500"}`}>
            {PRICE_SOURCE[price.source]}
          </td>
          <td className="py-1.5 text-right whitespace-nowrap">
            <Button size="sm" variant="ghost" onClick={() => { setEditing(true); }} aria-label={`Set the price of ${model}`}>
              Set price
            </Button>
            {price.source === "connection" && (
              <Button size="sm" variant="ghost" onClick={() => void save(null)} aria-label={`Use the default price of ${model}`}>
                Reset
              </Button>
            )}
          </td>
        </>
      )}
    </tr>
  );
}

/** What to open the add dialog on: a kind, and what was already found (Ollama). */
export interface AddStart {
  kind: Kind;
  url?: string;
  models?: string[];
}

/** Add a model connection, then test it. `start` opens on one kind (mount the dialog
 * when it opens, so it starts fresh); `onReady` hears of a connection that passed its
 * test (Getting started makes it the default). */
export function AddDialog({
  open,
  onClose,
  start,
  onReady,
}: {
  open: boolean;
  onClose: () => void;
  start?: AddStart | undefined;
  onReady?: ((connectionId: string, model: string) => void) | undefined;
}) {
  const refresh = useModelsRefresh();
  const [kind, setKind] = useState<Kind | null>(start?.kind ?? null);
  const [name, setName] = useState(start ? KINDS[start.kind].label : "");
  const [url, setUrl] = useState(start?.url ?? "");
  const [key, setKey] = useState("");
  const [model, setModel] = useState(start?.models?.[0] ?? "");
  const [suggested, setSuggested] = useState<string[]>(start?.models ?? []);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const choose = async (k: Kind) => {
    setKind(k);
    setName(KINDS[k].label);
    setUrl(k === "ollama" || k === "openai" ? KINDS[k].url : ""); // others: an example, not a value
    setResult(null);
    setSuggested([]);
    if (k === "ollama") {
      try {
        const found = await models.ollama();
        const first = found[0];
        if (first) {
          setUrl(first.base_url);
          setSuggested(first.models);
          setModel(first.models[0] ?? "");
        }
      } catch {
        // not found: the person types the address
      }
    }
  };
  const reset = () => {
    setKind(null);
    setKey("");
    setModel("");
    setResult(null);
    onClose();
  };
  const save = async () => {
    if (!kind) return;
    setBusy(true);
    setResult(null);
    try {
      const added = await models.add({ display_name: name.trim(), kind, base_url: url.trim(), api_key: key || null, models: model ? [model] : [] });
      setKey(""); // the key is saved; never kept in the page
      const tested = model ? await models.test(added.id, model.trim()) : null;
      refresh();
      if (tested?.ok) onReady?.(added.id, model.trim());
      if (!tested || tested.ok) {
        reset();
        return;
      }
      setResult({ ok: false, text: `Saved, but: ${tested.detail}. Fix it with Edit, then Test.` });
    } catch (e) {
      setResult({ ok: false, text: problemText(e) });
    } finally {
      setBusy(false);
    }
  };
  const k = kind ? KINDS[kind] : null;
  return (
    <Dialog open={open} onClose={reset} title={k ? `Add ${k.label}` : "Add a model"}>
      {!kind || !k ? (
        <div className="grid gap-2.5 sm:grid-cols-2">
          {(Object.keys(KINDS) as Kind[]).map((kk) => {
            const Icon = KIND_ICON[kk];
            return (
              <button
                key={kk}
                type="button"
                onClick={() => void choose(kk)}
                className="flex items-start gap-3 rounded-xl border border-stone-200 p-3.5 text-left transition hover:border-stone-300 hover:bg-stone-50 focus-visible:outline-2 focus-visible:outline-sun-500 dark:border-stone-700 dark:hover:bg-stone-800"
              >
                <Icon aria-hidden className="mt-0.5 size-5 text-stone-600 dark:text-stone-300" />
                <span>
                  <span className="block text-sm font-medium">{KINDS[kk].label}</span>
                  <span className="block text-xs text-stone-500">{KINDS[kk].blurb}</span>
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <p className="text-sm text-stone-600 dark:text-stone-400">{k.help}</p>
          <TextField
            label="Name"
            value={name}
            maxLength={60}
            required
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
          <TextField
            label={kind === "azure_foundry" ? "Endpoint" : "Address"}
            value={url}
            placeholder={k.url}
            required
            onChange={(e) => {
              setUrl(e.target.value);
            }}
          />
          {k.keyLabel && (
            <TextField
              label={k.keyLabel}
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={key}
              required={kind === "openai" || kind === "azure_foundry"}
              onChange={(e) => {
                setKey(e.target.value);
              }}
              hint="Saved encrypted on this computer. You won't see it again."
            />
          )}
          <div>
            <TextField
              label={k.modelLabel}
              value={model}
              required
              list="suggested-models"
              placeholder={kind === "openai" ? "gpt-4o-mini" : kind === "ollama" ? "qwen2.5:7b" : ""}
              onChange={(e) => {
                setModel(e.target.value);
              }}
            />
            <datalist id="suggested-models">
              {suggested.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
            {suggested.length > 0 && <p className="mt-1 text-xs text-stone-500">Found on this computer: {suggested.join(", ")}</p>}
          </div>
          {result && (
            <div role="alert" className={`rounded-xl px-3 py-2 text-sm ${result.ok ? "bg-emerald-50 text-emerald-800" : "bg-rose-50 text-rose-800 dark:bg-rose-950/40 dark:text-rose-200"}`}>
              {result.text}
            </div>
          )}
          <div className="flex justify-between gap-2">
            <Button
              variant="ghost"
              onClick={() => {
                setKind(null);
              }}
            >
              Back
            </Button>
            <div className="flex gap-2">
              <Button onClick={reset}>{result ? "Close" : "Cancel"}</Button>
              <Button variant="primary" type="submit" disabled={busy || !name.trim() || !url.trim() || !model.trim()}>
                {busy ? <Loader2 aria-hidden className="size-4 animate-spin" /> : null} Save and test
              </Button>
            </div>
          </div>
        </form>
      )}
    </Dialog>
  );
}

function EditDialog({ open, connection: c, onClose }: { open: boolean; connection: Connection; onClose: () => void }) {
  const refresh = useModelsRefresh();
  const [name, setName] = useState(c.display_name);
  const [url, setUrl] = useState(c.base_url);
  const [key, setKey] = useState("");
  const [modelsText, setModelsText] = useState(c.models.join(", "));
  const [error, setError] = useState<string | null>(null);
  const k = KINDS[c.kind];
  return (
    <Dialog open={open} onClose={onClose} title={`Edit ${c.display_name}`}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          models
            .edit(c.id, {
              display_name: name.trim(),
              base_url: url.trim(),
              api_key: key || null,
              models: modelsText.split(",").map((m) => m.trim()).filter(Boolean),
            })
            .then(() => {
              setKey("");
              refresh();
              onClose();
            })
            .catch((err: unknown) => {
              setError(problemText(err));
            });
        }}
      >
        <TextField
          label="Name"
          value={name}
          maxLength={60}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
        <TextField
          label="Address"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
          }}
        />
        {k.keyLabel && (
          <TextField
            label={`New ${k.keyLabel.toLowerCase()}`}
            type="password"
            autoComplete="off"
            value={key}
            placeholder={c.has_key ? "Leave empty to keep the saved key" : ""}
            onChange={(e) => {
              setKey(e.target.value);
            }}
            hint="A new key replaces the saved one; the old one is deleted."
          />
        )}
        <TextField
          label="Models (comma-separated)"
          value={modelsText}
          onChange={(e) => {
            setModelsText(e.target.value);
          }}
        />
        {error && <p role="alert" className="text-sm text-rose-600">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit">
            Save
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/** "Ollama · qwen2.5:7b": the setup's provider, and its model when there is one. */
function setupModel(provider: string | undefined, model: string | null | undefined): string {
  const label = setupLabel(provider);
  return model && provider !== "scripted" ? `${label} · ${model}` : label;
}

function setupLabel(provider: string | undefined): string {
  if (provider === "scripted") return "the offline demo model";
  if (provider === "ollama") return "Ollama";
  if (provider === "openai") return "OpenAI";
  return provider ?? "…";
}
