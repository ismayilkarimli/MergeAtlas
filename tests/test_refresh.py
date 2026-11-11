"""Refresh: what happens to a published map when its PR moves, as when a stack is rebased.

Run from the repository root:
    python3 -m unittest discover -s tests

A map is regenerated only when the user runs MergeAtlas, and the script handles every case it can alone:
    same head commit                 -> the map stands; fetch prints its URL
    same changes on a new commit     -> the script shifts links into the PR's own files and republishes
    changes that differ              -> only the cards whose changes differ, or whose links broke, go back to the agent

Code outside a PR's own files is pinned to the commit the PR was built on, so a rebase leaves those links alone.

The interface under test, in skills/mergeatlas/scripts/mergeatlas.py:
    fingerprint(card, rows)             -> a hash of the card's added and removed lines only
    patch_id(rows)                      -> a hash of every file's added and removed lines
    line_map(old, new)                  -> {old line number: new line number} for lines both versions keep
    shift_links(data, maps)             -> (data with code links moved by maps[path], [owners of links that broke])
    built_on(merge_base, pinned, head, is_ancestor)
                                        -> the commit a PR's own changes start from
    redo_plan(cards, old_rows, new_rows, old_paths, new_paths, broken)
                                        -> {redo, keep, added, gone, fix}
    refresh_work(map_id, pr, diff, built)
                                        -> (status, plan): status is new, same-head, refreshed or partial
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_stack_detection import mergeatlas


def diff_of(path, hunks):
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n" + "".join(hunks)


ONE = diff_of("cfg.txt", ["@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"])
ONE_MOVED = diff_of("cfg.txt", ["@@ -4,3 +4,3 @@ header\n x\n-b\n+B\n y\n"])
OTHER = diff_of("cfg.txt", ["@@ -1,3 +1,3 @@\n a\n-b\n+C\n c\n"])
CARD = {"id": "cfg", "paths": ["cfg.txt"]}


class Fingerprints(unittest.TestCase):
    def test_context_and_line_numbers_do_not_count(self):
        self.assertEqual(mergeatlas.fingerprint(CARD, mergeatlas.diff_rows(ONE)),
                         mergeatlas.fingerprint(CARD, mergeatlas.diff_rows(ONE_MOVED)))

    def test_a_different_change_differs(self):
        self.assertNotEqual(mergeatlas.fingerprint(CARD, mergeatlas.diff_rows(ONE)),
                            mergeatlas.fingerprint(CARD, mergeatlas.diff_rows(OTHER)))

    def test_patch_id_covers_every_file(self):
        two = ONE + diff_of("b.txt", ["@@ -1 +1 @@\n-x\n+y\n"])
        self.assertEqual(mergeatlas.patch_id(mergeatlas.diff_rows(ONE)), mergeatlas.patch_id(mergeatlas.diff_rows(ONE_MOVED)))
        self.assertNotEqual(mergeatlas.patch_id(mergeatlas.diff_rows(ONE)), mergeatlas.patch_id(mergeatlas.diff_rows(two)))
        self.assertNotEqual(mergeatlas.patch_id(mergeatlas.diff_rows(ONE)), mergeatlas.patch_id(mergeatlas.diff_rows(OTHER)))


class LineMap(unittest.TestCase):
    def test_lines_kept_follow_an_insertion_above(self):
        self.assertEqual(mergeatlas.line_map(["a", "b", "c"], ["new", "a", "b", "c"]), {1: 2, 2: 3, 3: 4})

    def test_a_removed_line_has_no_place(self):
        self.assertNotIn(2, mergeatlas.line_map(["a", "b", "c"], ["a", "c"]))


def map_data():
    return {
        "background": "Uses [the reader](app.py#L3).", "problem": "p", "solution": "[s](i1)",
        "cards": [
            {"id": "cfg", "paths": ["cfg.txt"], "summary": "Holds [a setting](cfg.txt#L2).",
             "changes": [{"problem": "p", "change": "Sets [it](cfg.txt#L2-L3) for [the reader](app.py#L3).", "result": "r"}]},
            {"id": "doc", "paths": ["doc.md"], "summary": "Names [the file](doc.md#L1).", "changes": []},
        ],
        "edges": [{"from": "cfg", "to": "doc", "flow": "Read at [x](cfg.txt#L3).", "connection_at": "cfg.txt#L2-L3"}],
        "intents": [{"id": "i1", "outcome": "Reads [y](cfg.txt#L1)."}],
    }


class ShiftLinks(unittest.TestCase):
    def test_links_move_with_their_lines_everywhere_in_the_map(self):
        data, broken = mergeatlas.shift_links(map_data(), {"cfg.txt": {1: 2, 2: 3, 3: 4}})
        self.assertEqual(broken, [])
        self.assertEqual(data["cards"][0]["summary"], "Holds [a setting](cfg.txt#L3).")
        self.assertEqual(data["cards"][0]["changes"][0]["change"], "Sets [it](cfg.txt#L3-L4) for [the reader](app.py#L3).")
        self.assertEqual(data["edges"][0]["connection_at"], "cfg.txt#L3-L4")
        self.assertEqual(data["edges"][0]["flow"], "Read at [x](cfg.txt#L4).")
        self.assertEqual(data["intents"][0]["outcome"], "Reads [y](cfg.txt#L2).")

    def test_paths_with_no_map_stay_pinned(self):
        data, _ = mergeatlas.shift_links(map_data(), {"cfg.txt": {1: 2, 2: 3, 3: 4}})
        self.assertEqual(data["background"], "Uses [the reader](app.py#L3).")

    def test_a_link_whose_lines_are_gone_breaks_and_names_its_owner(self):
        data, broken = mergeatlas.shift_links(map_data(), {"cfg.txt": {1: 1, 3: 2}})
        self.assertEqual(data["cards"][0]["summary"], "Holds [a setting](cfg.txt#L2).")
        self.assertEqual(broken, ["card cfg", "arrow cfg -> doc"])
        self.assertEqual(data["edges"][0]["flow"], "Read at [x](cfg.txt#L2).")

    def test_a_range_that_comes_apart_breaks(self):
        _, broken = mergeatlas.shift_links(map_data(), {"cfg.txt": {1: 1, 2: 2, 3: 5}})
        self.assertIn("card cfg", broken)

    def test_story_and_intents_name_themselves(self):
        _, broken = mergeatlas.shift_links(map_data(), {"app.py": {}, "cfg.txt": {1: 1, 2: 2, 3: 3}})
        self.assertEqual(broken, ["story", "card cfg"])
        _, broken = mergeatlas.shift_links(map_data(), {"cfg.txt": {2: 2, 3: 3}})
        self.assertEqual(broken, ["intent i1"])


class BuiltOn(unittest.TestCase):
    def ancestors(self, pairs):
        return lambda a, b: a == b or (a, b) in pairs

    def test_a_first_map_starts_from_the_merge_base(self):
        self.assertEqual(mergeatlas.built_on("m", None, "head", self.ancestors(set())), "m")

    def test_a_rebase_onto_the_parent_starts_from_the_new_merge_base(self):
        self.assertEqual(mergeatlas.built_on("p2", "p1", "head", self.ancestors({("p1", "p2"), ("p1", "head")})), "p2")

    def test_a_squash_merged_parent_leaves_the_child_on_the_parents_old_head(self):
        # the parent's branch was squashed into main: the child, not rebased, still holds the parent's old head,
        # while its merge base with main is the older main commit the parent started from
        self.assertEqual(mergeatlas.built_on("main0", "p1", "head", self.ancestors({("main0", "p1"), ("p1", "head")})), "p1")


class RedoPlan(unittest.TestCase):
    def test_only_cards_whose_changes_differ_go_back(self):
        cards = [CARD, {"id": "b", "paths": ["b.txt"]}]
        b = diff_of("b.txt", ["@@ -1 +1 @@\n-x\n+y\n"])
        plan = mergeatlas.redo_plan(cards, mergeatlas.diff_rows(ONE + b), mergeatlas.diff_rows(OTHER + b),
                                    ["cfg.txt", "b.txt"], ["cfg.txt", "b.txt", "new.txt"], [])
        self.assertEqual(plan, {"redo": ["cfg"], "keep": ["b"], "added": ["new.txt"], "gone": [], "fix": []})

    def test_cards_with_broken_links_go_back_and_the_rest_are_listed_to_fix(self):
        plan = mergeatlas.redo_plan([CARD], mergeatlas.diff_rows(ONE), mergeatlas.diff_rows(ONE_MOVED),
                                    ["cfg.txt", "old.txt"], ["cfg.txt"], ["card cfg", "story", "arrow cfg -> doc"])
        self.assertEqual(plan, {"redo": ["cfg"], "keep": [], "added": [], "gone": ["old.txt"],
                                "fix": ["story", "arrow cfg -> doc"]})


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


class RefreshWork(unittest.TestCase):
    """A real repository: app.py sits outside the PR, which changes cfg.txt."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")
        self.base = self.commit({"app.py": "import os\n\ndef read():\n    return os.environ\n", "cfg.txt": "a\nb\nc\n"}, "base")
        self.head = self.commit({"cfg.txt": "a\nB\nc\n"}, "change b")
        home = self.tmp / "home"
        patches = {"HOME": home, "WORK": home / "work", "DATA": home / "data"}
        self.patches = [mock.patch.object(mergeatlas, k, v) for k, v in patches.items()]
        self.patches.append(mock.patch.object(mergeatlas, "serve", lambda: None))
        for p in self.patches:
            p.start()
        self.cwd = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self.cwd)
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp)

    def commit(self, files, message):
        for path, text in files.items():
            (self.repo / path).write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)
        return git(self.repo, "rev-parse", "HEAD")

    def pr(self, head, base):
        diff = git(self.repo, "diff", base, head) + "\n"
        return {
            "number": 7, "title": "Change b", "body": "", "additions": 1, "deletions": 1,
            "files": [{"path": "cfg.txt", "additions": 1, "deletions": 1}], "headRefName": "change-b",
            "headRefOid": head, "baseRefName": "main", "url": "https://github.com/o/r/pull/7", "issues": [], "stack": None,
        }, diff

    def first_map(self):
        pr, diff = self.pr(self.head, self.base)
        status, _ = mergeatlas.refresh_work("o-r-7", pr, diff, self.base)
        self.assertEqual(status, "new")
        line = "+B"
        (mergeatlas.WORK / "o-r-7.input.json").write_text(json.dumps({
            "background": "The app reads its settings [from the environment](app.py#L3-L4).",
            "problem": "b is lower case.", "solution": "[Capitalise b](i1).",
            "cards": [{"id": "cfg", "kind": "config", "title": "cfg.txt", "paths": ["cfg.txt"],
                       "summary": "Holds [the setting](cfg.txt#L2).", "bullets": ["b"],
                       "changes": [{"intent": "i1", "problem": "b is lower case.",
                                    "change": "This PR writes [B](cfg.txt#L2), which [read](app.py#L3) returns.",
                                    "result": "B is upper case.", "snippets": [line]}]}],
            "edges": [], "intents": [{"id": "i1", "title": "Capitalise b", "outcome": "After this PR, cfg.txt holds B."}],
        }))
        mergeatlas.publish("o-r-7")

    def published(self):
        return json.loads((mergeatlas.DATA / "o-r-7.json").read_text())

    def saved_input(self):
        return json.loads((mergeatlas.WORK / "o-r-7.input.json").read_text())

    def test_a_first_fetch_pins_code_outside_the_pr_to_the_commit_it_was_built_on(self):
        self.first_map()
        self.assertEqual(self.published()["pr"]["blob"], f"https://github.com/o/r/blob/{self.base}/")
        self.assertEqual(self.published()["pr"]["pinned"], {"commit": self.base, "base": "main", "below": None})

    def test_the_same_head_leaves_the_map_alone(self):
        self.first_map()
        before = self.published()
        pr, diff = self.pr(self.head, self.base)
        self.assertEqual(mergeatlas.refresh_work("o-r-7", pr, diff, self.base)[0], "same-head")
        self.assertEqual(self.published(), before)

    def test_the_same_changes_on_a_new_commit_are_refreshed_by_the_script(self):
        self.first_map()
        git(self.repo, "checkout", "-q", self.base)
        base2 = self.commit({"app.py": "# settings\nimport os\n\ndef read():\n    return os.environ\n",
                             "cfg.txt": "top\na\nb\nc\n"}, "rebase target")
        head2 = self.commit({"cfg.txt": "top\na\nB\nc\n"}, "change b again")
        pr, diff = self.pr(head2, base2)
        status, _ = mergeatlas.refresh_work("o-r-7", pr, diff, base2)
        self.assertEqual(status, "refreshed")
        data = self.saved_input()
        self.assertIn("[B](cfg.txt#L3)", data["cards"][0]["changes"][0]["change"])
        # outside the PR, the link stays on the commit the map was built on
        self.assertIn("[read](app.py#L3)", data["cards"][0]["changes"][0]["change"])
        published = self.published()
        self.assertEqual(published["pr"]["blob"], f"https://github.com/o/r/blob/{self.base}/")
        key = [line for line in published["cards"][0]["changes"][0]["snippets"][0] if line.get("key")]
        self.assertEqual([(line["text"], line["line"]) for line in key], [("+B", "R3")])

    def test_review_marks_survive_a_refresh(self):
        self.first_map()
        before = self.published()["cards"][0]["fingerprint"]
        git(self.repo, "checkout", "-q", self.base)
        base2 = self.commit({"cfg.txt": "top\na\nb\nc\n"}, "rebase target")
        head2 = self.commit({"cfg.txt": "top\na\nB\nc\n"}, "change b again")
        mergeatlas.refresh_work("o-r-7", *self.pr(head2, base2), base2)
        self.assertEqual(self.published()["cards"][0]["fingerprint"], before)

    def test_changes_that_differ_go_back_to_the_agent_card_by_card(self):
        self.first_map()
        head2 = self.commit({"cfg.txt": "a\nBee\nc\n"}, "change b differently")
        pr, diff = self.pr(head2, self.base)
        status, plan = mergeatlas.refresh_work("o-r-7", pr, diff, self.base)
        self.assertEqual(status, "partial")
        self.assertEqual(plan["redo"], ["cfg"])
        self.assertEqual(json.loads((mergeatlas.WORK / "o-r-7.pr.json").read_text())["headRefOid"], head2)

    def test_a_refresh_keeps_the_search_log(self):
        self.first_map()
        (mergeatlas.WORK / "o-r-7.searches.json").write_text('[{"term": "read", "mode": "word", "files": []}]')
        head2 = self.commit({"cfg.txt": "a\nBee\nc\n"}, "change b differently")
        mergeatlas.refresh_work("o-r-7", *self.pr(head2, self.base), self.base)
        self.assertEqual(json.loads((mergeatlas.WORK / "o-r-7.searches.json").read_text())[0]["term"], "read")


if __name__ == "__main__":
    unittest.main()
