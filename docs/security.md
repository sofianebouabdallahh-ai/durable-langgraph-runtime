# What runs where, and how to delete it

Nuria runs entirely on your computer, in Docker.

## What runs

| Part | What it does | Reachable from |
|---|---|---|
| The app (UI) | The page you use, and the way in to the API | `127.0.0.1` only: this computer, not your network |
| 2 API servers, 2 workers | Your chats and agents. The workers run the steps of each reply | Inside Docker only |
| Postgres | Everything that's kept: chats, agents, skills, settings | Inside Docker; `127.0.0.1` for developer tools |
| Redis | The work queue (holds nothing that can't be rebuilt) | Inside Docker; `127.0.0.1` for developer tools |
| SearXNG | Web search for the agents (no key, no account) | Inside Docker only |
| The page reader | Reads web pages for the agents; refuses anything that isn't a public website | Inside Docker only |
| sandboxd *(on unless `--no-sandbox`)* | Starts the code sandboxes. The only part with the Docker socket, so it runs as root, alone, and answers only the workers' token | Inside Docker only |
| A sandbox per turn that runs code | Python and shell commands. **No network**, read-only, non-root, all capabilities dropped, CPU, memory, process and time limits; removed when the turn ends | Nothing: no network at all |
| *Optional:* Ollama | A local model | `127.0.0.1` |
| *Optional:* OpenTelemetry Collector, Tempo, Loki, Prometheus, Grafana (`--observability`) | Traces, log lines (redacted at the source and again in the collector), metrics, dashboards | `127.0.0.1` (Grafana and Prometheus); the rest inside the Compose network |

The containers run as ordinary users, not root, on a read-only filesystem (sandboxd
excepted, as above).

## What leaves your computer

- **Your messages, sent to the model you chose.** With the demo model or Ollama, nothing leaves. With OpenAI, Azure or another service, each turn is sent to that service under your account and its privacy terms.
- **Web searches and pages, when an agent uses those tools.** With the built-in search,
  SearXNG sends the query to public search engines (they see a search from your
  connection, not your chats). With Tavily or Brave, the query goes to them under your
  key. Pages are fetched from the sites themselves. Code in the sandbox can't reach the
  internet at all.
- **Notifications you approved**, to the webhook you set (`NOTIFY_WEBHOOK_URL`), signed
  with your secret. With no webhook set, nothing is sent.
- **Downloads from GitHub:** Nuria's code and images, when you install or update.
- **Nothing else, and nothing on its own.**
  - Feedback opens GitHub's page only when you click. You see the text first, and submit it there yourself.
  - The usage counts (**Settings → Privacy**, off unless you turn them on) are only ever attached to feedback you send.

## Who can drive it

- **Only Nuria's own pages.** The app answers only to `localhost`, `127.0.0.1` and the
  names you add in `UI_HOSTNAMES`; any other name gets "421". A web page that
  rebinds its domain to your computer (DNS rebinding) still sends its own name, so it
  is refused. The API refuses any request your browser makes on another site's behalf
  (cross-site, checked with the browser's `Sec-Fetch-Site` and `Origin`).
- **Nuria has no login yet.** Another program running on your computer can use the API,
  as with any local tool. Accounts come with the hosted version. On Kubernetes with a
  public address, the chart refuses to install without a password in front
  ([guide](kubernetes.md)).

## Where your keys are

- **Model keys** you add under **Models**, and a **search key** (Tavily, Brave) under **Tools**, are stored in the database, **encrypted** with `NURIA_SECRET_KEY` from `.env`. They're never shown again and never written to logs.
- **A key stays with its address.** Changing a model's address to another host, or an MCP server's address or header, asks for the key again: a saved key is only ever sent where you entered it for.
- **Local passwords** for Postgres and Grafana, SearXNG's secret and sandboxd's token are generated for this machine at setup, and kept only in `.env`. The sandboxes never see any of them.
- **`.env` holds the secrets.** It's readable only by you, and never part of a backup or a diagnostics file. Keep it safe: anyone with `.env` and a backup can open your saved keys.
- **Diagnostics** (`./setup.sh --doctor`) remove every password and key before writing the file.
- **Logs never hold content or keys.** Each line says what happened and its numbers (a tool call, its status and time), never message text, tool arguments or results; every line also goes through the secret filter, and the collector drops well-known secret fields a second time. Errors in the app's page are written to the API's log on this computer, nowhere else.
- **Who changed what** (Activity → Who changed what) records every change to agents, skills, models, settings, the kill switch and approvals, with what it was before. The app can add to it and read it, never edit or delete it. A key appears there only as "set", with a short fingerprint.

## What agents can do

- **Tools that touch the outside world need you.** Anything that sends something somewhere (like *notify*) waits for your **Approve**.
- **Budgets.** Every reply has a limit on steps, tool calls, tokens and cost, and stops at it.
- **Other content is treated as data.** Text that comes back from tools, web pages and MCP servers, and skills the agent loads when it needs them, is marked as data, never instructions. A planted "ignore your instructions" in a page or a skill can't grant a tool or skip an approval.
- **A skill set to Always use is your own instruction** when its check (below) found nothing: the agent gets it as plain guidance, because small local models skip guidance marked as data (in our tests, 1 time in 10 followed). A skill the check flagged stays data. Either way it can't grant a tool, change a limit or skip an approval: those are enforced by the app, not by the model.
- **Pages only from public websites.** The page reader refuses this computer, your network, Nuria's own services and cloud metadata addresses, after every redirect, and connects only to the address it checked. **Sites agents may read** narrows it to a list.
- **A page address nobody gave the agent asks first.** An agent reads, without asking, pages you named in the chat, pages a web search found, and sites on your list. Any other address (one planted in a page, which could carry your chat out in its query string) waits for your **Approve**, with the full address shown.
- **Addresses you give Nuria are checked.** An MCP server, a model address or a SearXNG address is resolved and refused if it leads to cloud metadata or Nuria's own services, whatever form it's written in (decimal, hex, a name that resolves there). Inside Nuria's containers, `127.0.0.1` is Nuria itself: for a server on your computer use `host.docker.internal`. These are checked when saved, tested and used; the model and MCP libraries resolve the name again when they connect.
- **MCP tools follow the same rules** ([guide](setup/tools.md#mcp-servers-tools-from-other-services)):
  - Every call asks first unless you chose "runs without asking" for a read-only tool.
  - Results are treated as data, and descriptions are checked when the server is tested.
  - A tool a server changed is blocked until you look; published agents keep the version
    they were published with.
  - Server tokens are stored encrypted, like model keys, and never shown, logged or put in
    the audit trail (a fingerprint only).
  - Nuria refuses its own services and cloud metadata addresses as MCP servers, and a
    token is only sent to the address and header it was entered for.
- **Code runs in a sandbox**, never in Nuria's own containers: no network, no keys, no files of yours, limits on CPU, memory, processes and time, a fresh one per turn.
- **Skills are checked when saved, and again when the checks improve.** A skill that hands over keys or tries to steer the agent is flagged, and attaching it asks you first. Skills with scripts are kept, but their scripts never run.
- **You can stop them.** **Stop** ends a reply at once (the tool or code it's running too); **Turn off** stops one agent everywhere, and **Stop all agents** every agent, until you turn them back on.

## Delete everything

```bash
./setup.sh --reset        # Windows: .\setup.ps1 -Reset   (asks first)
```

This deletes every chat, agent, skill, setting and downloaded model, and removes any sandbox left running. Then delete:
- the folder, which holds `.env` and `backups/`;
- the images, if you want the disk space back: `docker image prune -a`.

On Kubernetes (`--kubernetes`), `infra/kind/cluster.sh down` deletes the cluster and everything in it.
