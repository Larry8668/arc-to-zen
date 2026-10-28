#!/usr/bin/env python3 -I
"""Write out/plan.json into a Zen profile.

  python3 -I scripts/03_apply_to_zen.py            # dry run: writes to out/zen-preview/
  python3 -I scripts/03_apply_to_zen.py --apply    # writes to the Zen profile

Safety:
  * Never touches anything under ~/Library/Application Support/Arc (hard check).
  * Refuses to --apply while Zen is running.
  * Before --apply, tars the whole Zen profile to backups/ (restore = untar).
  * Profile is resolved from zen/installs.ini (the one Zen actually launches),
    not by guessing from folder names.

What it writes (all inside the Zen profile):
  containers.json                         + one container per Arc profile
  zen-sessions.jsonlz4                    workspaces, pinned tabs, folders, essentials
  zen-sessions-backup/clean.jsonlz4       same (so a fallback can't resurrect old state)
  zen-sessions-backup/recovery.baklz4     same
  sessionstore.jsonlz4 and sessionstore-backups/recovery.{jsonlz4,baklz4}
                                          window[0] tabs/folders/groups/spaces patched to match
The sidebar is REPLACED (Zen is a fresh install; the welcome folder goes away).
"""
import argparse
import colorsys
import configparser
import json
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mozlz4  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ZEN_ROOT = Path.home() / "Library" / "Application Support" / "zen"
ARC_ROOT = (Path.home() / "Library" / "Application Support" / "Arc").resolve()


def guard(path: Path) -> Path:
    p = Path(path).resolve()
    if p == ARC_ROOT or ARC_ROOT in p.parents:
        sys.exit(f"REFUSING: {p} is inside Arc's data directory")
    return p


def default_profile() -> Path:
    ini = configparser.ConfigParser(strict=False)
    ini.optionxform = str
    ini.read(ZEN_ROOT / "installs.ini")
    for sec in ini.sections():
        if ini[sec].get("Default"):
            return ZEN_ROOT / ini[sec]["Default"]
    sys.exit("Could not resolve Zen profile from installs.ini; pass --profile")


TESTED_ZEN_VERSIONS = {"1.23.4b"}  # session formats verified against these builds


def check_zen_version(allow_untested: bool) -> None:
    import plistlib
    try:
        with open("/Applications/Zen.app/Contents/Info.plist", "rb") as f:
            ver = plistlib.load(f)["CFBundleShortVersionString"]
    except OSError:
        sys.exit("Zen.app not found in /Applications")
    if ver in TESTED_ZEN_VERSIONS:
        return
    msg = (f"Zen {ver} is untested (tested: {', '.join(sorted(TESTED_ZEN_VERSIONS))}). "
           "Its session format may differ. Check the dry-run output, then pass --allow-untested-zen.")
    if not allow_untested:
        sys.exit(msg)
    print("WARNING:", msg)


def zen_running() -> bool:
    r = subprocess.run(["pgrep", "-f", "/Applications/Zen.app/Contents/MacOS/"], capture_output=True)
    return r.returncode == 0


# ---------- id helpers (formats copied from what Zen itself writes) ----------
_n = 0


def now_ms() -> int:
    return int(time.time() * 1000)


def sync_id() -> str:
    return f"{now_ms()}-{uuid.uuid4()}"


def folder_id() -> str:
    global _n
    _n += 1
    return f"{now_ms()}-{_n}"


ZEN_MIN_OPACITY, ZEN_MAX_OPACITY = 0.30, 0.80  # Zen's theme-picker opacity slider range


def theme_for(rgb, intensity=None, grain=None):
    """Arc background = colour x intensityFactor + grain noiseFactor.
    Zen theme     = colour x opacity (0.30-0.80) + texture."""
    if not rgb:
        return None
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
    opacity = 0.5 if intensity is None else ZEN_MIN_OPACITY + (ZEN_MAX_OPACITY - ZEN_MIN_OPACITY) * intensity
    return {"type": "gradient",
            "gradientColors": [{"c": list(rgb), "isCustom": False, "algorithm": "floating",
                                "isPrimary": True, "lightness": round(l * 100),
                                "position": {"x": 192, "y": 182}, "type": "undefined"}],
            "opacity": round(opacity, 3), "texture": round(grain or 0, 3)}


