/**
 * Settings → Tools (phase L6a): what the agents' tools use.
 * Web search: SearXNG in the stack by default (private, no key), or Tavily / Brave with
 * a key (saved encrypted, never shown again). Sites: optionally, the only sites agents
 * may read pages from. A test search shows it works.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Globe, KeyRound, ListChecks, SquareTerminal, XCircle } from "lucide-react";
import { useState } from "react";

import { api, type Schemas, unwrap } from "../api/client";
import { problemText } from "../chat/problems";
import { Section, Segmented, TextArea, TextField } from "../ui/form";
import { Button, Spinner } from "../ui/primitives";
import { McpServers } from "./McpServers";

type Settings = Schemas["ToolSettingsView"];
type Provider = Settings["search_provider"];

const PROVIDERS: readonly { value: Provider; label: string; hint: string }[] = [
  { value: "searxng", label: "Built in", hint: "SearXNG, no key" },
  { value: "tavily", label: "Tavily", hint: "Your API key" },
  { value: "brave", label: "Brave", hint: "Your API key" },
];

const KEY_HELP: Record<Provider, string> = {
  searxng: "",
  tavily: "Create a key at app.tavily.com (a free monthly allowance).",
  brave: "Create a key at api-dashboard.search.brave.com (billed per search, with monthly credits).",
};

const tools = {
  get: () => unwrap(api.GET("/tools/settings")),
  put: (body: Schemas["ToolSettingsUpdate"]) => unwrap(api.PUT("/tools/settings", { body })),
  test: (query: string) => unwrap(api.POST("/tools/search/test", { body: { query } })),
};

export function ToolsPage() {
  const settings = useQuery({ queryKey: ["tools", "settings"], queryFn: tools.get });
  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="font-display text-4xl font-medium tracking-tight">Tools</h1>
      <p className="mt-2 max-w-2xl text-stone-500 dark:text-stone-400">
        What your agents' tools use. Choose the tools themselves for each agent in the Studio.
      </p>
      <div className="mt-8 space-y-5">
        {settings.data ? (
          <>
            <SearchSettings current={settings.data} />
            <SitesSettings current={settings.data} />
            <McpServers />
            <Section
              title="Run Python and the terminal"
              description="Code runs in a locked box for each conversation turn: no internet, no access to your files or keys, limited time and memory."
              icon={<SquareTerminal aria-hidden className="size-4" />}
              testId="sandbox-settings"
            >
              <p className="text-sm">
                {settings.data.sandbox ? (
                  <>
                    <CheckCircle2 aria-hidden className="mr-1 inline size-4 text-emerald-600" />
                    On. Agents with Run Python, Use a terminal or Work with files can use them.
                  </>
                ) : (
                  <>Off on this installation. Turn it on with <code>./setup.sh --sandbox</code>.</>
                )}
              </p>
            </Section>
          </>
        ) : (
          <Spinner label="Loading…" />
        )}
      </div>
    </div>
  );
}

function useSaved() {
  const client = useQueryClient();
  return (saved: Settings) => {
    client.setQueryData(["tools", "settings"], saved);
  };
}

function SearchSettings({ current }: { current: Settings }) {
  const saved = useSaved();
  const [provider, setProvider] = useState<Provider>(current.search_provider);
  const [key, setKey] = useState("");
  const [url, setUrl] = useState(current.searxng_url ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Schemas["SearchTestView"] | null>(null);
  const keyed = provider !== "searxng";
  const keySaved = current.has_key && current.search_provider === provider;

  const save = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const body: Schemas["ToolSettingsUpdate"] = { search_provider: provider };
      if (key.trim()) body.api_key = key.trim();
      if (!keyed) body.searxng_url = url.trim();
      saved(await tools.put(body));
      setKey(""); // saved encrypted; never kept in the page
      setResult(await tools.test("weather today"));
    } catch (e) {
      setError(problemText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Web search" description="Used by the Search the web tool." icon={<Globe aria-hidden className="size-4" />} testId="search-settings">
      <div className="space-y-4">
        <Segmented label="Search with" value={provider} options={PROVIDERS} onChange={(p) => { setProvider(p); setResult(null); }} />
        {!keyed && (
          <details className="text-sm">
            <summary className="cursor-pointer text-stone-600 dark:text-stone-400">Use your own SearXNG instead (optional)</summary>
            <div className="mt-2">
              <TextField
                label="SearXNG address"
                value={url}
                placeholder="Leave empty: the one in Nuria"
                hint="Its JSON output must be on."
                onChange={(e) => { setUrl(e.target.value); }}
              />
            </div>
          </details>
        )}
        {!keyed && <p className="text-sm text-stone-600 dark:text-stone-400">Built in: a private search engine running with Nuria. Nothing to sign up for.</p>}
        {keyed && (
          <TextField
            label="API key"
            type="password"
            autoComplete="off"
            value={key}
            placeholder={keySaved ? "A key is saved: type a new one to replace it" : ""}
            hint={
              <>
                {KEY_HELP[provider]} It's saved encrypted on this computer and never shown again.
                {keySaved && current.key_fingerprint && (
                  <span className="ml-1 inline-flex items-center gap-1">
                    <KeyRound aria-hidden className="size-3" /> fingerprint {current.key_fingerprint}
                  </span>
                )}
              </>
            }
            onChange={(e) => { setKey(e.target.value); }}
          />
        )}
        {error && <p role="alert" className="text-sm text-rose-600">{error}</p>}
        {result && (
          <div className={`rounded-xl p-3 text-sm ring-1 ${result.ok ? "bg-emerald-50 ring-emerald-200 dark:bg-emerald-950/30 dark:ring-emerald-900" : "bg-rose-50 ring-rose-200 dark:bg-rose-950/30 dark:ring-rose-900"}`} data-testid="search-test">
            <p className="flex items-center gap-1.5 font-medium">
              {result.ok ? <CheckCircle2 aria-hidden className="size-4 text-emerald-600" /> : <XCircle aria-hidden className="size-4 text-rose-600" />}
              {result.detail}
            </p>
            {result.results.length > 0 && (
              <ul className="mt-2 space-y-1">
                {result.results.map((r) => (
                  <li key={r.url} className="truncate">
                    <span className="font-medium">{r.title}</span> <span className="text-stone-500">{r.url}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="flex gap-2">
          <Button variant="primary" disabled={busy || (keyed && !key.trim() && !keySaved)} onClick={() => void save()}>
            {busy ? "Saving…" : "Save and test"}
          </Button>
          {!busy && (
            <Button
              onClick={() => {
                setError(null);
                tools.test("weather today").then(setResult).catch((e: unknown) => { setError(problemText(e)); });
              }}
            >
              Test search
            </Button>
          )}
        </div>
      </div>
    </Section>
  );
}

function SitesSettings({ current }: { current: Settings }) {
  const saved = useSaved();
  const [text, setText] = useState(current.web_allowlist.join("\n"));
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  return (
    <Section
      title="Sites agents may read"
      description="Empty: any public site. Agents never reach your computer, your network or Nuria's own services, whatever you set here."
      icon={<ListChecks aria-hidden className="size-4" />}
      testId="sites-settings"
    >
      <TextArea
        label="Only these sites (one per line, e.g. wikipedia.org)"
        rows={4}
        value={text}
        onChange={(e) => { setText(e.target.value); setDone(false); }}
      />
      {error && <p role="alert" className="mt-2 text-sm text-rose-600">{error}</p>}
      <div className="mt-3 flex items-center gap-3">
        <Button
          variant="primary"
          onClick={() => {
            setError(null);
            tools
              .put({ web_allowlist: text.split(/\s+/).filter(Boolean) })
              .then((s) => { saved(s); setDone(true); })
              .catch((e: unknown) => { setError(problemText(e)); });
          }}
        >
          Save
        </Button>
        {done && <span role="status" className="text-sm text-emerald-700 dark:text-emerald-400">Saved</span>}
      </div>
    </Section>
  );
}
