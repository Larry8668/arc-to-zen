#!/usr/bin/env python3 -I
"""Turn an Arc snapshot into a browser-neutral, hand-editable plan.

Reads ONLY from snapshot/<ts>/ (made by 01_snapshot_arc.sh) — never from Arc.

Outputs (in out/):
  plan.json           containers / workspaces / pinned tree / essentials
  preview.txt         human-readable view of the plan
  arc_bookmarks.html  Netscape bookmarks file of the same data (fallback:
                      Zen -> Import from HTML gives you plain bookmarks too)

Mapping:
  Arc profile     -> Zen container (separate cookie jar, like Arc profiles)
  Arc space       -> Zen workspace, default container = space's profile
  pinned tabs     -> pinned tabs in that workspace (folders preserved)
  favourites      -> Zen Essentials for that profile's container
"""
import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Arc's SF-symbol space icons -> emoji (Zen workspace icons are emoji)
ICON_MAP = {"planet": "🪐", "star": "⭐", "heart": "❤️", "briefcase": "💼",
            "house": "🏠", "book": "📖", "graduationcap": "🎓", "folder": "📁"}
CONTAINER_COLORS = ["blue", "orange", "green", "purple", "turquoise", "pink", "yellow", "red"]
CONTAINER_ICONS = ["fingerprint", "briefcase", "circle", "tree", "pet", "gift", "fruit", "food"]
# Firefox's fixed container palette (hex from Firefox's contextual identity CSS)
FF_COLORS = {"blue": (55, 173, 255), "turquoise": (0, 199, 154), "green": (81, 205, 0),
             "yellow": (255, 203, 0), "orange": (255, 159, 0), "red": (255, 97, 61),
             "pink": (255, 75, 218), "purple": (175, 81, 245)}


def nearest_container_color(rgb):
    """Closest Firefox container colour by hue (Arc colours are pastel, so hue is what matters)."""
    import colorsys
    h = colorsys.rgb_to_hsv(*(v / 255 for v in rgb))[0]
    def dist(c):
        hc = colorsys.rgb_to_hsv(*(v / 255 for v in FF_COLORS[c]))[0]
        d = abs(h - hc)
        return min(d, 1 - d)
    return min(FF_COLORS, key=dist)


def find_modifiers(theme: dict) -> dict:
    """Arc's background intensity/grain, e.g. {"intensityFactor": 0.7, "noiseFactor": 0.65}."""
    def walk(o):
        if isinstance(o, dict):
            if "intensityFactor" in o or "noiseFactor" in o:
                return o
            for v in o.values():
                r = walk(v)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = walk(v)
                if r:
                    return r
        return None
    return walk(theme.get("background", {})) or {}


def profile_key(p: dict) -> str:
    if not p or "default" in p:
        return "Default"
    for v in (p.get("custom") or {}).values():
        if isinstance(v, dict) and v.get("directoryBasename"):
            return v["directoryBasename"]
    return "Default"


def pairs(lst):
    """Arc stores maps as [marker, value, marker, value, ...]."""
    for i in range(0, len(lst) - 1):
        if isinstance(lst[i], dict):
            yield lst[i], lst[i + 1]


def find_rgb(obj, prefer=("background", "primaryColorPalette")):
    """First {red,green,blue} dict found in Arc's theme blob, as 0-255 ints."""
    def walk(o):
        if isinstance(o, dict):
            if {"red", "green", "blue"} <= o.keys():
                return [max(0, min(255, round(float(o[k]) * 255))) for k in ("red", "green", "blue")]
            for v in o.values():
                r = walk(v)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = walk(v)
                if r:
                    return r
        return None
    for k in prefer:
        if isinstance(obj, dict) and k in obj:
            r = walk(obj[k])
            if r:
                return r
    return walk(obj)


SKIPPED = []  # (kind, title) of Arc items with no Zen equivalent, reported in preview


def build_tree(items: dict, parent_id: str) -> list:
    out = []
    for cid in (items.get(parent_id) or {}).get("childrenIds", []):
        it = items.get(cid)
        if not it:
            continue
        data = it.get("data") or {}
        tab = data.get("tab")
        if tab:
            url = tab.get("savedURL") or ""
            if not url:
                continue
            out.append({"type": "tab", "title": it.get("title") or tab.get("savedTitle") or url, "url": url})
        elif "list" in data or (not data and it.get("title")):
            out.append({"type": "folder", "name": it.get("title") or "Folder", "items": build_tree(items, cid)})
        elif "splitView" in data:
            # Zen split views aren't persisted as pinned items; keep the tabs, in order
            out.extend(n for n in build_tree(items, cid) if n["type"] == "tab")
        else:
            SKIPPED.append((next(iter(data), "unknown"), it.get("title") or ""))
    return out


