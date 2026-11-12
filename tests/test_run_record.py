"""The run record: what each command notes about a map's run, and what report makes of it.

Run from the repository root:
    python3 -m unittest discover -s tests

Every command that works on a map adds one line to <work-dir>/<map-id>.run.jsonl: when it ran and its counts. The
record never holds code, paths, search terms or the map's words, so report can be pasted into a bug report as it
stands. A run starts where fetch hands the agent work to do, and report sums up the latest one.

The interface under test, in skills/mergeatlas/scripts/mergeatlas.py:
    note(map_id, step, **numbers)       -> appends one step to the record
    rule_of(problem)                    -> the rule a publish rejection was for, "other" when no rule names it
    words_in(data)                      -> the words of prose a map holds, link targets left out
    summary_of(steps)                   -> the lines report prints for the latest run
    publish(map_id, asked=True)         -> notes the attempt, unless fetch republished the map by itself
    finish(map_id)                      -> notes that the cold read is done, which ends the map's draft
"""
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_stack_detection import mergeatlas

DIFF = "diff --git a/cfg.txt b/cfg.txt\n--- a/cfg.txt\n+++ b/cfg.txt\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"
PR = {"number": 7, "title": "Change b", "additions": 1, "deletions": 1, "files": [{"path": "cfg.txt", "additions": 1, "deletions": 1}],
      "headRefOid": "a" * 40, "pinned": "b" * 40, "baseRefName": "main", "url": "https://github.com/o/r/pull/7", "issues": [],
      "stack": None}
MAP = {
    "background": "The app reads [its settings](cfg.txt#L1-L3).", "problem": "b is lower case.", "solution": "[Capitalise b](i1).",
    "cards": [{"id": "cfg", "kind": "config", "title": "cfg.txt", "paths": ["cfg.txt"], "summary": "Holds the setting.",
               "bullets": ["One line"],
               "changes": [{"intent": "i1", "problem": "b is lower case.", "change": "This PR writes [B](cfg.txt#L2).",
                            "result": "B is upper case.", "snippets": ["+B"]}]}],
    "edges": [], "intents": [{"id": "i1", "title": "Capitalise b", "outcome": "After this PR, cfg.txt holds B."}],
}