def make_tab(url, title, *, ws, ctx, group=None, essential=False, empty=False):
    entry = {"url": url, "triggeringPrincipal_base64": '{"3":{}}'}
    if title:
        entry["title"] = title
    tab = {
        "entries": [entry],
        "lastAccessed": now_ms(),
        "pinned": True,
        "hidden": False,
        "zenWorkspace": None if essential else ws,
        "zenSyncId": sync_id(),
        "zenEssential": essential,
        # True = "this tab is in its space's default container"; Zen then hides
        # the coloured container stripe on the tab (like tabs it creates itself).
        "zenDefaultUserContextId": True if ctx else None,
        "zenPinnedIcon": None,
        "zenIsEmpty": empty,
        "zenHasStaticIcon": False,
        "zenGlanceId": None,
        "zenIsGlance": False,
        "_zenPinnedInitialState": {"entry": dict(entry), "image": None},
        "zenLiveFolderItemId": None,
        "searchMode": None,
        "userContextId": ctx,
        "attributes": {},
        "index": 1,
        "image": None,
        "userTypedValue": "",
        "userTypedClear": 0,
    }
    if group:
        tab["groupId"] = group
    return tab


def emit(nodes, *, ws, ctx, tabs, folders, groups, parent=None):
    """Append nodes in sidebar order. Top-level folder position in Zen is the
    position of its tabs in `tabs`, so order here == order in the sidebar."""
    prev = None  # previous sibling, for nested folder placement
    for n in nodes:
        if n["type"] == "tab":
            t = make_tab(n["url"], n["title"], ws=ws, ctx=ctx, group=parent)
            tabs.append(t)
            prev = {"type": "tab", "id": t["zenSyncId"]}
            continue
        fid = folder_id()
        empty = make_tab("about:blank", "", ws=ws, ctx=ctx, group=fid, empty=True)
        tabs.append(empty)
        folders.append({
            "pinned": True, "essential": False, "splitViewGroup": False, "id": fid,
            "name": n["name"], "collapsed": True, "saveOnWindowClose": True,
            "parentId": parent, "prevSiblingInfo": prev or {"type": "start", "id": None},
            "emptyTabIds": [empty["zenSyncId"]], "userIcon": "", "isLiveFolder": False,
            "workspaceId": ws,
        })
        groups.append({"pinned": True, "splitView": False, "id": fid, "name": n["name"],
                       "color": "zen-workspace-color", "collapsed": True, "saveOnWindowClose": True})
        emit(n["items"], ws=ws, ctx=ctx, tabs=tabs, folders=folders, groups=groups, parent=fid)
        prev = {"type": "group", "id": fid}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", type=Path, default=None)
    ap.add_argument("--plan", type=Path, default=ROOT / "out" / "plan.json")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-untested-zen", action="store_true")
    args = ap.parse_args()

    if args.apply:
        check_zen_version(args.allow_untested_zen)
    profile = guard(args.profile or default_profile())
    if not (profile / "prefs.js").exists():
        sys.exit(f"Not a Zen profile (no prefs.js): {profile}")
    plan = json.loads(args.plan.read_text())
    print(f"Zen profile: {profile}\nPlan:        {args.plan}\nMode:        {'APPLY' if args.apply else 'dry run'}")

    if args.apply and zen_running():
        sys.exit("Zen is running. Quit it (Cmd+Q) and re-run.")

    # ---- containers ----
    cj = json.loads((profile / "containers.json").read_text())
    by_name = {i.get("name"): i for i in cj["identities"] if i.get("public") and i.get("name")}
    ctx_of = {}
    for c in plan["containers"]:
        ident = by_name.get(c["name"])
        if not ident:
            cj["lastUserContextId"] += 1
            ident = {"userContextId": cj["lastUserContextId"], "public": True, "icon": c["icon"],
                     "color": c["color"], "name": c["name"], "accessKey": ""}
            cj["identities"].append(ident)
        ctx_of[c["profile"]] = ident["userContextId"]

    # ---- sidebar ----
    old = mozlz4.read(profile / "zen-sessions.jsonlz4")
    old_uuids = [s["uuid"] for s in old.get("spaces", [])]
    tabs, folders, groups, spaces = [], [], [], []
    for i, w in enumerate(plan["workspaces"]):
        # reuse the existing workspace uuid for the first one so the
        # zen.workspaces.active pref keeps pointing at something real
        ws = old_uuids[i] if i < len(old_uuids) else "{" + str(uuid.uuid4()) + "}"
        ctx = ctx_of[w["profile"]]
        space = {"uuid": ws, "name": w["name"], "containerTabId": ctx, "hasCollapsedPinnedTabs": False}
        if w.get("icon"):
            space["icon"] = w["icon"]
        th = theme_for(w.get("rgb"), w.get("intensity"), w.get("grain"))
        if th:
            space["theme"] = th
        elif i < len(old.get("spaces", [])) and old["spaces"][i].get("theme"):
            space["theme"] = old["spaces"][i]["theme"]
        spaces.append(space)
        emit(w["items"], ws=ws, ctx=ctx, tabs=tabs, folders=folders, groups=groups)

    ess = []
    for prof, items in plan["essentials"].items():
        for n in items:
            ess.append(make_tab(n["url"], n["title"], ws=None, ctx=ctx_of[prof], essential=True))
    tabs = ess + tabs  # essentials first, as Zen stores them

    sidebar = dict(old)
    sidebar.update({"lastCollected": now_ms(), "tabs": tabs, "folders": folders,
                    "groups": groups, "spaces": spaces, "splitViewData": []})

    print(f"\n{len(spaces)} workspaces, {len(tabs) - len(ess)} sidebar tabs "
          f"(incl. {len(folders)} folder placeholders), {len(folders)} folders, {len(ess)} essentials, "
          f"{len(plan['containers'])} containers")
    write_profile(profile, sidebar, cj, apply=args.apply)


