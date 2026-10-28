<p align="center">
  <img src="assets/logo.svg" width="120" alt="arc-to-zen logo">
</p>

<h1 align="center">arc-to-zen</h1>

<p align="center">
  Move your <a href="https://arc.net">Arc</a> setup into <a href="https://zen-browser.app">Zen Browser</a> on macOS,
  without touching Arc.
</p>

<p align="center">
  <img alt="macOS" src="https://img.shields.io/badge/platform-macOS-lightgrey">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="No dependencies" src="https://img.shields.io/badge/dependencies-none-brightgreen">
  <img alt="MIT" src="https://img.shields.io/badge/license-MIT-green">
</p>

> **The browsers:** [Arc](https://arc.net) by The Browser Company · [Zen Browser](https://zen-browser.app)
> ([source](https://github.com/zen-browser/desktop)). This is an independent community tool. See
> [Disclaimer](#disclaimer).

It moves spaces, pinned tabs and folders, favourites, profiles, colours, and history.

Zen's importer doesn't list Arc, and Arc keeps most of its sidebar in its own JSON rather than
Chromium's bookmarks file. These scripts read Arc's data, build an editable plan, and write it
straight into Zen's session files.

**Arc is never modified.** Step 1 only *copies* Arc's data into `snapshot/`, and everything after
that works on the copy. The scripts refuse to write to any path inside Arc's data folder.

## What maps to what

| Arc | Zen |
|---|---|
| Profile | Container (separate cookies/logins per workspace) |
| Space | Workspace, with its profile's container as default |
| Pinned tabs & folders (nested) | Pinned tabs & folders, same order |
| Favourites (per profile) | Essentials (per container) |
| Space colour, intensity, grain, icon | Workspace theme colour, opacity, texture, emoji |
| Split view | Its tabs, in order |
| History | Zen's native importer, via a temporary shim (step 4) |
| Passwords | Arc CSV export → Zen import (manual, step 5) |
| Notes, easels, boosts | Not migrated (listed in the preview) |

> **Know the difference:** an Arc profile isolates *everything* (passwords, history, extensions).
> A Zen container isolates only cookies and site storage. Passwords, history, extensions and settings
> are shared across all workspaces in one Zen profile. That's a Firefox limitation, and Zen has no
> equivalent today. If you need full isolation for something (e.g. work), use a separate Zen profile
> for it.

## Requirements

- macOS, Python 3.10+ (no third-party packages)
- Arc installed. It can stay open: the snapshot is a copy.
- Zen installed, opened once, and **quit** before applying
- Tested with **Zen 1.23.4b** and **Arc 1.170**. On other Zen versions, `--apply` stops unless you
  pass `--allow-untested-zen`. Check the dry run first.

## Quick start

```bash
git clone https://github.com/Larry8668/arc-to-zen.git && cd arc-to-zen
./migrate.sh
```

## Step by step

```bash
./scripts/01_snapshot_arc.sh                    # copy Arc data -> snapshot/<timestamp>/
python3 -I scripts/02_build_plan.py             # -> out/plan.json, out/preview.txt, out/arc_bookmarks.html
#   optional: edit out/plan.json (rename containers, drop workspaces, reorder)
python3 -I scripts/03_apply_to_zen.py           # dry run -> out/zen-preview/
python3 -I scripts/03_apply_to_zen.py --apply   # Zen quit; backs up the Zen profile to backups/ first
```

`out/arc_bookmarks.html` is a standard bookmarks file of the same data, as a fallback
(Zen → Bookmarks → Import from HTML).

Arc profiles with no space (spaces you deleted) are skipped, even though Arc still keeps their data.

### Tweaks after importing (keeps changes you made in Zen)

```bash
python3 -I scripts/05_patch_zen.py --drop "Some Space"                  # dry run
python3 -I scripts/05_patch_zen.py --drop "Some Space" --apply
python3 -I scripts/05_patch_zen.py --colours --apply                    # re-apply Arc colours
```
This hides the container stripe on tabs. `--colours` re-applies Arc colours (overwriting any you picked in Zen). `--drop` removes a leftover
workspace or container.

### 4. History

```bash
python3 -I scripts/04_history_shim.py
```
This creates `~/Library/Application Support/Microsoft Edge Beta`, a folder Zen's built-in importer
recognises, containing clean copies of each Arc profile's history from the snapshot. The script
refuses to run if that folder already exists. Then in Zen: Settings → General → Import Browser Data →
**Microsoft Edge Beta** → pick an "Arc – …" profile → History. Repeat for each profile, then:
```bash
python3 -I scripts/04_history_shim.py --remove
```

### 5. Passwords (manual)

Arc's password export only covers the profile of the **space you're currently in**. For each space:
Arc → `arc://password-manager/settings` → *Export passwords*. Then in Zen: `about:logins` → ⋯ →
*Import from a File*. **Delete the CSVs afterwards** (`rm -P …`), because they are plain text.
Consider setting a Zen primary password too.

### 6. Extensions

Reinstall the Firefox versions from addons.mozilla.org. `snapshot/*/user-data/*/ext-manifests/`
lists what each Arc profile had.

## Undo

`./scripts/99_restore_zen_backup.sh` restores the Zen profile from the newest `backups/` tarball.
Backups made after you import passwords contain them (decryptable without a primary password).
Delete `backups/` once you're happy.

## How Zen stores this (1.23.x)

- `zen-sessions.jsonlz4` is the source of truth for the sidebar (`tabs`, `folders`, `groups`,
  `spaces`). Fallbacks live in `zen-sessions-backup/{clean,recovery}`, and Firefox's
  `sessionstore.jsonlz4` + `sessionstore-backups/recovery.*` hold a per-window copy. The scripts
  write all of them consistently.
- `.jsonlz4` files are `mozLz40\0` + a uint32 size + an LZ4 block (`scripts/mozlz4.py`, pure Python).
- A folder is a `folders[]` entry plus a `groups[]` entry with the same id, plus one `zenIsEmpty`
  about:blank tab listed in `emptyTabIds`. Top-level folder position = position of its tabs in `tabs[]`.
- An Essential is a pinned tab with `zenEssential: true`, `zenWorkspace: null` and
  `userContextId` set to its container.
- `zenDefaultUserContextId: true` hides the container colour stripe on a tab.
- The Zen profile is resolved from `installs.ini`, not by folder name, because fresh installs can
  have more than one "Default" profile folder.

## Tests

```bash
python3 -I -m unittest discover -s tests -v
```
The tests use synthetic Arc and Zen data in a temp directory. Real browser data is never read.

## Credits

Arc's data format notes from [olegfour3/arc2zen](https://github.com/olegfour3/arc2zen) were a
useful starting point.

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by The Browser Company (makers of
Arc) or the Zen Browser project. "Arc" and "Zen" are names of their respective owners and are used
here only to describe what the tool works with. The logo is original artwork made for this project
and doesn't use either browser's branding. The scripts only read your own local data. Use at
your own risk, and keep the backups the scripts create until you're happy with the result.
