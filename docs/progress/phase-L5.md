# Phase L5 — Release v0.1 & the feedback loop

**Completed:** 2026-10-18 (built; **v0.1.0 is tagged after the merge**; M3 after the testers) · **Branch:** `feat/l5-release-v0.1` · **Plan:** [plans/phase-L5.md](../plans/phase-L5.md) · **Guides:** [testers](../setup/testers.md), [updating](../setup/updating.md), [security](../security.md) · **Tests:** backend 555 (+9) · UI unit 62 (+5) · browser 3 new · an upgrade job in CI

## What we built

**One version everywhere.** `VERSION` (0.1.0) is the release.
- **In step:** the backend, the UI and both charts carry it, and a unit test keeps them in step.
- **Pinned images:** setup writes `NURIA_VERSION` to `.env`, so Compose pulls exactly that release's images. `latest` is only a fallback for an older `.env`.
- **On screen:** the sidebar shows *Nuria 0.1.0*.
- **Releasing:** a `v*` tag must match `VERSION` and the changelog. The release workflow then publishes the images and a GitHub Release, whose notes are that version's changelog section.

**Updates that keep everything, and a way back.** `./setup.sh --update [--to vX.Y.Z]`:
1. **Backs up first, and checks the backup.** If the backup fails, nothing is changed.
2. **Moves to the newest or the named release.**
3. **Hands over to the new version.** The new version's own `setup.sh` finishes: its images, migrations, a restart, a smoke turn. The old script no longer starts a version it doesn't know.
4. **Prints the way back on any failure:** `--update --to v<previous>`, then `--restore <backup>`.

**`./setup.sh --restore FILE`** puts a backup back. `setup.ps1` has `-Update -To` and `-Restore`; it dumps inside the container, so PowerShell can't re-encode the file.

**Feedback in two clicks.**
- **Send feedback** sits at the bottom of the sidebar: what you were doing, what happened, how it felt.
  - The text appears exactly as it will be sent: the installation's details if ticked, and the usage counts if sharing is on and ticked.
  - **Open a GitHub issue** opens the `feedback` issue form with every field filled in from the URL, capped under 8 KB. **Download** saves the full text.
- **Report this reply**, under *What happened?*, downloads a zip:
  - the steps, with structural fields only (names of steps and tools, times, outcomes, reasons);
  - the agent's definition, if it's one you made;
  - the conversation, only if ticked.

  It then opens the "my agent didn't do what I expected" issue.
- **Download this chat**: the chat as Markdown, in the chat's header.
- **Issue templates:** feedback, something broke (asks for `--doctor`), agent behaviour (asks for the zip), an idea.

**Usage counts, opt-in.**
- **Where:** Settings → **Privacy**. Off by default (migration 0013).
- **What:** versions, kinds and counts, never content. They are computed from the database on request and shown exactly.
- **Where they go:** they are only ever attached to feedback the person sends. There's no server to send them to until the hosted beta.

**Docs:**
- the [tester guide](../setup/testers.md): install, what to try, how to send feedback, every usage count;
- [updating and backups](../setup/updating.md);
- [what runs where and how to delete it](../security.md);
- troubleshooting rows for updates, memory and a short secret key;
- the README for v0.1.0, with `git clone --branch v0.1.0`.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC1 | **Install a release** | ✅ Setup pins `NURIA_VERSION` from `VERSION`; Compose resolves `…:0.1.0` (and `latest` for an old `.env`); the app shows *Nuria 0.1.0* (browser test). ⏳ Pulling `0.1.0` from GHCR needs the tag, and the packages to be public (see below) |
| SC2 | **Update keeps everything** | ✅ `infra/ci/upgrade.sh`: `phase-L4` installed with two chats (14 messages), then updated to this branch. Every chat and message is identical, and the smoke turn passes. Locally, and in CI on every PR |
| SC3 | **Restore** | ✅ In the same run: a chat added after the update is gone after `--restore` of the update's backup, and everything else matches the snapshot from before the update |
| SC4 | **Feedback in two clicks** | ✅ Browser: the issue URL carries the template, title and each field; the download has the full text; **no request to github.com** before the click; an empty form can't be sent |
| SC5 | **Report a reply** | ✅ Integration: the zip has README and events.json, and no secret string by default; `chat.md` and full events only with `include_chat`; your own agent's `agent.md`. Browser: the download is a zip, and the issue link uses the agent-behaviour template |
| SC6 | **Telemetry opt-in and content-free** | ✅ Integration: off by default; a planted string in a title, a message, tool args and a note appears nowhere in the report; every field is documented. Browser: the counts reach the feedback preview only when on and ticked |
| SC7 | **Docs** | ✅ README → testers.md → install, try, update, send feedback; security.md → delete everything |
| SC8 | Quality | ✅ Backend 555 passed (coverage 92%); UI 62 unit tests; full browser suite (see the PR); the kind and upgrade jobs in CI |
| M3 | **5–10 external testers** | ⏳ After the release: with people, not this PR |

## Bugs found by testing

- **Every good backup was judged empty.** The backup check `gzip -dc … | grep -q` exits at the first match, `gzip` gets SIGPIPE, and under `pipefail` the pipeline fails. The update then (correctly) refused to go on. The check now reads the whole dump.
- **`--update` didn't work in a git worktree.** It checked for a `.git` folder, which is a file in a worktree. It now asks git.
- **The old setup started the new version.** During an update, the version being replaced would have run the new version's start: the new script now finishes the job.
- **The version in the sidebar was slightly too faint**: 4.46:1, under WCAG AA's 4.5. Caught by the accessibility checks.
- **"Send" now matches "Send feedback".** The browser tests' lookup of the Send button had to become exact.

## Before testers can install it

1. **Merge, then tag `v0.1.0`.** The release workflow builds and publishes the images and the GitHub Release.
2. **Make the GHCR packages `runtime` and `ui` public.** They're private until then, and testers couldn't pull them; setup would fall back to building locally, which takes minutes.
3. **Invite 5–10 testers** with the [tester guide](../setup/testers.md).

## Known limitations

- **Nothing sends usage counts on its own.** Hosted telemetry comes with the beta (P12).
- **No update notifications:** testers hear about a new version from us.
- **`setup.ps1`'s update and restore** mirror `setup.sh` but haven't been run on Windows yet.