def build_outputs(profile: Path, sidebar: dict, containers: dict) -> dict:
    """Every file that carries sidebar state, made consistent with `sidebar`."""
    tabs, spaces = sidebar["tabs"], sidebar["spaces"]
    n_ess = sum(1 for t in tabs if t.get("zenEssential"))
    patched = {}
    for f in [profile / "sessionstore.jsonlz4",
              profile / "sessionstore-backups" / "recovery.jsonlz4",
              profile / "sessionstore-backups" / "recovery.baklz4"]:
        if not f.exists():
            continue
        d = mozlz4.read(f)
        if d.get("windows"):
            w0 = d["windows"][0]
            w0.update({"tabs": tabs, "folders": sidebar["folders"], "groups": sidebar["groups"],
                       "spaces": spaces, "splitViewData": sidebar.get("splitViewData", []),
                       "selected": n_ess + 1 if len(tabs) > n_ess else 1})
            if w0.get("activeZenSpace") not in {s["uuid"] for s in spaces}:
                w0["activeZenSpace"] = w0["workspaceID"] = spaces[0]["uuid"]
            for extra in d["windows"][1:]:
                extra["tabs"] = [t for t in extra.get("tabs", []) if not t.get("pinned")]
        patched[f] = d
    outputs = {profile / "containers.json": ("json", containers),
               profile / "zen-sessions.jsonlz4": ("lz4", sidebar),
               profile / "zen-sessions-backup" / "clean.jsonlz4": ("lz4", sidebar),
               profile / "zen-sessions-backup" / "recovery.baklz4": ("lz4", sidebar)}
    outputs.update({f: ("lz4", d) for f, d in patched.items()})
    return outputs


def write_profile(profile: Path, sidebar: dict, containers: dict, *, apply: bool) -> None:
    outputs = build_outputs(profile, sidebar, containers)
    if not apply:
        dest = guard(ROOT / "out" / "zen-preview")
        shutil.rmtree(dest, ignore_errors=True)
        for path, (kind, data) in outputs.items():
            p = dest / path.relative_to(profile)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.with_suffix(p.suffix + ".json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
            if kind == "lz4":
                mozlz4.write(p, data)
                assert mozlz4.read(p) == json.loads(json.dumps(data)), f"roundtrip failed {p}"
        print(f"Dry run: generated files in {dest} (nothing in Zen touched). Re-run with --apply.")
        return

    if zen_running():
        sys.exit("Zen is running. Quit it (Cmd+Q) and re-run.")
    backups = guard(ROOT / "backups")
    backups.mkdir(exist_ok=True)
    tarpath = backups / f"zen-profile-{datetime.now():%Y%m%d-%H%M%S}.tar.gz"
    with tarfile.open(tarpath, "w:gz") as tf:
        tf.add(profile, arcname=profile.name)
    tarpath.chmod(0o600)  # contains logins.json + key4.db: decryptable without a primary password
    tarpath.with_name(tarpath.name.removesuffix(".tar.gz") + ".txt").write_text(str(profile) + "\n")
    print(f"Backup of whole Zen profile: {tarpath}")

    for path, (kind, data) in outputs.items():
        guard(path)
        assert profile in path.parents, path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".arc2zen-tmp")
        if kind == "lz4":
            mozlz4.write(tmp, data)
            mozlz4.read(tmp)  # verify before replacing
        else:
            tmp.write_text(json.dumps(data))
        tmp.replace(path)
        print(f"  wrote {path.relative_to(profile)}")
    print("\nDone. Open Zen to check. To undo: scripts/99_restore_zen_backup.sh")


if __name__ == "__main__":
    main()
