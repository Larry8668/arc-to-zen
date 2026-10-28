#!/usr/bin/env python3 -I
"""Patch the CURRENT Zen state in place (keeps anything you changed in Zen
since the import), unlike 03 which regenerates the sidebar from the plan.

  python3 -I scripts/05_patch_zen.py --drop "Old Space"            # dry run
  python3 -I scripts/05_patch_zen.py --drop "Old Space" --apply

Does:
  * hides the coloured container stripe on tabs that are in their space's
    default container (sets zenDefaultUserContextId, as Zen does for its own tabs)
  * --colours: re-applies Arc colours (out/plan.json) to workspaces + containers,
    by name (overwrites colours you picked in Zen, so it's opt-in)
  * --drop NAME: removes that workspace, its tabs/folders, its container and the
    container's Essentials
Same safety as 03: Arc is never touched, refuses while Zen runs, full backup first.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mozlz4  # noqa: E402
from importlib import import_module  # noqa: E402

apply_mod = import_module("03_apply_to_zen")
guard, default_profile, theme_for, write_profile = (
    apply_mod.guard, apply_mod.default_profile, apply_mod.theme_for, apply_mod.write_profile)
ROOT = apply_mod.ROOT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", type=Path, default=None)
    ap.add_argument("--plan", type=Path, default=ROOT / "out" / "plan.json")
    ap.add_argument("--drop", action="append", default=[], help="workspace/container name to remove")
    ap.add_argument("--colours", "--colors", action="store_true",
                    help="re-apply Arc colours (overwrites colours set in Zen)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-untested-zen", action="store_true")
    args = ap.parse_args()
    if args.apply:
        apply_mod.check_zen_version(args.allow_untested_zen)

    profile = guard(args.profile or default_profile())
    plan = json.loads(args.plan.read_text())
    sidebar = mozlz4.read(profile / "zen-sessions.jsonlz4")
    cj = json.loads((profile / "containers.json").read_text())
    print(f"Zen profile: {profile}\nMode: {'APPLY' if args.apply else 'dry run'}\n")

    # ---- drop workspaces / containers ----
    drop = set(args.drop)
    drop_ws = {s["uuid"] for s in sidebar["spaces"] if s.get("name") in drop}
    drop_ctx = {i["userContextId"] for i in cj["identities"] if i.get("public") and i.get("name") in drop}
    # a container still used by a kept workspace must stay
    drop_ctx -= {s.get("containerTabId") for s in sidebar["spaces"] if s["uuid"] not in drop_ws}
    before = len(sidebar["tabs"])
    sidebar["spaces"] = [s for s in sidebar["spaces"] if s["uuid"] not in drop_ws]
    sidebar["tabs"] = [t for t in sidebar["tabs"]
                       if t.get("zenWorkspace") not in drop_ws
                       and not (t.get("zenEssential") and t.get("userContextId") in drop_ctx)]
    dropped_folders = {f["id"] for f in sidebar.get("folders", []) if f.get("workspaceId") in drop_ws}
    sidebar["folders"] = [f for f in sidebar.get("folders", []) if f["id"] not in dropped_folders]
    sidebar["groups"] = [g for g in sidebar.get("groups", []) if g["id"] not in dropped_folders]
    cj["identities"] = [i for i in cj["identities"] if i["userContextId"] not in drop_ctx]
    if drop:
        print(f"drop {sorted(drop)}: {len(drop_ws)} workspace(s), {len(drop_ctx)} container(s), "
              f"{before - len(sidebar['tabs'])} tab(s)/essential(s), {len(dropped_folders)} folder(s)")
    if not sidebar["spaces"]:
        sys.exit("Refusing: that would remove every workspace")

    # ---- hide container stripe on default-container tabs ----
    ws_ctx = {s["uuid"]: s.get("containerTabId", 0) for s in sidebar["spaces"]}
    fixed = 0
    for t in sidebar["tabs"]:
        ctx = t.get("userContextId", 0)
        default = (ctx and t.get("zenEssential")) or (ctx and ws_ctx.get(t.get("zenWorkspace")) == ctx)
        if default and not t.get("zenDefaultUserContextId"):
            t["zenDefaultUserContextId"] = True
            fixed += 1
    print(f"container stripe hidden on {fixed} tab(s)")

    # ---- colours from the Arc plan (opt-in) ----
    if args.colours:
        by_name = {w["name"]: w for w in plan["workspaces"]}
        for s in sidebar["spaces"]:
            w = by_name.get(s.get("name"))
            th = w and theme_for(w.get("rgb"), w.get("intensity"), w.get("grain"))
            if th:
                s["theme"] = th
                print(f"theme  {s['name']:10} rgb={w['rgb']} opacity={th['opacity']} texture={th['texture']}")
        cplan = {c["name"]: c for c in plan["containers"]}
        for i in cj["identities"]:
            c = cplan.get(i.get("name"))
            if c and i.get("color") != c["color"]:
                print(f"container {i['name']:10} colour {i.get('color')} -> {c['color']}")
                i["color"] = c["color"]

    write_profile(profile, sidebar, cj, apply=args.apply)


if __name__ == "__main__":
    main()
