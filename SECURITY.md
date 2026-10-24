# Security policy

## Supported versions

Nuria is young and maintained by one person. Security fixes go into the latest release only.

| Version | Supported |
|---|---|
| 0.2.x | ✅ |
| < 0.2 | ❌ (update with `./setup.sh --update`: it backs up your data first) |

## Reporting a vulnerability

**Please don't open a public issue.** Report it privately on GitHub instead: the repository's **Security** tab → **Report a vulnerability** ([direct link](https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime/security/advisories/new)). Only you and the maintainer see it.

Helpful to include: what you found, how to reproduce it (the setup command, the model, the steps), and what an attacker could do with it.

What to expect: an answer within 7 days (it's a one-person project: best effort), a fix or a plan once it's confirmed, and credit in the release notes if you'd like it.

## Scope

In scope: the code in this repository and its defaults (`./setup.sh`, the Compose stack, the Helm charts, the published images), for example:
- a secret (a model key, an MCP token, a database password) that leaks into logs, traces, the audit trail, a download or the browser;
- a way around an approval, a budget, the kill switch or the sandbox;
- text from a tool, a web page, an MCP server or a skill that makes an agent use a tool or send data without your approval;
- a service reachable from outside your machine with the default settings.

Out of scope: what a model says (models make mistakes; Nuria's job is that they can't act without you), third-party MCP servers and model providers themselves, and setups that turn the defaults off on purpose (`--no-sandbox`, exposing ports beyond `127.0.0.1`).

How Nuria protects you, and how to delete everything: [docs/security.md](docs/security.md).
