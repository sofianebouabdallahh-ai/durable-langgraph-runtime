# Build your own agent

In Nuria, open **Agents** in the sidebar, then **New agent** (or **Copy** on a built-in agent to start from it). You never need to write code or Markdown.

## 1. Fill in the form

| Section | What to write |
|---|---|
| **Basics** | Its name ("Trip planner") and one or two sentences on what it's for. Its id (`trip-planner`) is made from the name and never changes. |
| **Instructions** | How it works, how it answers, what it never does, as if you were briefing a new colleague. **Insert** adds things filled in when it runs, like today's date. |
| **Tools** | What it can use: search, calculator, notes, notifications. Tools that reach people (notifications) **always ask you first**. You can cap how often each is used per message. |
| **Helpers** | Optional. Sub-agents it hands parts of a question to: each has its own name, description, instructions and tools, and they work in parallel. Helpers can't use tools that need your approval. |
| **Effort** | **Quick**, **Standard** or **Thorough**: how much it may do for one message. **Custom** sets the numbers. Near the limit it wraps up gracefully rather than stopping mid-sentence. |
| **Protections** | On by default: hiding passwords and keys in tool data, and telling it the date. Optional: a summary when a chat ends. |
| **Model** | It uses Nuria's model, the one chosen in setup. Choosing a model per agent comes in the next release. |

Everything is **saved as you type** ("Saved" at the top). If something isn't right, it's explained in red **next to the field**.

## 2. Try it

**Start a test chat** on the right. It's a real chat with your draft, with two differences:
- **A small budget,** so an experiment can't run away.
- **Nothing that reaches people is really sent.** You still approve a notification, and it shows what *would* have been sent.

Change something and test again: every change needs a fresh test before it can be published.

## 3. Publish

**Publish** turns your draft into **version 1** (then 2, 3…), with an optional note on what changed. From then on:
- **Everyone can chat with it:** from Home's agent picker, or with **Chat with it**.
- **A published version never changes.** To change it, click **Edit**, which creates a draft, then test and publish again. Chats already running finish on the version they started with; new messages use the new version.
- **History** lists every version. **Restore** turns an old version into the draft, and publishing it rolls back.

## 4. Share or back up

**Export** downloads the agent as a file: a single `.agent.md`, or a `.zip` when it has helpers. **Import** on the Agents page turns such a file into a new agent (never replacing one). The files are the same format as the built-in agents in `backend/agents/`, so you can also keep them in git.

## Good to know

- **Built-in agents** (like Nuria) are read-only. Copy one to make your own version.
- **Test chats** don't appear in your chat list; they live in the editor.
- The Studio and the built-in agents share **one set of rules**, so if the Studio accepts an agent, so would a file, and the other way round.
