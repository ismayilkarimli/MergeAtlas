"""The evals: a fixed set of pull requests to judge a change to the skill against.

Run from the repository root:
    python3 -m unittest discover -s tests

evals/run.py maps each pull request of evals/set.json under a label of its own, with a copy of the skill that runs against
the label's cache, writes down how each run went, and scores the maps: their links against the code, and six fixed questions
a model answers from the cards alone. No test starts claude, clones a repository or touches ~/.cache/mergeatlas-evals.

The interface under test, in evals/run.py:
    prepare(label, key, skill)          -> sets up one pull request for a run and prints the prompt
    snapshot(folder, skill)             -> gives a label its own copy of the skill, once
    collect(label, key)                 -> writes <key>.result.json from the run record and the published map
    verdicts(reply)                     -> counts a checker's wrong and elsewhere lines
    answered(reply)                     -> adds up a judge's grades
    compare(first, second)              -> prints a Markdown table for each pull request both labels hold
"""
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("evals_run", REPO / "evals" / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


class Set(unittest.TestCase):
    def test_the_set_names_three_pulls_with_full_commit_ids(self):
        pulls = json.loads((REPO / "evals" / "set.json").read_text())["pulls"]
        self.assertEqual([p["key"] for p in pulls], ["small", "medium", "large"])
        for pull in pulls:
            self.assertRegex(pull["head"], r"^[0-9a-f]{40}$")
            self.assertGreater(pull["budget_usd"], 0)
            self.assertGreater(pull["timeout_min"], 0)
        self.assertEqual(run.map_id_of(pulls[0]), "excalidraw-excalidraw-10903")

    def test_every_questions_file_belongs_to_a_pull_in_the_set(self):
        keys = {p["key"] for p in run.pulls()}
        files = sorted((REPO / "evals" / "questions").glob("*.json"))
        self.assertEqual([f.stem for f in files], ["medium", "small"])
        for file in files:
            self.assertIn(file.stem, keys)
            asked = json.loads(file.read_text())
            self.assertEqual(len(asked), 6)
            self.assertTrue(all(item["q"] and item["a"] for item in asked))


class Labels(unittest.TestCase):
    """A cache of their own, so no test reads or writes ~/.cache/mergeatlas-evals."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        for name, value in {"ROOT": self.root, "ensure_clone": lambda pull: self.root / "repos" / "clone", "stop_server": lambda: None}.items():
            patch = mock.patch.object(run, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.small = run.pull_of("small")
        self.map_id = run.map_id_of(self.small)

    def skill(self, name, script):
        folder = self.root / name / "skills" / "mergeatlas"
        (folder / "scripts" / "__pycache__").mkdir(parents=True, exist_ok=True)
        (folder / "scripts" / "mergeatlas.py").write_text(script)
        (folder / "SKILL.md").write_text(name)
        return folder

    def prepare(self, label, key="small", skill=None):
        out = io.StringIO()
        with redirect_stdout(out):
            run.prepare(label, key, skill)
        return out.getvalue()

    def write(self, label, relative, text):
        path = run.folder_of(label) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def record(self, label, steps):
        self.write(label, f"home/work/{self.map_id}.run.jsonl", "\n".join(json.dumps(s) for s in steps))

    def collect(self, label, key="small"):
        run.collect(label, key)
        return json.loads((run.folder_of(label) / f"{key}.result.json").read_text())


class Snapshots(Labels):
    def test_the_stub_runs_the_skill_against_the_label_s_cache(self):
        self.prepare("lab", skill=REPO / "skills" / "mergeatlas")
        stub = run.folder_of("lab") / "skill" / "scripts" / "mergeatlas.py"
        self.assertTrue((stub.parent / "mergeatlas_real.py").exists())
        self.assertFalse((stub.parent / "__pycache__").exists())
        version = subprocess.run([sys.executable, str(stub), "version"], capture_output=True, text=True)
        self.assertRegex(version.stdout, r"^\d+\.\d+\.\d+\n$")
        report = subprocess.run([sys.executable, str(stub), "report", "x"], capture_output=True, text=True)
        self.assertNotEqual(report.returncode, 0)
        self.assertIn("no run record for x", report.stderr)
        self.write("lab", "home/work/x.run.jsonl", json.dumps({"at": 1.0, "step": "fetch", "version": "0.4.0", "status": "new", "files": 1,
                                                               "additions": 2, "deletions": 3, "diff_lines": 9}))
        report = subprocess.run([sys.executable, str(stub), "report", "x"], capture_output=True, text=True)
        self.assertIn("pull request   1 files, +2 -3, 9 diff lines, new", report.stdout)

    def test_a_label_keeps_the_skill_it_was_first_given(self):
        self.prepare("lab", skill=self.skill("one", 'print("one")\n'))
        self.prepare("lab", skill=self.skill("two", 'print("two")\n'))
        folder = run.folder_of("lab") / "skill"
        self.assertEqual((folder / "scripts" / "mergeatlas_real.py").read_text(), 'print("one")\n')
        self.assertEqual((folder / "SKILL.md").read_text(), "one")
        self.prepare("other", skill=self.skill("two", 'print("two")\n'))
        self.assertEqual((run.folder_of("other") / "skill" / "SKILL.md").read_text(), "two")

    def test_prepare_clears_what_an_earlier_run_left(self):
        skill = self.skill("one", "")
        left = [f"home/work/{self.map_id}.run.jsonl", f"home/work/{self.map_id}.readers/story.txt", f"home/data/{self.map_id}.json",
                "small.result.json", "small.claude.json"]
        kept = ["home/work/other-repo-1.run.jsonl", "home/data/other-repo-1.json", "large.result.json", "skill/SKILL.md"]
        for relative in left + kept:
            self.write("lab", relative, "x")
        out = self.prepare("lab", skill=skill)
        for relative in left:
            self.assertFalse((run.folder_of("lab") / relative).exists(), relative)
        for relative in kept:
            self.assertTrue((run.folder_of("lab") / relative).exists(), relative)
        folder = run.folder_of("lab")
        prompt = (folder / "small.prompt.txt").read_text()
        self.assertEqual(out, f"{self.root / 'repos' / 'clone'}\n{prompt}\n")
        self.assertEqual(prompt, (
            f"Read the file {folder}/skill/SKILL.md and follow it to map this pull request: https://github.com/excalidraw/excalidraw/pull/10903\n"
            f"Wherever it says <skill-dir>, use {folder}/skill. Do not use any installed mergeatlas skill. Use Sonnet 5.5 at medium effort "
            "for the cold readers. You have no browser, so skip opening the page in step 9. Ask no questions, because nobody can answer. "
            'When the map is finished, reply with the one word "done".'))


class Results(Labels):
    def test_the_result_counts_rounds_rejections_and_checked_links(self):
        self.record("lab", [
            {"at": 1000.0, "step": "fetch", "status": "new"},
            {"at": 1060.0, "step": "publish", "accepted": False},
            {"at": 1120.0, "step": "publish", "accepted": True, "cards": 4, "intents": 2, "arrows": 3, "words": 500},
            {"at": 1130.0, "step": "card"}, {"at": 1131.0, "step": "card"}, {"at": 1132.0, "step": "claims", "links": 9},
            {"at": 1200.0, "step": "checked", "ok": 7, "sent_back": 2},
            {"at": 1300.0, "step": "publish", "accepted": True, "cards": 5, "intents": 2, "arrows": 3, "words": 520},
            {"at": 1310.0, "step": "card"}, {"at": 1320.0, "step": "claims", "links": 2},
            {"at": 1330.0, "step": "checked", "ok": 2, "sent_back": 0},
            {"at": 1600.0, "step": "finish"},
        ])
        self.write("lab", f"home/data/{self.map_id}.json", json.dumps({"pr": {"draft": False}}))
        self.write("lab", "small.claude.json", json.dumps({"total_cost_usd": 3.25, "num_turns": 80, "duration_ms": 1800000}))
        self.assertEqual(self.collect("lab"), {
            "finished": True, "minutes_to_first_map": 2.0, "minutes_to_finish": 10.0, "publishes": 3, "rejected": 1,
            "reader_files": 3, "reader_rounds": 2, "links_checked": 11, "links_sent_back": 2,
            "cards": 5, "intents": 2, "arrows": 3, "words": 520, "cost_usd": 3.25, "turns": 80, "agent_minutes": 30.0})

    def test_a_run_that_never_finished_says_so(self):
        self.record("lab", [{"at": 1000.0, "step": "fetch", "status": "new"},
                            {"at": 1060.0, "step": "publish", "accepted": False, "rejected_for": {"other": 1}}])
        self.write("lab", f"home/data/{self.map_id}.json", json.dumps({"pr": {"draft": True}}))
        result = self.collect("lab")
        self.assertFalse(result["finished"])
        for field in ("minutes_to_first_map", "minutes_to_finish", "cards", "words", "cost_usd", "turns", "agent_minutes"):
            self.assertIsNone(result[field], field)
        self.assertEqual((result["publishes"], result["rejected"], result["reader_files"], result["links_checked"]), (1, 1, 0, 0))
        self.assertFalse(self.collect("empty")["finished"])


class Scores(unittest.TestCase):
    def test_verdicts_count_wrong_and_elsewhere_and_ignore_none(self):
        reply = "1 wrong: it sets the flag to false\n2. Elsewhere - the lines declare a name\n- 4: WRONG, contradicts\nthe 5 wrong ones are noted\n"
        self.assertEqual(dict(run.verdicts(reply)), {"wrong": 2, "elsewhere": 1})
        self.assertEqual(dict(run.verdicts("none")), {})
        self.assertEqual(dict(run.verdicts("1 ok\n2 wrongly named")), {})

    def test_answers_score_a_half_for_partly(self):
        self.assertEqual(run.answered("1: yes\n2 - partly\n3. no\n4: YES\n"), 2.5)
        self.assertEqual(run.answered("nothing"), 0)


class Comparisons(Labels):
    def table(self, first, second):
        out = io.StringIO()
        with redirect_stdout(out):
            run.compare(first, second)
        return out.getvalue()

    def test_compare_shows_a_dash_for_what_one_label_lacks(self):
        self.write("a", "small.result.json", json.dumps({
            "finished": True, "minutes_to_first_map": 12.5, "minutes_to_finish": 30.0, "cost_usd": 3.5, "turns": 90, "rejected": 1,
            "reader_rounds": 3, "reader_files": 12, "links_checked": 20, "links_sent_back": 2, "cards": 4, "words": 800}))
        self.write("a", "small.score.json", json.dumps({"links": 20, "wrong": 1, "elsewhere": 2, "questions": 6, "answered": 4.5}))
        self.write("b", "small.result.json", json.dumps({"finished": False, "cost_usd": None, "cards": None}))
        self.write("a", "medium.result.json", "{}")
        lines = self.table("a", "b").splitlines()
        self.assertEqual(lines[:3], ["| small #10903 | a | b |", "|---|---|---|", "| finished | yes | no |"])
        self.assertEqual(len(lines), 2 + 13)
        rows = dict(re.fullmatch(r"\| (.*?) \| (.*) \|", line).groups() for line in lines[2:])
        self.assertEqual(rows["minutes to the first map"], "12.5 | -")
        self.assertEqual(rows["cost (USD)"], "3.5 | -")
        self.assertEqual(rows["map: cards / words"], "4 / 800 | -")
        self.assertEqual(rows["links a checker rejects"], "3 of 20 | -")
        self.assertEqual(rows["questions answered"], "4.5 of 6 | -")
        self.assertEqual(rows["links sent back while mapping"], "2 | -")
        self.assertNotIn("medium", self.table("a", "b"))


if __name__ == "__main__":
    unittest.main()
