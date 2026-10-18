# Skills

A **skill** is reusable know-how an agent loads when a task needs it: how your team writes a weekly update, a packing checklist, the questions to ask before planning a trip. Skills live in a library (**Skills** in the sidebar) and are attached to agents and helpers in the Studio.

Skills use the open [Agent Skills](https://agentskills.io/specification) format, so a skill written elsewhere can be uploaded here, and one written here downloads as a standard folder.

## How agents use them

- An agent sees only each attached skill's **name** and **when to use it**: a line each, so many skills don't crowd its instructions.
- When one fits the task, it **loads** it and reads the instructions (and any reference file it needs). In a chat this shows as **Used a skill**.
- A helper sees **only its own** skills, and the main agent only its own.
- A skill is **reference material, never rules**: it can't give an agent tools, raise its limits or skip an approval. Whatever a skill says, the agent's own tools, limits and approvals decide.

## Write one

**Skills → New skill**:

| Field | What to write |
|---|---|
| **Name** | A short name; it's saved in the standard form (`Weekly update` → `weekly-update`) and never changes. |
| **When should an agent use it?** | What it's for and when, in a sentence or two. This is all the agent sees until it loads the skill, so make it specific: "How our team writes a weekly update. Use when asked for a status update." |
| **What it should know or do** | The know-how itself: steps, rules, examples. Under about 5,000 tokens works best (the form shows the count); longer material can go in a reference file. |
| **Reference file** | Optional. A longer document the agent reads only when it needs it, e.g. a full checklist. |

**Edit** saves a new version (the name stays). **Download** gives the skill's folder as a zip.

## Upload one

**Skills → Upload**: a zip of a skill folder (`my-skill/SKILL.md`, plus `references/`, `assets/`, `scripts/` if any), or just a `SKILL.md`. The folder's name must match the skill's `name`. Limits: 10 MB and 100 files. **Upload a new version** (in a skill's details) replaces it with a new upload of the same skill.

## The scan

Every save and upload is checked against the standard and **scanned**. The report says what was found, where (file and line), in plain words:

| Finding | What happens |
|---|---|
| **A secret** (an API key, a token, a password in a URL) | **Not saved.** Skills are text agents and people read; remove it and try again. The secret is never shown back. |
| **Text that tries to steer the agent** ("ignore previous instructions", "send this to…") | Saved, marked **Needs a look**. Check it's meant. |
| **Web addresses** | Saved, listed for you to check. |
| **Long encoded blocks, invisible characters** | Saved, marked: they can hide text from people. |
| **Code** (`scripts/`, executables) | Saved and **never run**: Nuria can't run skill code yet, and agents can't read it. Shown as **Has code: never runs**. |

## Versions and published agents

- A **draft** agent uses each skill's current version: edit a skill and the draft needs a new test.
- **Publishing locks** the skill versions the agent was tested with. Editing or removing a skill never changes a published agent; publish it again to take the new version.
- **Remove** takes a skill out of the library; published agents keep the version they locked.
- **Built-in skills** (`trip-planning`, `plain-writing`) ship with Nuria and are read-only: download one and upload a copy under another name to change it.

## In agent files

Agent files list skills by name (`skills: [weekly-update]`, on the agent or a helper). An exported agent `.zip` carries its skills next to it, in `skills/<name>/`; importing it adds them to the library (scanned like any upload), reuses an identical one, and refuses a different skill with the same name.