class Cache(unittest.TestCase):
    """A cache of its own, so no test reads or writes the real one."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        patches = {"HOME": self.home, "WORK": self.home / "work", "DATA": self.home / "data"}
        for name, value in patches.items():
            patch = mock.patch.object(mergeatlas, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        serve = mock.patch.object(mergeatlas, "serve", lambda: None)
        serve.start()
        self.addCleanup(serve.stop)
        self.addCleanup(shutil.rmtree, self.home)

    def steps(self, map_id="o-r-7"):
        path = mergeatlas.WORK / f"{map_id}.run.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def work(self, data=MAP):
        mergeatlas.WORK.mkdir(parents=True)
        for name, text in {"pr.json": json.dumps(PR), "input.json": json.dumps(data), "diff": DIFF,
                           "searches.json": "[]", "cochange.json": "{}"}.items():
            (mergeatlas.WORK / f"o-r-7.{name}").write_text(text)

    def publish(self, problems=(), **how):
        with mock.patch.object(mergeatlas, "problems_in", return_value=list(problems)), redirect_stdout(io.StringIO()):
            mergeatlas.publish("o-r-7", **how)


class Notes(Cache):
    def test_a_step_is_one_line_with_its_time_and_release(self):
        mergeatlas.note("o-r-7", "search", mode="word", files=3)
        mergeatlas.note("o-r-7", "export")
        first, second = self.steps()
        self.assertEqual({k: first[k] for k in ("step", "mode", "files", "version")},
                         {"step": "search", "mode": "word", "files": 3, "version": mergeatlas.VERSION})
        self.assertEqual(second["step"], "export")
        self.assertLessEqual(first["at"], second["at"])

    def test_a_record_that_cannot_be_written_never_stops_the_command(self):
        mergeatlas.HOME.mkdir(exist_ok=True)
        mergeatlas.WORK.write_text("a file where the work directory should be")
        mergeatlas.note("o-r-7", "search", mode="word", files=3)

    def test_an_accepted_publish_notes_the_size_of_the_map(self):
        self.work()
        self.publish()
        (step,) = self.steps()
        self.assertEqual({k: step[k] for k in ("step", "accepted", "cards", "intents", "arrows")},
                         {"step": "publish", "accepted": True, "cards": 1, "intents": 1, "arrows": 0})
        self.assertEqual(step["words"], mergeatlas.words_in(MAP))

    def test_a_rejected_publish_notes_its_rules_and_none_of_its_words(self):
        self.work()
        problems = ["card cfg change 1: no such lines src/secret.py#L4", "card cfg: no such file src/secret.py",
                    "card cfg change 1 change: a reason ends with no code link, or issue or ticket it comes from, "
                    "after its because: 'It fails because the vault key is missing.'"]
        with self.assertRaises(SystemExit):
            self.publish(problems)
        (step,) = self.steps()
        self.assertEqual(step["rejected_for"], {"link-to-missing-lines": 1, "reach-names-missing-file": 1, "open-why": 1})
        written = (mergeatlas.WORK / "o-r-7.run.jsonl").read_text()
        for private in ("secret", "vault", "cfg"):
            self.assertNotIn(private, written)

    def test_a_map_fetch_republishes_by_itself_is_no_attempt(self):
        self.work()
        self.publish(asked=False)
        self.assertEqual(self.steps(), [])

    def test_finishing_a_map_is_noted(self):
        self.work()
        self.publish()
        with redirect_stdout(io.StringIO()):
            mergeatlas.finish("o-r-7")
        self.assertEqual([s["step"] for s in self.steps()], ["publish", "finish"])

    def test_printing_a_card_for_a_cold_read_is_noted(self):
        self.work()
        with redirect_stdout(io.StringIO()):
            mergeatlas.card_text("o-r-7", "story")
            mergeatlas.card_text("o-r-7", "cfg")
        self.assertEqual([(s["step"], s["story"]) for s in self.steps()], [("card", True), ("card", False)])

    def test_asking_for_a_card_that_is_not_there_is_not_noted(self):
        self.work()
        with self.assertRaises(SystemExit):
            mergeatlas.card_text("o-r-7", "nope")
        self.assertEqual(self.steps(), [])


class Drafts(Cache):
    """A map is served as a draft from its first publish, so it can be read while its cards are cold read, and it stays
    one until finish. The published map says so in pr.draft, beside the commit and time it was made at in pr.mapped."""

    def map(self):
        return json.loads((mergeatlas.DATA / "o-r-7.json").read_text())["pr"]

    def finish(self):
        out = io.StringIO()
        with redirect_stdout(out):
            mergeatlas.finish("o-r-7")
        return out.getvalue()

    def test_a_published_map_is_a_draft_that_says_what_it_was_made_at(self):
        self.work()
        with mock.patch.object(mergeatlas.time, "time", return_value=1700000000.4):
            self.publish()
        self.assertEqual((self.map()["draft"], self.map()["mapped"]), (True, {"at": 1700000000, "head": "a" * 40}))
        self.assertTrue(mergeatlas.is_draft("o-r-7"))

    def test_finish_ends_the_draft_and_changes_nothing_else(self):
        self.work()
        self.publish()
        before = json.loads((mergeatlas.DATA / "o-r-7.json").read_text())
        self.assertIn("?map=o-r-7", self.finish())
        after = json.loads((mergeatlas.DATA / "o-r-7.json").read_text())
        self.assertFalse(mergeatlas.is_draft("o-r-7"))
        before["pr"]["draft"] = False
        self.assertEqual(after, before)

    def test_publishing_again_after_finish_starts_a_new_draft(self):
        self.work()
        self.publish()
        self.finish()
        self.publish()
        self.assertTrue(mergeatlas.is_draft("o-r-7"))

    def test_a_map_fetch_republishes_by_itself_stays_as_finished_as_it_was(self):
        self.work()
        self.publish()
        self.publish(asked=False)
        self.assertTrue(mergeatlas.is_draft("o-r-7"))
        self.finish()
        self.publish(asked=False)
        self.assertFalse(mergeatlas.is_draft("o-r-7"))

    def test_a_map_from_before_drafts_is_finished(self):
        mergeatlas.DATA.mkdir(parents=True)
        (mergeatlas.DATA / "o-r-7.json").write_text(json.dumps({"pr": {"number": 7}, "cards": []}))
        self.assertFalse(mergeatlas.is_draft("o-r-7"))

    def test_finish_refuses_a_map_that_was_never_published(self):
        with self.assertRaises(SystemExit) as stopped:
            self.finish()
        self.assertIn("run publish first", str(stopped.exception))
        self.assertEqual(self.steps(), [])


class Rules(unittest.TestCase):
    def test_a_rejection_is_named_by_its_rule(self):
        for problem, rule in [
            ("card a change 2: missing result", "missing-part"),
            ("missing background", "missing-part"),
            ("card a: src/x.py is already in another card", "file-on-two-cards"),
            ("no card holds src/x.py", "file-without-card"),
            ("arrow a -> b: no card b", "arrow-to-missing-card"),
            ("not accounted for: src/x.py (from search 'run')", "reach-not-sorted"),
            ("intent i2: no change", "intent-without-change"),
            ("card a change 1: no intent i9", "change-without-intent"),
            ("card a b: an id takes letters, digits, - and _ only", "id-not-a-slug"),
            ("solution: link every PR as [words](#N); missing #3", "stack-story"),
            ("something publish has never said", "other"),
        ]:
            self.assertEqual(mergeatlas.rule_of(problem), rule, problem)

    def test_a_sentence_quoted_from_the_map_cannot_rename_its_rejection(self):
        problem = ("card a summary: a reason ends with no code link, or issue or ticket it comes from, after its because: "
                   "'It breaks because there is no such file and no card holds it.'")
        self.assertEqual(mergeatlas.rule_of(problem), "open-why")

    def test_every_rejection_publish_can_make_has_a_rule(self):
        broken = {
            "tickets": [{}, {"key": "ENG-1", "title": "t", "url": "http://tracker"}],
            "broad_searches": [{"term": "never-run"}],
            "cards": [
                {"id": "two words", "kind": "core", "paths": ["a.py", "not-in-pr.py"], "summary": "Fails because it does.",
                 "changes": [{"intent": "nope", "problem": "as described above", "snippets": [" same"], "mechanical": "whitespace"},
                             {"intent": "mech", "problem": "as described above", "snippets": [" same"]}],
                 "reaches": [{"paths": ["gone.py"], "effect": "none"}], "unaffected": [{"paths": ["gone.py"]}]},
                {"id": "two words", "kind": "odd", "paths": ["a.py"], "changes": [{"intent": "tests", "mechanical": "whitespace"}]},
                {"id": "t", "kind": "test", "paths": ["b.py"], "changes": [{"intent": "tests", "change": "[x](a.py#L99)"}]},
            ],
            "intents": [{"id": "tests", "builds_on": [{"intent": "later"}]}, {"id": "tests"}, {"id": "unused"},
                        {"id": "mech", "mechanical": True}, {"id": "mech2", "mechanical": True}, {"id": "not a slug"}],
            "edges": [{"from": "t", "to": "t", "kind": "odd", "connection_at": "a.py#L99"}, {"from": "t", "to": "ghost"}],
            "solution": "[x](ghost)",
        }
        rows = mergeatlas.diff_rows("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n same\n-x = 1\n+x = 2\n")
        searches = [{"term": "x", "mode": "word", "files": ["unsorted.py"]}]
        found = mergeatlas.problems_in(broken, {"a.py": (1, 1), "b.py": (0, 0), "c.py": (1, 0)}, lambda path: None, rows,
                                       searches, {})
        found += mergeatlas.stack_problems({"solution": "[x](#9) because."}, {"prs": [{"number": 1}]})
        self.assertGreater(len({mergeatlas.rule_of(p) for p in found}), 20)
        self.assertEqual([p for p in found if mergeatlas.rule_of(p) == "other"], [])


class Words(unittest.TestCase):
    def test_link_targets_are_not_words(self):
        self.assertEqual(mergeatlas.words_in({"background": "Reads [its two settings](src/app/cfg.txt#L1-L3) once."}), 5)

    def test_every_piece_of_prose_counts(self):
        # story 5 + 4 + 2, card 3 + 2 + 4 + 4 + 4, intent 6
        self.assertEqual(mergeatlas.words_in(MAP), 34)


def step(at, name, **numbers):
    return {"at": at, "step": name, "version": "0.1.0", **numbers}


RUN = [
    step(0, "fetch", status="new", files=36, additions=2199, deletions=92, diff_lines=4210),
    step(60, "search", mode="word", files=12), step(90, "search", mode="word", files=3), step(120, "search", mode="paths", files=1),
    step(600, "publish", accepted=False, rejected_for={"open-why": 4, "link-to-missing-lines": 1}),
    step(700, "publish", accepted=False, rejected_for={"open-why": 2}),
    step(900, "publish", accepted=True, cards=32, intents=8, arrows=23, words=7000),
    step(910, "card", story=True), step(911, "card", story=False), step(912, "card", story=False),
    step(1500, "publish", accepted=True, cards=32, intents=8, arrows=23, words=7400),
    step(1510, "card", story=False),
    step(1800, "publish", accepted=True, cards=32, intents=8, arrows=23, words=7450),
]


class Summary(Cache):
    def line(self, steps, name):
        """What the summary says after a label; labels fill a column 15 wide."""
        return next((line[15:] for line in mergeatlas.summary_of(steps) if line[:15].rstrip() == name), None)

    def test_the_pull_request_is_sized(self):
        self.assertEqual(self.line(RUN, "pull request"), "36 files, +2199 -92, 4210 diff lines, new")

    def test_searches_are_counted_by_kind(self):
        self.assertEqual(self.line(RUN, "searches"), "3 (2 word, 1 paths), 16 files matched")

    def test_rejections_are_summed_across_attempts_most_frequent_first(self):
        self.assertEqual(self.line(RUN, "publishes"), "5, of which 2 rejected")
        self.assertEqual(self.line(RUN, "rejected for"), "open-why 6, link-to-missing-lines 1")

    def test_a_cold_read_round_is_a_run_of_cards_between_publishes(self):
        self.assertEqual(self.line(RUN, "cold reads"), "4 cards and stories printed, over 2 rounds")

    def test_the_map_is_sized_as_last_published(self):
        self.assertEqual(self.line(RUN, "map"), "32 cards, 8 intents, 23 arrows, 7450 words")

    def test_time_runs_from_the_fetch_to_the_finished_map(self):
        done = RUN + [step(1860, "finish"), step(2400, "export")]
        self.assertEqual(self.line(done, "time"), "15 min to the first accepted publish, 31 min to the finished map")

    def test_a_run_whose_cold_read_was_not_finished_says_so(self):
        self.assertEqual(self.line(RUN, "time"),
                         "15 min to the first accepted publish, 30 min to the last step, and the cold read was not finished")

    def test_a_later_fetch_that_hands_back_work_starts_a_new_run(self):
        later = [step(90000, "fetch", status="partial", files=37, additions=2300, deletions=92, diff_lines=4400),
                 step(90300, "publish", accepted=True, cards=33, intents=8, arrows=23, words=7600)]
        self.assertEqual(self.line(RUN + later, "run"), "2 of 2 for this map, MergeAtlas 0.1.0")
        self.assertEqual(self.line(RUN + later, "pull request"), "37 files, +2300 -92, 4400 diff lines, changed since its last map")
        self.assertEqual(self.line(RUN + later, "publishes"), "1, of which 0 rejected")
        self.assertEqual(self.line(RUN + later, "time"),
                         "5 min to the first accepted publish, 5 min to the last step, and the cold read was not finished")

    def test_a_fetch_that_finds_the_map_unchanged_starts_no_run(self):
        same = [step(90000, "fetch", status="same-head", files=36, additions=2199, deletions=92, diff_lines=4210)]
        self.assertEqual(self.line(RUN + same, "run"), "1 of 1 for this map, MergeAtlas 0.1.0")

    def test_a_run_with_nothing_published_reports_what_it_has(self):
        self.assertEqual([line.split()[0] for line in mergeatlas.summary_of(RUN[:2])], ["run", "pull", "searches"])

    def test_report_prints_the_summary_under_what_it_ran_on(self):
        mergeatlas.WORK.mkdir(parents=True)
        (mergeatlas.WORK / "o-r-7.run.jsonl").write_text("".join(json.dumps(s) + "\n" for s in RUN))
        out = io.StringIO()
        with redirect_stdout(out):
            mergeatlas.report("o-r-7")
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[0].startswith(f"MergeAtlas {mergeatlas.VERSION}, Python "))
        self.assertEqual(lines[2:], mergeatlas.summary_of(RUN))
        self.assertNotIn("o-r-7", out.getvalue())

    def test_report_says_when_a_map_has_no_record(self):
        with self.assertRaises(SystemExit) as stopped:
            mergeatlas.report("o-r-7")
        self.assertIn("no run record", str(stopped.exception))


if __name__ == "__main__":
    unittest.main()