def count(nodes):
    t = f = 0
    for n in nodes:
        if n["type"] == "tab":
            t += 1
        else:
            f += 1
            a, b = count(n["items"])
            t += a; f += b
    return t, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=str(ROOT / "snapshot" / "latest"))
    ap.add_argument("--include-unpinned", action="store_true",
                    help="also bring Arc's unpinned 'today' tabs as pinned tabs")
    ap.add_argument("--out", default=str(ROOT / "out"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    snap = Path(args.snapshot)

    sidebar = json.loads((snap / "StorableSidebar.json").read_text())
    local_state = json.loads((snap / "user-data" / "Local State").read_text())
    profile_names = {k: v.get("name", k) for k, v in local_state["profile"]["info_cache"].items()}

    container = next(c for c in sidebar["sidebar"]["containers"]
                     if isinstance(c, dict) and "items" in c and "spaces" in c)
    items = {i["id"]: i for i in container["items"] if isinstance(i, dict)}

    workspaces = []
    for s in container["spaces"]:
        if not isinstance(s, dict):
            continue
        tree = []
        for marker, cid in pairs(s.get("newContainerIDs", [])):
            if "pinned" in marker or (args.include_unpinned and "unpinned" in marker):
                tree += build_tree(items, str(cid))
        ci = s.get("customInfo") or {}
        mods = find_modifiers(ci.get("windowTheme") or {})
        workspaces.append({
            "name": s.get("title") or "Space",
            "profile": profile_key(s.get("profile")),
            "icon": ICON_MAP.get(((ci.get("iconType") or {}).get("icon") or ""), ""),
            "rgb": find_rgb(ci.get("windowTheme") or {}),
            "intensity": mods.get("intensityFactor"),
            "grain": mods.get("noiseFactor"),
            "items": tree,
        })

    essentials = {}
    for marker, cid in pairs(container.get("topAppsContainerIDs", [])):
        tabs = [n for n in build_tree(items, str(cid)) if n["type"] == "tab"]
        if tabs:
            essentials[profile_key(marker)] = tabs

    # Only profiles that back a visible Arc space are migrated. Profiles with
    # no space (e.g. spaces you deleted) keep leftover favourites in Arc's
    # data, but they aren't visible in Arc, so they're dropped here too.
    spaced = {w["profile"] for w in workspaces}
    dropped = sorted(p for p in set(essentials) | set(profile_names) if p not in spaced)
    essentials = {p: t for p, t in essentials.items() if p in spaced}

    # One container per migrated profile. Name it after its space when it has
    # exactly one (e.g. Arc's "Your Chromium" profile -> "Personal"); colour
    # = nearest Firefox container colour to the space's Arc colour.
    containers = []
    for i, prof in enumerate(sorted(spaced, key=lambda p: (p != "Default", p))):
        ws = [w for w in workspaces if w["profile"] == prof]
        containers.append({
            "profile": prof,
            "name": ws[0]["name"] if len(ws) == 1 else profile_names[prof],
            "color": nearest_container_color(ws[0]["rgb"]) if ws[0].get("rgb")
                     else CONTAINER_COLORS[i % len(CONTAINER_COLORS)],
            "icon": CONTAINER_ICONS[i % len(CONTAINER_ICONS)],
        })

    plan = {"source_snapshot": str(snap.resolve()), "containers": containers,
            "workspaces": workspaces, "essentials": essentials}

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False))

    # preview
    cname = {c["profile"]: c["name"] for c in containers}
    lines = [f"SKIPPED Arc profiles without a space: "
             f"{', '.join(f'{p} ({profile_names[p]})' for p in dropped) or 'none'}\n",
             "CONTAINERS (Arc profile -> Zen container)"]
    lines += [f"  {c['profile']:10} -> {c['name']!r} ({c['color']}/{c['icon']})" for c in containers]

    def dump(nodes, ind):
        for n in nodes:
            if n["type"] == "tab":
                lines.append(f"{ind}- {n['title'][:60]}  <{n['url'][:70]}>")
            else:
                lines.append(f"{ind}[{n['name']}]")
                dump(n["items"], ind + "    ")
    for w in workspaces:
        t, f = count(w["items"])
        lines.append(f"\nWORKSPACE {w['icon']} {w['name']!r}  container={cname[w['profile']]!r}  "
                     f"rgb={w['rgb']} intensity={w.get('intensity')} grain={w.get('grain')}  "
                     f"({t} tabs, {f} folders)")
        dump(w["items"], "  ")
    for prof, tabs in essentials.items():
        lines.append(f"\nESSENTIALS for container {cname[prof]!r} ({len(tabs)})")
        dump(tabs, "  ")
    if SKIPPED:
        lines.append(f"\nSKIPPED Arc items with no Zen equivalent ({len(SKIPPED)}):")
        lines += [f"  {kind}: {title!r}" for kind, title in SKIPPED]
    (out / "preview.txt").write_text("\n".join(lines) + "\n")

    # fallback HTML bookmarks
    e = lambda s: html.escape(s or "", quote=True)
    hb = ["<!DOCTYPE NETSCAPE-Bookmark-file-1>",
          '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
          "<TITLE>Bookmarks</TITLE>", "<H1>Arc export</H1>", "<DL><p>"]

    def hdump(nodes, ind):
        for n in nodes:
            if n["type"] == "tab":
                hb.append(f'{ind}<DT><A HREF="{e(n["url"])}">{e(n["title"])}</A>')
            else:
                hb.append(f"{ind}<DT><H3>{e(n['name'])}</H3>")
                hb.append(f"{ind}<DL><p>")
                hdump(n["items"], ind + "    ")
                hb.append(f"{ind}</DL><p>")
    hdump([{"type": "folder", "name": f"Arc – {w['name']}", "items": w["items"]} for w in workspaces if w["items"]]
          + [{"type": "folder", "name": f"Arc Favourites – {cname[p]}", "items": t} for p, t in essentials.items()], "    ")
    hb.append("</DL><p>")
    (out / "arc_bookmarks.html").write_text("\n".join(hb) + "\n")

    if not args.quiet:
        print((out / "preview.txt").read_text())
    print(f"Wrote {out/'plan.json'}, {out/'preview.txt'}, {out/'arc_bookmarks.html'}")


if __name__ == "__main__":
    main()
