"""End-to-end tests on synthetic data. Never touches real Arc/Zen data:
scripts are copied into a temp dir and pointed at a fake snapshot + fake Zen profile.

    python3 -I -m unittest discover -s tests -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import mozlz4  # noqa: E402


def item(id_, parent, children=(), title=None, data=None):
    return {"id": id_, "parentID": parent, "childrenIds": list(children), "title": title, "data": data or {}}


def tab(id_, parent, url, title=None):
    return item(id_, parent, title=title, data={"tab": {"savedURL": url, "savedTitle": title or url}})


def fake_arc_snapshot(root: Path) -> Path:
    snap = root / "snapshot"
    (snap / "user-data").mkdir(parents=True)
    p1 = {"custom": {"_0": {"directoryBasename": "Profile 1"}}}
    p2 = {"custom": {"_0": {"directoryBasename": "Profile 2"}}}
    items = [
        # Space "Home" (Default profile): tab, nested folders, split view, note
        item("home-pinned", None, ["t1", "f1", "sv", "note"], data={"itemContainer": {}}),
        tab("t1", "home-pinned", "https://a.example/", "A"),
        item("f1", "home-pinned", ["t2", "f2"], title="Outer", data={"list": {}}),
        tab("t2", "f1", "https://b.example/", "B"),
        item("f2", "f1", ["t3"], title="Inner", data={"list": {}}),
        tab("t3", "f2", "https://c.example/", "C"),
        item("sv", "home-pinned", ["t4", "t5"], data={"splitView": {}}),
        tab("t4", "sv", "https://d.example/", "D"),
        tab("t5", "sv", "https://e.example/", "E"),
        item("note", "home-pinned", title="My note", data={"arcDocument": {}}),
        # Two spaces on Profile 1
        item("w1-pinned", None, ["t6"], data={"itemContainer": {}}),
        tab("t6", "w1-pinned", "https://f.example/", "F"),
        item("w2-pinned", None, ["t7"], data={"itemContainer": {}}),
        tab("t7", "w2-pinned", "https://g.example/", "G"),
        # Favourites: Default + Profile 2 (which has no space -> dropped)
        item("fav-default", None, ["t8"]),
        tab("t8", "fav-default", "https://mail.example/", "Mail"),
        item("fav-p2", None, ["t9"]),
        tab("t9", "fav-p2", "https://orphan.example/", "Orphan"),
    ]
    sidebar = {"sidebar": {"containers": [{"global": {}}, {
        "items": items,
        "spaces": [
            {"id": "s1", "title": "Home", "profile": {"default": True},
             "newContainerIDs": [{"pinned": {}}, "home-pinned"],
             "customInfo": {"iconType": {"icon": "planet"}, "windowTheme": {"background": {"single": {"_0": {
                 "style": {"color": {"_0": {"blendedSingleColor": {"_0": {
                     "color": {"red": 0.5, "green": 0.4, "blue": 0.9},
                     "modifiers": {"intensityFactor": 0.6, "noiseFactor": 0.2}}}}}}}}}}}},
            {"id": "s2", "title": "Work A", "profile": p1, "newContainerIDs": [{"pinned": {}}, "w1-pinned"]},
            {"id": "s3", "title": "Work B", "profile": p1, "newContainerIDs": [{"pinned": {}}, "w2-pinned"]},
        ],
        "topAppsContainerIDs": [{"default": True}, "fav-default", p2, "fav-p2"],
    }]}}
    (snap / "StorableSidebar.json").write_text(json.dumps(sidebar))
    (snap / "user-data" / "Local State").write_text(json.dumps({"profile": {"info_cache": {
        "Default": {"name": "Person 1"}, "Profile 1": {"name": "Job"}, "Profile 2": {"name": "Old"}}}}))
    return snap


def fake_zen_profile(root: Path) -> Path:
    prof = root / "zen" / "Profiles" / "abc.Default (release)"
    (prof / "sessionstore-backups").mkdir(parents=True)
    (prof / "prefs.js").write_text("")
    (prof / "containers.json").write_text(json.dumps({"version": 8, "lastUserContextId": 5, "identities": [
        {"userContextId": 1, "public": True, "icon": "fingerprint", "color": "blue"}]}))
    space = {"uuid": "{11111111-1111-1111-1111-111111111111}", "name": "Space", "containerTabId": 0}
    mozlz4.write(prof / "zen-sessions.jsonlz4", {"tabs": [], "folders": [], "groups": [], "spaces": [space]})
    mozlz4.write(prof / "sessionstore.jsonlz4", {"windows": [{"tabs": [], "selected": 1}]})
    return prof


class MozLz4Test(unittest.TestCase):
    def test_decompress_overlapping_match(self):
        # token: 3 literals + match len 9 (5+4), offset 3 -> "abc" repeated 4x
        self.assertEqual(mozlz4.lz4_block_decompress(bytes([0x35]) + b"abc" + b"\x03\x00", 12), b"abc" * 4)

    def test_roundtrip_long(self):
        with tempfile.TemporaryDirectory() as td:
            obj = {"x": "y" * 5000, "n": list(range(300))}
            mozlz4.write(Path(td) / "f.jsonlz4", obj)
            self.assertEqual(mozlz4.read(Path(td) / "f.jsonlz4"), obj)


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.repo = self.td / "repo"
        shutil.copytree(REPO / "scripts", self.repo / "scripts")
        self.snap = fake_arc_snapshot(self.td)
        self.profile = fake_zen_profile(self.td)

    def tearDown(self):
        shutil.rmtree(self.td)

    def run_script(self, *args):
        r = subprocess.run([sys.executable, "-I", *map(str, args)], capture_output=True, text=True, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r.stdout

    def plan(self):
        self.run_script(self.repo / "scripts/02_build_plan.py", "--snapshot", self.snap, "--quiet")
        return json.loads((self.repo / "out/plan.json").read_text())

    def test_plan(self):
        plan = self.plan()
        ws = {w["name"]: w for w in plan["workspaces"]}
        self.assertEqual(list(ws), ["Home", "Work A", "Work B"])
        home = ws["Home"]["items"]
        self.assertEqual([n.get("title") or n.get("name") for n in home], ["A", "Outer", "D", "E"])
        self.assertEqual(home[1]["items"][1]["name"], "Inner")           # nested folder kept
        self.assertEqual(ws["Home"]["icon"], "🪐")
        self.assertEqual(ws["Home"]["intensity"], 0.6)
        # profile with two spaces -> one container named after the profile
        names = {c["profile"]: c["name"] for c in plan["containers"]}
        self.assertEqual(names, {"Default": "Home", "Profile 1": "Job"})
        self.assertNotIn("Profile 2", plan["essentials"])                 # spaceless profile dropped
        preview = (self.repo / "out/preview.txt").read_text()
        self.assertIn("arcDocument: 'My note'", preview)

    def test_apply_dry_run(self):
        self.plan()
        self.run_script(self.repo / "scripts/03_apply_to_zen.py", "--profile", self.profile)
        prev = self.repo / "out/zen-preview"
        side = mozlz4.read(prev / "zen-sessions.jsonlz4")
        self.assertEqual([s["name"] for s in side["spaces"]], ["Home", "Work A", "Work B"])
        self.assertEqual(side["spaces"][0]["uuid"], "{11111111-1111-1111-1111-111111111111}")  # reused
        self.assertEqual(side["spaces"][1]["containerTabId"], side["spaces"][2]["containerTabId"])
        folders = {f["name"]: f for f in side["folders"]}
        self.assertEqual(folders["Inner"]["parentId"], folders["Outer"]["id"])
        for f in side["folders"]:  # each folder's empty placeholder tab exists
            ids = {t["zenSyncId"] for t in side["tabs"] if t.get("zenIsEmpty")}
            self.assertTrue(set(f["emptyTabIds"]) <= ids)
        ess = [t for t in side["tabs"] if t["zenEssential"]]
        self.assertEqual([t["entries"][0]["url"] for t in ess], ["https://mail.example/"])
        self.assertTrue(all(t["zenDefaultUserContextId"] for t in side["tabs"]))
        self.assertEqual(mozlz4.read(prev / "zen-sessions-backup/clean.jsonlz4"), side)
        self.assertEqual(mozlz4.read(prev / "sessionstore.jsonlz4")["windows"][0]["tabs"], side["tabs"])
        # dry run must not have modified the fake profile
        self.assertEqual(mozlz4.read(self.profile / "zen-sessions.jsonlz4")["spaces"][0]["name"], "Space")

    def test_refuses_arc_dir(self):
        arc = Path.home() / "Library/Application Support/Arc"
        r = subprocess.run([sys.executable, "-I", str(self.repo / "scripts/03_apply_to_zen.py"),
                            "--profile", str(arc)], capture_output=True, text=True, cwd=self.repo)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("REFUSING", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
