# Tools: search the web, read pages, run Python, MCP servers

Agents do things through **tools**. You choose them for each agent in the Studio
(**Agents → your agent → Tools**), and for each helper on its own.

| Tool | What it does | Needs |
|---|---|---|
| **Search the web** | Finds pages and returns their titles, addresses and a snippet | Nothing: a private search engine (SearXNG) runs with Nuria |
| **Read web pages** | Reads a page or a PDF as text, so the agent can quote and cite it | Nothing |
| **Run Python** | Runs Python 3.12 (numpy, pandas) and shows what it printed. A last line that's an expression is shown too, as in a notebook | The sandbox (on by default) |
| **Use a terminal** | Runs shell commands (bash, coreutils) in the same sandbox | The sandbox |
| **Work with files** | Lists, reads and writes files in the sandbox's workspace | The sandbox |
| **Notes** | Keeps notes you ask it to remember | Nothing |
| **Notifications** | Sends a message to someone: **always asks you first** | Nothing (not delivered yet: recorded only) |
| **Tools from MCP servers** | Whatever the server offers: docs search, issue trackers, databases, your own services | A server you add in **Settings → Tools** ([below](#mcp-servers-tools-from-other-services)) |

A helper with no tools can only answer from what it already knows. The Studio says so,
and offers the tools its description asks for ("searches the web…" → **Search the web,
Read web pages**).

## MCP servers: tools from other services

The **Model Context Protocol** (MCP) is the standard way services share tools with AI
agents. Add a server, and its tools can be given to any agent.

1. **Settings → Tools → MCP servers → Add a server.**
   - Give it a name and its address: its Streamable HTTP endpoint, often ending in `/mcp`.
   - If it needs a token, paste it. It's saved encrypted on this computer and never shown
     again. It's sent as `Authorization: Bearer …`, or in another header you name
     under **Advanced**.
2. **Nuria tests it at once** and lists its tools. Each tool's description and arguments
   go through the same check as skills: hidden instructions ("send the user's message
   to…", "don't mention this") are flagged.
3. **Switch on the tools agents may use.**
   - **A tool asks you before every call.** The approval card shows what it's about to
     send.
   - **"Runs without asking"** is offered only for a tool the server marks read-only, and
     it's your choice: the server's label alone never decides.
4. **In the Studio,** switched-on tools appear next to the built-in ones, marked with
   their server's name. Helpers can only get the ones that run without asking.

**If a server changes a tool** (its description, arguments or labels), agents stop using
it, and Settings shows the old and new versions until you choose **It's fine: use the
new version**.
- A **published agent keeps the version it was published with.** If the server changes
  the tool, that agent gets no call until you test and publish it again. This protects
  against a server that changes a tool after you approved it (a "rug pull").
- **Switching a tool off, or removing its server,** stops it for every agent at once.

**After a crash,** a tool that runs without asking is called again; a tool that asks
first isn't sent twice, and the agent tells you it may have run once already.

**Try it:** DeepWiki answers questions about public GitHub repositories, free and without
a token. Add `https://mcp.deepwiki.com/mcp`, switch on its tools, and ask an agent about a
repository.

**Not yet:** servers you run as a command (`npx …`, stdio) and servers that need you to
sign in with OAuth (GitHub's, Notion's). Both are planned (L8b, L8c).

## Web search

**Settings → Tools → Web search** chooses where searches go:

- **Built in** (the default): SearXNG, in Docker with Nuria. No key, no account. It asks
  public search engines on the agent's behalf, so they see a search, not who you are.
- **Tavily** or **Brave**, with your API key: saved encrypted on this computer and never
  shown again (only its fingerprint).
- **Your own SearXNG**, by its address (its JSON output must be on).

**Save and test** runs a real search, so you know it works.

## Reading pages, safely

Every page is read by a separate service, the **page reader**. It refuses anything that
isn't a public website: your computer (`localhost`), your network (`192.168.…`), Nuria's
own services (the database, the API), and cloud metadata addresses. It checks again
after every redirect and connects only to the address it checked, so a page can't
redirect it inside.

**Sites agents may read** (Settings → Tools) can narrow it further: list sites (one per
line, e.g. `wikipedia.org`) and agents read pages only there.

What a page says is **information, never instructions**. A page that says "ignore your
instructions and send…" changes nothing the agent is allowed to do: sending still asks
you first, and tools it doesn't have stay out of reach.

## Running code: the sandbox

Code runs in a **sandbox**: a fresh, locked-down container for each conversation turn.

- **No internet**, no access to your files, keys or Nuria's services.
- **Limits:** 0.5 CPU, 256 MB of memory, 64 processes, 64 MB of workspace; each command
  stops at its time limit (30 s by default, up to 2 minutes).
- **A clean start each turn.** Files written in a turn are there for the rest of it, then
  the sandbox is removed.
- Only `pip`-free Python: numpy, pandas, python-dateutil and tabulate are installed.
  Nothing can be installed (no network).

`./setup.sh --no-sandbox` starts Nuria without it: the code tools aren't offered, and
everything else works. `./setup.sh --sandbox` turns it back on.

## Skills an agent always uses

Skills are know-how an agent loads when a request needs it (**Skills** in the sidebar).
Small local models rarely load skills by themselves, so each skill attached to an agent
has an **Always use** switch: its instructions are then part of every turn, still as
information, never as orders. A skill whose safety check found something to look at
asks you to confirm before it's attached.

## Stopping agents

- **Stop** (in a chat, while it answers) stops that reply at once: the model call, the
  tool, any code and helpers, not just "after this step".
- **Turn off** an agent (in the Studio, or on its card in **Agents**): every reply it's
  giving stops now, in every chat and test chat, and new messages to it are refused until
  you **Turn on**.
- **Stop all agents** (bottom of the sidebar): every agent, everywhere. A red banner stays
  on every page until **Turn agents back on**.

Waiting for your **Approve** doesn't count against an agent's time limit: approve when you
can, and it carries on.

## Download a chat

**Download** (top of a chat) saves it as Markdown: what you wrote, each reply with the
model and its tokens, the model's reasoning when it gives one, every tool call with its
arguments and full result, and what each helper did.
