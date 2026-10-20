# Testing Nuria: a guide for testers

Thank you for trying Nuria. This is its first release (**0.1**). It runs on your computer, and what you tell us decides what we build next.

## 1. Install it (10 minutes)

You need **Docker** and nothing else: [macOS](macos.md) · [Windows](windows.md) · [Linux](linux.md).

```bash
git clone --branch v0.1.0 https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime.git nuria
cd nuria
./setup.sh            # Windows (PowerShell): .\setup.ps1
```

Setup asks which model to use:
- **Ollama** (the default): a free model on your computer. If Ollama is installed, setup downloads the model it needs (about 5 GB, once); if not, it runs Ollama in Docker ([models.md](models.md)).
- **Your own account:** an OpenAI or Azure key. You can also add keys later in the app, under **Models**.
- **Demo model:** works offline with no download, but follows simple rules rather than understanding you.

When it says **Nuria is ready**, it opens http://localhost:3000.

## 2. What we'd love you to try

Use it as you like. These are what we most want to hear about:

1. **A conversation.** Ask something that needs a tool (a sum, a note to keep), and something that needs an approval ("tell the team…"). Press **Stop** in the middle of a long reply.
2. **"What happened?"** under a reply. Does the story make sense?
3. **Build an agent.** The first time, follow **Get started** on Home: it walks you through a model, your agent, a tool and a helper, a test and publishing ([guide](getting-started.md)). Then try a skill ([guide](skills.md)).
4. **Your own model**, if you have one, under **Models** ([guide](models.md)).
5. **An update**, when we tell you a new version is out: `./setup.sh --update` ([guide](updating.md)).

And anything that surprised you: good or bad, big or small.

## 3. Tell us (two clicks)

- **Send feedback**, at the bottom of the sidebar. Write what you were doing, what happened and how it felt, then:
  - **Open a GitHub issue**: GitHub opens with everything filled in, so you can check it before you submit; or
  - **Download**: a file you can email us instead.
- **A reply that went wrong?** Under it, open **What happened? → Report this reply**. Download the report, then open the issue and attach the file.
  - The report says what the reply did, step by step, without the conversation's text, unless you tick the box that adds it.
- **Something broke?** Run `./setup.sh --doctor` and attach the file it writes to a "Something broke" issue. Every password and key in it is removed.

Nothing is ever sent without your click. **Settings → Privacy** shows the usage counts you can choose to add to your feedback, if you turn them on.

## What the usage counts are (only if you turn them on)

They are numbers and kinds, never what you wrote:

| Count | What it is |
|---|---|
| `version`, `deployment`, `cpu` | Nuria's version; Compose or Kubernetes; your computer's CPU type (e.g. arm64) |
| `model_provider`, `connections` | The model type setup uses (scripted, ollama, openai); the model connections you added, by type |
| `chats`, `turns`, `days_active` | How many chats and turns, and on how many days |
| `turns_failed` | Turns that failed, by reason (e.g. `budget:tokens`), never their text |
| `agents`, `agents_published`, `skills` | How many agents you made and published, and skills you added |
| `approvals` | Approvals decided, by decision (approve, reject) |

You see exactly these values, from your installation, before anything is shared.

## 4. When you're done

- **Stop it** with `./setup.sh --stop`. Your data is kept.
- **Delete everything** with `./setup.sh --reset`. It asks first; then delete the `nuria` folder.

See [what runs where, and how to delete it](../security.md).
