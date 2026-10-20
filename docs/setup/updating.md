# Updating Nuria, and getting your data back

## Update

```bash
./setup.sh --update               # Windows: .\setup.ps1 -Update
```

1. **It backs up your data first**, to `backups/nuria-<version>-<date>.sql.gz`, and checks the backup isn't empty. If the backup fails, it stops and changes nothing.
2. **It moves to the newest release**, or the one you name: `./setup.sh --update --to v0.2.0`.
3. **It starts that release.** It downloads that version's images, updates the database (an update never removes data: every change is additive), restarts, and runs a chat turn to check everything works.
4. **If anything fails**, it prints the two commands that take you back: the version you had, and your backup.

Your chats, agents, skills, models and settings are all kept.

**Before you update:**
- **Your own edits:** if you changed files in the folder, the update refuses to mix them in. Run `git stash` first.
- **If you installed before 0.1.0:** run `git pull` once, then `./setup.sh --update`. Older versions didn't have this update.

## Get your data back

```bash
./setup.sh --restore backups/nuria-0.1.0-20261018-130602.sql.gz      # Windows: .\setup.ps1 -Restore <file>
```

It asks first, because it **replaces today's data** with the backup's. Then it puts the backup back and checks a chat turn.

**Going back to an older version** after an update has two steps:
1. **The code:** `./setup.sh --update --to v<the version you had>`.
2. **The data:** `./setup.sh --restore <the backup the update made>`.

## Keep your backups

- **They're private.** Backups are in `backups/`, readable only by you. They hold your conversations, and your model keys, encrypted with the key in `.env`.
- **Keep `.env` with them.** Without that key, a backup restores everything except your saved model keys: you'd re-enter those in **Models**.
- **Clean up.** Nothing deletes old backups; delete the ones you don't need.
