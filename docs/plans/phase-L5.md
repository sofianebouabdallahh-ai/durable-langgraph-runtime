# Phase L5 plan — Release v0.1 & the feedback loop

**Goal:** the first release that strangers can install, keep up to date without losing anything, and tell us about in two clicks.

**Part of:** the [local release](local-release.md) (L1 ✅ → L2 ✅ → L3a–c ✅ → L4 ✅ → **L5**). **Milestone M3:** 5–10 external testers installed it and their feedback is collected.

**Requirements:** [local-release](local-release.md) §4.7 (updating and keeping data), §4.8 (feedback and diagnostics), §4.9 (documentation).

## 1. Research findings

| Topic | Finding | Consequence |
|---|---|---|
| **Versions** | The Python package says `0.0.0`, the UI says `0.1.0`, and the charts say `0.1.0`. Compose and the charts use `:latest` images. The release workflow already publishes semver tags (`0.1.0`, `0.1`) and `latest` for a `v*` tag | **One `VERSION` file**. Setup writes `NURIA_VERSION` to `.env`, and Compose pulls `…:${NURIA_VERSION}`, so an update lands on exactly one release and a rollback is possible. The workflow refuses a tag that doesn't match `VERSION` |
| **`--update`** | It runs `git pull --ff-only`, takes a backup with `pg_dump` (not checked for being empty), restarts and smoke-tests. There is no restore and no upgrade test | Move to the **newest release tag** (or `--to vX.Y.Z`). Check the backup isn't empty. Pull that version's images, migrate, restart, smoke-test, and on failure print how to restore. Add **`--restore FILE`**. CI tests an upgrade from the previous release with data in it |
| **Previous release for the upgrade test** | No `v*` tag exists yet; the phase tags (`phase-L1` … `phase-L4`) do | The test upgrades from the newest `v*` tag, else the newest `phase-*` tag: today `phase-L4`. Its images are built from that checkout |
| **Feedback** | No issue templates and no way to give feedback in the app. GitHub accepts `/issues/new?template=…&title=…&body=…`; long URLs are cut off around 8 KB | A **Send feedback** form. It opens a pre-filled issue, short text only, or downloads the same text. Anything large (an agent, a turn's events) is a **downloaded bundle** the tester attaches. Nothing leaves the machine without a click |
| **Telemetry** | Nothing is collected. There is no server to receive it until the hosted beta (P12) | **Opt-in, content-free usage counts:** versions, OS and CPU, the model provider type, and counts of chats, turns, agents, skills and failures by reason. They are computed from the database on request. When on, they are **attached to a feedback report**, shown in its preview first. Nothing is sent on its own. Every field is documented |
| **Exports** | Agents export (L3a) and so do skills (L3c); conversations don't | **Download this chat** (Markdown). The "report this reply" bundle includes it only if the tester ticks the box |
| **Docs** | Guides exist for each OS, models, agents, skills, troubleshooting and the AC43 tester script. The README's status stops at L3a. There is no guide for testers, no security note, and nothing on updating | A README refresh, **testers.md** (what we want feedback on and how to send it), **security.md** (what runs where, where keys are, how to delete everything), and **updating.md** (update, backups, restore) |

## 2. Design

### 2.1 Versions and releases
- `VERSION` (`0.1.0`) is read by the backend's `/about`, the UI's About line, the charts' `appVersion`, setup and the release workflow.
- Setup writes `NURIA_VERSION` (the checkout's `VERSION`) to `.env`. Compose uses `image: …:${NURIA_VERSION:-latest}`.
- The release workflow, on `v*`:
  - checks that the tag equals `v$(cat VERSION)`;
  - publishes the images (as today);
  - creates a GitHub Release whose notes are that version's CHANGELOG section.

### 2.2 Update, backup, restore
- **`./setup.sh --update [--to vX.Y.Z]`:**
  1. Refuse with local changes.
  2. `git fetch --tags`, then check out the target: the newest `v*` tag when on a release, else fast-forward the branch.
  3. Back up: `pg_dump` → `backups/nuria-<version>-<time>.sql.gz`, checked to contain the schema.
  4. Set `NURIA_VERSION`, then pull (or build).
  5. `up` (the migrate service runs first; migrations are expand/contract).
  6. Smoke-test. On failure, print the restore command and the previous version.
- **`./setup.sh --restore backups/….sql.gz`:**
  1. Confirm (it replaces today's data).
  2. Stop the app.
  3. Recreate the database from the dump.
  4. Start.
  5. Smoke-test.
- **`setup.ps1`** gets `-Update -To` and `-Restore`.

### 2.3 Feedback
- **Send feedback** sits at the bottom of the sidebar. It opens a dialog with:
  - what you were doing; what happened;
  - how it felt (1–5);
  - "include this installation's details" (version, OS and CPU, model provider type);
  - "include usage counts", only when telemetry is on.
- **The dialog shows the exact text, then offers two buttons:**
  - **Open a GitHub issue**: a new tab with the `feedback` template, title and body pre-filled.
  - **Download**: a `.md` file to email.
- **Report this reply**, under a reply's *What happened?*:
  - **Downloads a zip:**
    - the turn's events;
    - the agent's export, when it's one of yours;
    - the reply's text, only if ticked.
  - **Opens** the `agent-didnt-do-what-i-expected` template, which asks for the zip.
- **Issue templates** (`.github/ISSUE_TEMPLATE/`): bug, idea, feedback, agent behaviour. `config.yml` links the docs and the doctor bundle.

### 2.4 Telemetry (opt-in)
- **Where it's set:** Settings → **Privacy**. The switch is off by default and stored in the database (migration `0013`, `app_settings`).
- **`GET /telemetry`:** the counts, exactly as they would be shared.
- **`PUT /telemetry`:** on or off.
- **Never included:** content, prompts, names, keys or URLs. A test checks that no string from the database's content tables appears in the report.

### 2.5 Exports
- **`GET /sessions/{id}/export`:** Markdown with title, agent, and every message, tool card and approval, in order.
- **In the UI:** **Download this chat** in the chat's menu.

## 3. Tasks

| # | Task | Verification |
|---|---|---|
| L5.1 | `VERSION`; `/about` and the UI show it; `NURIA_VERSION` in setup and Compose; the release workflow checks the tag and creates the Release | Unit: about's version; workflow lint; `./setup.sh` writes the version, Compose resolves the tag |
| L5.2 | `--update [--to]`, the backup check, `--restore`; the same in setup.ps1 | Locally: update from `phase-L4` with data; restore a backup; the data is identical (counts and a chat's messages) |
| L5.3 | CI: upgrade from the previous release with data in it, then restore | The job is green on the PR |
| L5.4 | Feedback dialog, report-this-reply bundle, issue templates | Vitest (issue URL, body under the URL limit, nothing included unticked); browser test |
| L5.5 | Telemetry: migration, API, Privacy page | Unit and integration: off by default; counts correct; no content strings |
| L5.6 | Conversation export | Integration: Markdown in order; a tool card; an approval |
| L5.7 | Docs: README, testers.md, security.md, updating.md, troubleshooting additions; CHANGELOG `0.1.0` | Links checked; every doc says what to do, not how it works |
| L5.8 | Release `v0.1.0` (after merge) | The workflow publishes the images and the Release; a clean `./setup.sh` on the tag pulls `0.1.0` |

## 4. Success criteria

| # | Criterion | Pass when |
|---|---|---|
| SC1 | **Install a release** | A clean `./setup.sh` on `v0.1.0` pulls the `0.1.0` images, and the app shows *Nuria 0.1.0* |
| SC2 | **Update keeps everything** | An update from the previous release with chats, agents, skills and a saved model keeps all of them, and the smoke turn passes; in CI |
| SC3 | **Restore** | Restoring the update's backup brings back exactly the data from before (counts and a chat's messages) |
| SC4 | **Feedback in two clicks** | Send feedback → Open a GitHub issue: the issue page opens pre-filled. Nothing is sent before the click (browser test, no network request to github.com) |
| SC5 | **Report a reply** | The zip has the turn's events and the agent; the reply text only if ticked |
| SC6 | **Telemetry is opt-in and content-free** | Off by default; on, the counts appear in the feedback preview; no prompt, name, key or URL in it (test) |
| SC7 | **Docs** | A tester can go from the README to a working chat, an update and a feedback report without help (checked against testers.md) |
| SC8 | Quality | Backend, UI, browser and container e2e, kind and the upgrade job are green |
| M3 | **5–10 external testers** | Their feedback is collected. This happens after the release, with people, and isn't decided by this PR |

## 5. Risks

| Risk | Mitigation |
|---|---|
| An update breaks someone's data | A checked backup first; expand/contract migrations; a restore command; the upgrade is tested in CI with data in it |
| A pre-filled issue leaks something private | Only what the tester typed and ticked, shown in full before sending; bundles are downloaded, never uploaded |
| "Telemetry" erodes trust | Off by default, nothing sent automatically, every field documented, and the preview is the exact payload |
| `latest` drifting under a tester | Releases pin `NURIA_VERSION`; `latest` is only a fallback for an old `.env` |

## 6. Out of scope

- **Hosted telemetry** and a collection endpoint (P12).
- **Automatic updates** and update notifications.
- **Signed images and verification on pull.** The release already attaches an SBOM and provenance.
- **The tester sessions themselves**, which produce M3.
