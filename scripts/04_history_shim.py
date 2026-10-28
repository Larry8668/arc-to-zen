#!/usr/bin/env python3 -I
"""Expose Arc *snapshot* history to Zen's built-in Chromium importer.

Zen has no "Arc" entry in Settings -> Import, but it does read
"~/Library/Application Support/Microsoft Edge Beta" as a Chromium browser.
That folder doesn't exist on this Mac, so we create it from the snapshot
(never from Arc), with clean single-file History DBs (VACUUM INTO), and
profile names relabelled "Arc – <name>".

  python3 -I scripts/04_history_shim.py           # create shim
  python3 -I scripts/04_history_shim.py --remove  # delete it again

Then: Zen -> Settings -> General -> Import Browser Data -> "Microsoft Edge Beta"
      -> pick "Arc – …" profile -> tick History -> Import. Repeat per profile.
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


def create(snapshot: Path):
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
    for prof, info in cache.items():
        src = ud / prof / "History"
        if not src.exists():
            continue
        info["name"] = f"Arc – {label.get(prof, info.get('name', prof))}"
        (SHIM / prof).mkdir()
        clean_copy(src, SHIM / prof / "History", ud / prof / "History-journal")
        n = sqlite3.connect(f"file:{SHIM / prof / 'History'}?mode=ro", uri=True).execute(
            "select count(*) from urls").fetchone()[0]
        print(f"  {prof:10} -> {info['name']!r}: {n} urls")
    (SHIM / "Local State").write_text(json.dumps({"profile": {"info_cache": cache}}))
    print(f"Shim ready at {SHIM}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--snapshot", type=Path, default=ROOT / "snapshot" / "latest")
    a = ap.parse_args()
    remove() if a.remove else create(a.snapshot)
