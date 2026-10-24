/**
 * Settings → Tools → MCP servers (phase L8): tools from other services, for any agent.
 *
 * Add a server by its address (and a token if it needs one: saved encrypted, never shown
 * again). Its tools are listed and checked; switch on the ones agents may use. A tool
 * asks you before each call unless the server marks it read-only and you choose "runs
 * without asking". If the server changes a tool later, agents can't use it until you look
 * at the change.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Plug, RefreshCw, Trash2, XCircle } from "lucide-react";
import { useState } from "react";

import { api, type Schemas, unwrap } from "../api/client";
import { problemText } from "../chat/problems";
import { Dialog, Section, Switch, TextField } from "../ui/form";
import { Button, Pill, Spinner } from "../ui/primitives";

type Server = Schemas["McpServerView"];
type Tool = Schemas["McpToolView"];

const KEY = ["mcp", "servers"] as const;
const path = (id: string) => ({ params: { path: { server_id: id } } });

export function McpServers() {
  const servers = useQuery({ queryKey: KEY, queryFn: () => unwrap(api.GET("/mcp/servers")) });
  return (
    <Section
      title="MCP servers"
      description="Tools from other services, through the Model Context Protocol. Add a server, then switch on the tools your agents may use; give them to an agent in the Studio."
      icon={<Plug aria-hidden className="size-4" />}
      testId="mcp-servers"
    >
      {servers.data ? (
        <div className="space-y-4">
          {servers.data.map((s) => (
            <ServerCard key={s.id} server={s} />
          ))}
          <AddServer first={servers.data.length === 0} />
        </div>
      ) : (
        <Spinner label="Loading…" />
      )}
    </Section>
  );
}

function useSaved() {
  const client = useQueryClient();
  return (saved?: Server) => {
    if (saved) client.setQueryData<Server[]>(KEY, (all = []) => {
      const others = all.filter((s) => s.id !== saved.id);
      return all.some((s) => s.id === saved.id) ? all.map((s) => (s.id === saved.id ? saved : s)) : [...others, saved];
    });
    void client.invalidateQueries({ queryKey: KEY });
    void client.invalidateQueries({ queryKey: ["studio"] }); // the catalogue lists switched-on tools
  };
}

function AddServer({ first }: { first: boolean }) {
  const saved = useSaved();
  const [open, setOpen] = useState(first);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [header, setHeader] = useState("Authorization");
  const add = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/mcp/servers", { body: { display_name: name.trim(), url: url.trim(), token: token.trim() || null, header_name: header.trim() || "Authorization" } })),
    onSuccess: (server) => {
      saved(server);
      setName("");
      setUrl("");
      setToken("");
      setOpen(false);
    },
  });
  if (!open)
    return (
      <Button onClick={() => { setOpen(true); }} data-testid="mcp-add-open">
        <Plug aria-hidden className="size-4" /> Add a server
      </Button>
    );
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        add.mutate();
      }} className="space-y-3 rounded-xl border border-dashed border-stone-300 p-4 dark:border-stone-700" data-testid="mcp-add">
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField label="Name" value={name} onChange={(e) => { setName(e.target.value); }} placeholder="Docs search" required maxLength={60} />
        <TextField label="Address" value={url} onChange={(e) => { setUrl(e.target.value); }} placeholder="https://example.com/mcp" required hint="Its Streamable HTTP endpoint (often ends in /mcp)." />
      </div>
      <TextField
        label="Token (optional)"
        type="password"
        autoComplete="off"
        value={token}
        onChange={(e) => { setToken(e.target.value); }}
        hint="If the server needs one. Saved encrypted on this computer, never shown again."
      />
      <details className="text-sm">
        <summary className="cursor-pointer text-stone-500">Advanced</summary>
        <div className="mt-2 max-w-xs">
          <TextField label="Send the token in this header" value={header} onChange={(e) => { setHeader(e.target.value); }} hint="Authorization (as a Bearer token) unless the server says otherwise." />
        </div>
      </details>
      {add.error && <p className="text-sm text-rose-600">{problemText(add.error)}</p>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={add.isPending || !name.trim() || !url.trim()}>
          {add.isPending ? "Adding and testing…" : "Add and test"}
        </Button>
        {!first && <Button variant="ghost" onClick={() => { setOpen(false); }}>Cancel</Button>}
      </div>
    </form>
  );
}

function ServerCard({ server }: { server: Server }) {
  const saved = useSaved();
  const [removing, setRemoving] = useState(false);
  const test = useMutation({ mutationFn: () => unwrap(api.POST("/mcp/servers/{server_id}/test", path(server.id))), onSuccess: saved });
  const remove = useMutation({
    mutationFn: () => api.DELETE("/mcp/servers/{server_id}", path(server.id)),
    onSuccess: () => {
      setRemoving(false);
      saved();
    },
  });
  const changed = server.tools.filter((t) => t.changed && t.enabled).length;
  return (
    <div className="rounded-xl border border-stone-200 p-4 dark:border-stone-800" data-testid="mcp-server" data-name={server.name}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-medium">{server.display_name}</h3>
            {server.status === "ready" ? (
              <Pill tone="green"><CheckCircle2 aria-hidden className="size-3" /> Ready</Pill>
            ) : server.status === "failed" ? (
              <Pill tone="rose"><XCircle aria-hidden className="size-3" /> Not working</Pill>
            ) : (
              <Pill>Not tested</Pill>
            )}
            {changed > 0 && <Pill tone="amber"><AlertTriangle aria-hidden className="size-3" /> {changed} changed: look again</Pill>}
          </div>
          <p className="mt-0.5 break-all font-mono text-xs text-stone-500">{server.url}</p>
          <p className="text-xs text-stone-500">
            {server.has_token ? `Token set (${server.token_fingerprint ?? "…"})` : "No token"}
            {server.status_detail && <> · <span data-testid="mcp-status">{server.status_detail}</span></>}
          </p>
        </div>
        <div className="flex gap-1.5">
          <Button size="sm" onClick={() => { test.mutate(); }} disabled={test.isPending} data-testid="mcp-test">
            <RefreshCw aria-hidden className={`size-3.5 ${test.isPending ? "animate-spin" : ""}`} /> Test
          </Button>
          <Button size="sm" variant="ghost" onClick={() => { setRemoving(true); }} aria-label={`Remove ${server.display_name}`}>
            <Trash2 aria-hidden className="size-3.5" />
          </Button>
        </div>
      </div>
      {server.tools.length > 0 && (
        <ul className="mt-3 divide-y divide-stone-100 dark:divide-stone-800">
          {server.tools.map((t) => (
            <ToolRow key={t.name} server={server} tool={t} />
          ))}
        </ul>
      )}
      <Dialog open={removing} onClose={() => { setRemoving(false); }} title={`Remove ${server.display_name}?`}>
        <p className="text-sm">Its tools stop working for every agent at once. Agents that use them will say the tool is switched off.</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => { setRemoving(false); }}>Cancel</Button>
          <Button variant="danger" onClick={() => { remove.mutate(); }} disabled={remove.isPending}>Remove</Button>
        </div>
      </Dialog>
    </div>
  );
}

function ToolRow({ server, tool }: { server: Server; tool: Tool }) {
  const saved = useSaved();
  const tpath = { params: { path: { server_id: server.id, tool: tool.name } } };
  const set = useMutation({
    mutationFn: (body: { enabled: boolean; without_asking: boolean }) => unwrap(api.PUT("/mcp/servers/{server_id}/tools/{tool}", { ...tpath, body })),
    onSuccess: saved,
  });
  const approve = useMutation({ mutationFn: () => unwrap(api.POST("/mcp/servers/{server_id}/tools/{tool}/approve", tpath)), onSuccess: saved });
  const findings = (tool.scan.findings as { message: string }[] | undefined) ?? [];
  const blocked = tool.scan.status === "blocked";
  return (
    <li className="py-3" data-testid="mcp-tool" data-name={tool.name}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[13px] font-medium">{tool.name}</div>
          <p className="text-sm text-stone-600 dark:text-stone-300">{tool.description || "No description"}</p>
          <p className="mt-0.5 text-xs text-stone-500">
            {tool.read_only ? "The server says it only reads." : "It may change things or send something: it asks you first, every time."}
          </p>
        </div>
        <div className="w-44 space-y-1.5">
          <Switch
            checked={tool.enabled}
            onChange={(on) => { set.mutate({ enabled: on, without_asking: false }); }}
            label="Use it"
            disabled={set.isPending || blocked}
          />
          {tool.enabled && tool.read_only && (
            <Switch
              checked={tool.without_asking}
              onChange={(on) => { set.mutate({ enabled: true, without_asking: on }); }}
              label="Runs without asking"
              disabled={set.isPending || tool.changed}
            />
          )}
        </div>
      </div>
      {findings.length > 0 && (
        <div className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200" data-testid="mcp-findings">
          <AlertTriangle aria-hidden className="mr-1 inline size-3.5" />
          {blocked ? "Blocked by the check: " : "The check found: "}
          {findings.map((f) => f.message).join(" · ")}
        </div>
      )}
      {tool.changed && tool.enabled && (
        <div className="mt-2 rounded-lg border border-amber-300 px-3 py-2 text-sm dark:border-amber-800" data-testid="mcp-changed">
          <p className="font-medium">The server changed this tool. Agents can't use it until you look.</p>
          {tool.approved_description && (
            <p className="mt-1 text-xs text-stone-500">
              Was: <span className="line-through">{tool.approved_description}</span>
            </p>
          )}
          <p className="mt-0.5 text-xs">Now: {tool.description}</p>
          <Button size="sm" className="mt-2" onClick={() => { approve.mutate(); }} disabled={approve.isPending || blocked}>
            It's fine: use the new version
          </Button>
          <p className="mt-1 text-xs text-stone-500">Published agents keep the old one until you test and publish them again.</p>
        </div>
      )}
      {(set.error ?? approve.error) && <p className="mt-1 text-xs text-rose-600">{problemText(set.error ?? approve.error)}</p>}
    </li>
  );
}
