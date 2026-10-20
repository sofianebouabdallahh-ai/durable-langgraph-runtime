# Phase L3d plan — Getting started: a guided first agent

> **Status: delivered.** Results: [progress/phase-L3d.md](../progress/phase-L3d.md).

**Goal:** a person who has just installed Nuria is led, step by step and inside the real app, to their first working agent:
1. **Choose a model:** a free local one (Ollama), a key (OpenAI, Azure AI Foundry, other), or the demo model for now.
2. **Create an agent:** describe it, or start from a template.
3. **Give it a tool.**
4. **Give it a helper** (a sub-agent).
5. **Try it**, then publish it and chat with it.

Each step is done **for real**: no fake screens, no video. The guide notices when the step is done.

**Why now:** L3a–L3c built the pieces, L4 (dashboards, Kubernetes) is merged, and L5 (release v0.1, PR #23) is open. A newcomer still has to discover Settings → Models, the Studio, helpers, test chats and publishing on their own. This is the first thing the v0.1 testers and the AC43 testers (M2) will meet.

**Part of:** the [local release](local-release.md), after L5; shipped as **v0.1.1**.

---

## 1. Research findings

| Topic | Finding | Consequence |
|---|---|---|
| **Tours vs doing** | Benchmarks across hundreds of SaaS products: median tour completion is ~29%. 1–2-step tours finish at ~73%, 9+ steps at ~8%. Tours the user starts finish ~3× more often than ones that start on their own ([Produktly via Indie Hackers](https://www.indiehackers.com/post/onboarding-benchmarks-from-real-data-across-464-saas-products-median-tour-completion-is-29-6288651c93), [Chameleon](https://www.chameleon.io/blog/effective-product-tour-metrics)). Vendor data, but consistent | **No long automatic tour.** Five short steps, started by the person, each one a real action |
| **Checklists** | A checklist item should be a real change in the account, not "explore the dashboard"; filler items teach people to ignore the list ([Frigade](https://frigade.com/glossary/onboarding-checklist)). The usual recommendation is a checklist plus short, contextual guidance ([Designrevision](https://designrevision.com/blog/saas-onboarding-best-practices.md)) | A **Get started** checklist whose items tick themselves when the thing exists, plus a small **guide strip** on each screen saying exactly what to do there |
| **Accessibility** | Spotlight tours (dimmed page, a bubble on an element) are the hardest pattern to make accessible: dimmed content stays focusable, bubbles overlap controls, screen-reader behaviour varies. Inline hints are the most accessible ([Kompassify](https://kompassify.com/blog/accessible-onboarding-guide), [WebAIM](https://webaim.org/discussion/mail_message?id=40942), [Abyss](https://abyss.uhc.com/web/ui/coachmark)) | The guide is **inline content**: a labelled region above the page's own content, in reading order, never covering a control, no focus traps. Nothing to fight for keyboard or screen-reader users |
| **Libraries** | driver.js and react-joyride are MIT; Shepherd.js and Intro.js are AGPL or paid ([Inline Manual](https://inlinemanual.com/blog/driverjs-vs-introjs-vs-shepherdjs-vs-reactour)). Both MIT options are spotlight tours | **No tour library:** the pattern chosen is plain components we already have (Section, Pill, Button). No new dependency, no licence question |
| **What the app has** | Home greets and starts a chat, with no hint of agents, models or the Studio. Models has Ollama discovery and "Save and test". The Studio has Describe it, templates, tools, helpers, a test chat and Publish. The demo model works offline | The guide **links into the existing screens** and reuses their components (the Add-a-model dialog, Describe it). The only new screen is the checklist |
| **Progress** | Progress kept in the browser is lost on another browser and drifts from reality; progress derived from the account can't lie (like "Tested" in L3a) | **Derived on the server** from facts (a model ready, the guide's agent has a tool, a helper, a completed test chat, a published version, a chat). Only two things are stored: which agent is "the one from the guide", and whether the guide was dismissed |

## 2. Design

```
 Home (first visit): "New here? Build your first agent in 5 steps" card ──► #/start
 Sidebar: "Get started  2/5"  (until finished or dismissed)

 #/start — the checklist (one card per step; done ✓ / do it next / later)
   1 Choose a model      → inline chooser: Ollama (found? / how to install) · A key (kind tiles) · Demo for now
   2 Create your agent   → Describe it (an example to edit) or From a template → it becomes "your agent"
   3 Give it a tool      → opens your agent in the Studio, Tools section
   4 Give it a helper    → … Helpers section
   5 Try it and publish  → … the test chat, then Publish, then "Chat with it"

 On those screens: a guide strip "Step 3 of 5 · Give it a tool": what to do here, in one or
 two sentences · ✓ when done → "Next: give it a helper" · "Back to the guide" · "Hide"
```

### 2.1 Backend
- **Migration 0014** (`workspace_settings`; L5 uses 0013): `guide_agent_id` (the agent built in the guide, nullable, FK) and `guide_dismissed_at`.
- **`onboarding.py`** (Specification per step; the progress is derived):
  - `model_ready`: a connection passed its test and is the default, or the setup's model isn't the demo; "Demo for now" marks the step skipped, not done;
  - `agent_created`: the guide's agent exists (or the person picked one of their agents);
  - `has_tool`, `has_helper`: the guide's agent's draft or published version has ≥ 1 tool, ≥ 1 helper;
  - `tested`: a completed test-chat turn on it; `published`: it has a published version; `chatted`: a chat with it has a reply.
- **API** `/onboarding`:
  - `GET`: the steps with `done`, `skipped` and the next step; the guide's agent id and name; dismissed or not;
  - `PUT`: set the guide's agent, skip the model step, dismiss, start over.
  - `POST /studio/agents` and `…/from-proposal` take `guide: true` to make the new agent the guide's.
- **Ollama help:** the existing `GET /models/ollama` (found, with its models). When nothing is found, the UI shows per-OS install steps and the one model to pull.

### 2.2 UI
- **`#/start`, the Get started page:**
  - a title, a progress bar ("2 of 5 done"), and five step cards;
  - each card: what and why (one sentence), its state (done ✓, next, later), and one primary action;
  - done cards collapse to a line with "Change" where it makes sense;
  - at the end: "You built X. Chat with it", plus links to Skills and Models.
- **Step 1, inline chooser:** three tiles.
  - **Free on this computer (Ollama):** detects Ollama. Found: pick the model and Save and test. Not found: copyable install commands for macOS, Windows and Linux, plus `ollama pull qwen2.5:7b`, with a **Check again** button.
  - **Use a key:** the existing add-a-model form for OpenAI, Azure AI Foundry or another service, with where to find the key.
  - **Use the demo model for now:** says plainly what it can and can't do.
  - On success it offers **Make it the default** (pre-checked).
- **Step 2:**
  - **Describe it** (the L3c flow) with an editable example ("It plans family trips…"), or **From a template**;
  - the agent created becomes the guide's agent;
  - an existing agent can be picked instead.
- **The guide strip** (`GuideStrip`): shown on the Models page and in the Studio of the guide's agent, while the guide is active.
  - A `region` labelled "Getting started", above the page content.
  - It says what to do on this screen, and switches to ✓ and a **Next** link when the server says the step is done (refetched after saves and test-chat replies, as "Tested" is).
  - It can be hidden. The Studio's sections get a gentle highlight (a ring) on the one the step is about, without moving focus or covering anything.
- **Entry points:**
  - Home shows a dismissible card while the guide isn't finished;
  - the sidebar shows "Get started" with its progress;
  - nothing starts by itself;
  - dismissing hides both, and the guide stays reachable from **Help → Get started** (a link on the Agents and Models pages).
- **Words:** plain language throughout, no ids or file formats. "Helper" is explained in one line ("another agent yours can hand part of a job to, so they work in parallel"); "tool" too ("something it can use: search, a calculator, notes, notifications").

## 3. Tasks

| # | Task | Verification |
|---|---|---|
| L3d.1 | Migration 0013; `onboarding.py` (steps derived from facts); `/onboarding` API; `guide` flag on creating an agent | Integration: every step flips on the real action and only then; demo-model skip; start over; dismiss |
| L3d.2 | Get started page and step cards; Home card; sidebar entry with progress | Vitest; axe |
| L3d.3 | Step 1: the model chooser (Ollama found / not found / key / demo), reusing the Models dialog | Browser: fake connection → done; no Ollama → install help shown, Check again |
| L3d.4 | Step 2: Describe it / template / pick existing → the guide's agent | Browser |
| L3d.5 | `GuideStrip` on Models and the Studio, with the section highlight and live completion | Browser: each strip ticks without a reload |
| L3d.6 | Browser e2e 5×: a newcomer's whole path, by visible labels only (fake model, then the demo model); keyboard-only run; axe on every guide screen. A live run with Ollama | 5/5; CI |
| L3d.7 | Docs: "Getting started" in the README and `docs/setup/getting-started.md`; the tester script points to the guide; summary; PR | |

## 4. Success criteria

| # | Criterion | How | Pass when |
|---|---|---|---|
| SC1 | **A first agent, guided** | Browser, visible labels only: Get started → model (fake key) → Describe it → a tool → a helper → test → publish → chat | Every step ticks as it's done, with no reload; the person never needs a screen the guide didn't link; **5/5** |
| SC2 | **Ollama, both ways** | Ollama running / not running | Found: its models offered, Save and test → done. Not found: install steps for the person's OS and Check again, no error wall |
| SC3 | **The demo path** | No model at all | The model step can be skipped ("Demo for now"); the rest completes; the checklist shows "skipped" with a way back |
| SC4 | **Progress can't lie** | Delete the helper after step 4; edit after the test | The step un-ticks (it's derived); a reload or another browser shows the same progress |
| SC5 | **Never in the way** | Use the app without the guide; dismiss it | Nothing starts by itself; once dismissed, Home and the sidebar are as before; the guide is still reachable |
| SC6 | **Accessible** | Keyboard only, screen reader labels, axe | The whole path works from the keyboard; the strip is a labelled region in reading order; axe clean on every guide screen |
| SC7 | **Short** | Count it | 5 steps; each strip is at most two sentences; the whole path takes under 10 minutes with the demo model (timed in the browser test) |
| SC8 | Quality and docs | CI | Backend, UI, browser 5×, container e2e; getting-started doc followed on a clean stack |

## 5. Risks

| Risk | Mitigation |
|---|---|
| The guide drifts from the screens it points to | It points at sections by id (`section-tools`…), covered by the browser test; strip texts live next to the steps in one file |
| "Done" lags after an action | The strip refetches on the same signals the Studio already uses (save, test-chat reply) |
| People who don't want it | User-started, dismissible, never modal |
| Ollama install varies by OS | Commands per OS, copyable, with a link to ollama.com; Check again instead of guessing |

## 6. Out of scope
- **Video or animated walkthroughs.**
- **Tours of the other pages** (Skills is linked at the end, not toured).
- **Analytics on guide completion:** opt-in telemetry is L5.
- **Multi-user progress:** one person locally; the beta adds per-user state.
