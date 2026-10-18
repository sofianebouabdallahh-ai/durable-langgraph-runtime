# Build your own agent

In Nuria, open **Agents** in the sidebar, then **New agent**. You never need to write code or Markdown. Choose how to start:

- **Describe it** (the default): say in a few sentences what you want ("It plans family trips, keeps to a budget, and has a helper that finds kid-friendly restaurants"), then **Draft it**. Nuria's builder agent fills in the form: name, instructions, tools, effort, helpers, and skills from your library that fit. You see a summary first; **Use this draft** opens it in the editor, **Try again** starts over. Nothing is saved until you accept.
- **From a template**: start from a built-in agent (or **Copy** on its card). The original stays as it is.
- **Start blank**: a name, and you fill in the rest.

The draft uses your default model (Settings → Models). Offline, with the demo model, it's a simple reading of your words: a starting point to edit.

## 1. Fill in the form

| Section | What to write |
|---|---|
| **Basics** | Its name ("Trip planner") and one or two sentences on what it's for. Its id (`trip-planner`) is made from the name and never changes. |
| **Instructions** | How it works, how it answers, what it never does, as if you were briefing a new colleague. **Insert** adds things filled in when it runs, like today's date. **Improve my instructions** suggests a clearer version next to yours: **Use the suggestion** or **Keep mine**. |
| **Tools** | What it can use: search, calculator, notes, notifications. Tools that reach people (notifications) **always ask you first**. You can cap how often each is used per message. |
| **Skills** | Optional. Know-how from your [skill library](skills.md) that it loads when a task needs it: a checklist, a house style. It sees only each skill's name and "when to use it" until it loads one. |
| **Helpers** | Optional. Sub-agents it hands parts of a question to: each has its own name, description, instructions, tools, model and skills, and they work in parallel. Helpers can't use tools that need your approval. |
| **Effort** | **Quick**, **Standard** or **Thorough**: how much it may do for one message. **Custom** sets the numbers. Near the limit it wraps up gracefully rather than stopping mid-sentence. |
| **Protections** | On by default: hiding passwords and keys in tool data, and telling it the date. Optional: a summary when a chat ends. |
| **Model** | The default model, or any model you added in [Settings → Models](models.md). Each helper can use a different one. |

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

**Export** downloads the agent as a file: a single `.agent.md`, or a `.zip` when it has helpers or skills (its skills travel with it, in the standard skill format). **Import** on the Agents page turns such a file into a new agent (never replacing one); skills it carries join your library, are scanned like any upload, and an identical skill is reused. The files are the same format as the built-in agents in `backend/agents/`, so you can also keep them in git.

## Good to know

- **Built-in agents** (like Nuria) are read-only. Copy one to make your own version.
- **Test chats** don't appear in your chat list; they live in the editor.
- The Studio and the built-in agents share **one set of rules**, so if the Studio accepts an agent, so would a file, and the other way round.
- **Publishing locks its skills.** A published version keeps the skill versions it was tested with; editing a skill changes drafts (test again), never a published agent until you publish again.
