#!/usr/bin/env python3 -I
"""Expose Arc *snapshot* history to Zen's built-in Chromium importer.

A "shim" is a small adapter: Zen has no "Arc" entry in Settings -> Import,
but it does read "~/Library/Application Support/Microsoft Edge Beta" as a
Chromium browser. If that folder doesn't exist, we create it from the
snapshot (never from Arc), with clean single-file History DBs (VACUUM INTO),
and profile names relabelled "Arc – <name>".

  python3 -I scripts/04_history_shim.py           # create shim (migrated profiles only)
  python3 -I scripts/04_history_shim.py --all     # include profiles with no space too
  python3 -I scripts/04_history_shim.py --remove  # delete it again

Then: Zen -> Settings -> General -> Import Browser Data -> "Microsoft Edge Beta"
      -> pick "Arc – …" profile -> tick History -> Import. Repeat per profile.

Zen's importer caps history at 2000 URLs per profile and 180 days, unless you
first change two prefs in about:config (printed when the shim is created).
"""
import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIM = Path.home() / "Library" / "Application Support" / "Microsoft Edge Beta"
MARKER = ".created-by-arc-to-zen"


def remove():
    if not SHIM.exists():
        print("No shim present."); return
    if not (SHIM / MARKER).exists():
        sys.exit(f"REFUSING: {SHIM} exists but wasn't created by this tool")
    shutil.rmtree(SHIM)
    print(f"Removed {SHIM}")


def clean_copy(src: Path, dst: Path, journal: Path):
    """Copy db+journal to a temp dir, let SQLite settle it there, VACUUM INTO dst."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / src.name
        shutil.copy2(src, tmp)
        if journal.exists():
            shutil.copy2(journal, Path(td) / journal.name)
        con = sqlite3.connect(tmp)
        con.execute("VACUUM INTO ?", (str(dst),))
        con.close()


def oldest_visit_days(db: Path) -> int:
    """Age in days of the oldest visit (Chrome time = µs since 1601-01-01)."""
    import time
    us = sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute(
        "select min(last_visit_time) from urls where last_visit_time > 0").fetchone()[0]
    if not us:
        return 0
    return int((time.time() - (us / 1e6 - 11644473600)) / 86400) + 1


def create(snapshot: Path, include_all: bool):
    if SHIM.exists():
        if (SHIM / MARKER).exists():
            sys.exit(f"Shim already exists at {SHIM}. Use --remove first.")
        sys.exit(f"REFUSING: {SHIM} already exists and is not ours")
    ud = snapshot / "user-data"
    ls = json.loads((ud / "Local State").read_text())
    plan = json.loads((ROOT / "out" / "plan.json").read_text())
    label = {c["profile"]: c["name"] for c in plan["containers"]}
    cache = ls["profile"]["info_cache"]
    SHIM.mkdir()
    (SHIM / MARKER).write_text("temporary import shim; safe to delete\n")
    exposed, max_urls, max_days = {}, 0, 0
    for prof, info in cache.items():
        src = ud / prof / "History"
        if not src.exists():
            continue
        if prof not in label and not include_all:
            print(f"  {prof:10} skipped (no space in Arc; use --all to include)")
            continue
        info["name"] = f"Arc – {label.get(prof, info.get('name', prof))}"
        (SHIM / prof).mkdir()
        clean_copy(src, SHIM / prof / "History", ud / prof / "History-journal")
        db = SHIM / prof / "History"
        n = sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute("select count(*) from urls").fetchone()[0]
        days = oldest_visit_days(db)
        max_urls, max_days = max(max_urls, n), max(max_days, days)
        exposed[prof] = info
        print(f"  {prof:10} -> {info['name']!r}: {n} urls, oldest {days} days ago")
    (SHIM / "Local State").write_text(json.dumps({"profile": {"info_cache": exposed}}))
    print(f"\nShim ready at {SHIM}")
    if max_urls > 2000 or max_days > 180:
        print("\nZen's importer only takes the newest 2000 URLs per profile from the last 180 days.\n"
              "To import everything, first set these in Zen's about:config:\n"
              "  browser.migrate.chrome.history.limit     -> 0\n"
              f"  browser.migrate.history.maxAgeInDays     -> {max(max_days, 180)}\n"
              "(You can reset both afterwards.)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--all", action="store_true", help="include Arc profiles that have no space")
    ap.add_argument("--snapshot", type=Path, default=ROOT / "snapshot" / "latest")
    a = ap.parse_args()
    remove() if a.remove else create(a.snapshot, a.all)
