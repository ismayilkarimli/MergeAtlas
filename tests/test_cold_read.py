"""The cold read: which cards a reader still has to read, and the files the readers are handed.

Run from the repository root:
    python3 -m unittest discover -s tests

A cold reader sees the words of a card with its link targets left out. The script writes each card whose words no reader
has passed to a file of its own, so the card never enters the agent's context, and keeps the hash of the words that
passed in <work-dir>/<map-id>.read.json. A card is read again only when its words change.

The interface under test, in skills/mergeatlas/scripts/mergeatlas.py:
    card_words(data, name, stack)       -> the words of the story or one card, as one string
    hashes_of(data, stack)              -> {name: hash of its words}, the story first
    readers(map_id)                     -> writes <map-id>.readers/<name>.txt for each unread name and prints its path
    passed(map_id, names)               -> records the names as read at their words as they stand
    finish(map_id)                      -> records every name as read
    card_text(map_id, name)             -> prints the words of a name, as it always has
"""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout

from test_run_record import MAP, Cache, mergeatlas

TWO = copy.deepcopy(MAP)
TWO["cards"].append({"id": "doc", "kind": "docs", "title": "doc.md", "paths": ["doc.md"], "summary": "Names the file.",
                     "bullets": ["One line"],
                     "changes": [{"intent": "i1", "problem": "The file is unnamed.", "change": "This PR names [it](doc.md#L1).",
                                  "result": "The file has a name.", "snippets": ["+# name"]}]})
TWO["edges"] = [{"from": "cfg", "to": "doc", "kind": "docs", "label": "Describes the setting", "relationship": "Both name b.",
                 "connection": "doc.md names the setting.", "connection_code": "# name", "connection_at": "doc.md#L1",
                 "flow": "The setting is described."}]


class Readers(Cache):
    def run_command(self, command, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            command(*args)
        return out.getvalue()

    def unread(self):
        """The names readers prints, in order."""
        return [line.split("\t")[0] for line in self.run_command(mergeatlas.readers, "o-r-7").splitlines() if "\t" in line]

    def edit(self, change):
        path = mergeatlas.WORK / "o-r-7.input.json"
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))

    def test_the_story_and_every_card_get_a_file_at_first(self):
        self.work(TWO)
        lines = self.run_command(mergeatlas.readers, "o-r-7").splitlines()
        folder = mergeatlas.WORK / "o-r-7.readers"
        self.assertEqual(lines, [f"{name}\t{folder / name}.txt" for name in ("story", "cfg", "doc")])
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["cfg.txt", "doc.txt", "story.txt"])
        self.assertEqual([(s["step"], s["story"]) for s in self.steps()], [("card", True), ("card", False), ("card", False)])

    def test_a_file_holds_the_instructions_then_the_cards_words(self):
        self.work(TWO)
        self.run_command(mergeatlas.readers, "o-r-7")
        for name in ("story", "cfg", "doc"):
            written = (mergeatlas.WORK / "o-r-7.readers" / f"{name}.txt").read_text(encoding="utf-8")
            self.assertEqual(written, mergeatlas.READER + "\n\n" + mergeatlas.card_words(TWO, name))
        self.assertTrue(mergeatlas.READER.endswith("\n\n---"))
        self.assertIn("This PR writes B [→ code].", (mergeatlas.WORK / "o-r-7.readers" / "cfg.txt").read_text(encoding="utf-8"))

    def test_a_passed_card_is_not_read_again(self):
        self.work(TWO)
        self.assertEqual(self.unread(), ["story", "cfg", "doc"])
        self.assertEqual(self.run_command(mergeatlas.passed, "o-r-7", ["story", "cfg"]), "passed: story, cfg\n")
        self.assertEqual(self.unread(), ["doc"])
        self.assertEqual([p.name for p in (mergeatlas.WORK / "o-r-7.readers").iterdir()], ["doc.txt"])
        self.run_command(mergeatlas.passed, "o-r-7", ["doc"])
        self.assertEqual(self.run_command(mergeatlas.readers, "o-r-7"),
                         "nothing to read: the story and every card passed as they stand\n")
        self.assertEqual(list((mergeatlas.WORK / "o-r-7.readers").iterdir()), [])

    def test_an_edited_card_is_read_again(self):
        self.work(TWO)
        self.run_command(mergeatlas.passed, "o-r-7", ["story", "cfg", "doc"])
        self.edit(lambda data: data["cards"][0]["changes"][0].update(result="B is upper case everywhere."))
        self.assertEqual(self.unread(), ["cfg"])
        # a link that moves leaves the words alone
        self.run_command(mergeatlas.passed, "o-r-7", ["cfg"])
        self.edit(lambda data: data["cards"][0]["changes"][0].update(change="This PR writes [B](cfg.txt#L9)."))
        self.assertEqual(self.unread(), [])

    def test_an_update_is_read_in_one_round(self):
        self.work(TWO)
        self.run_command(mergeatlas.passed, "o-r-7", ["story", "cfg", "doc"])
        update = mergeatlas.WORK / "o-r-7.update.json"
        update.write_text(json.dumps({"from": "c" * 40, "touched": ["cfg"], "hashes": mergeatlas.hashes_of(TWO)}))
        self.edit(lambda data: data["cards"][0]["changes"][0].update(result="B is upper case everywhere."))
        self.assertEqual(self.unread(), ["cfg"])
        self.edit(lambda data: data["cards"][0]["changes"][0].update(result="B is upper case in every file."))
        self.assertEqual(self.run_command(mergeatlas.readers, "o-r-7"),
                         "nothing more to read: an update is read once, so read your edits yourself, then run finish\n")
        self.assertEqual([s["step"] for s in self.steps()], ["card"])
        self.assertEqual([p.name for p in (mergeatlas.WORK / "o-r-7.readers").iterdir()], ["cfg.txt"])
        # the next update starts its own round
        update.write_text(json.dumps({"from": "d" * 40, "touched": ["cfg"], "hashes": mergeatlas.hashes_of(TWO)}))
        self.assertEqual(self.unread(), ["cfg"])

    def test_an_update_whose_words_all_passed_has_nothing_to_read(self):
        self.work(TWO)
        self.run_command(mergeatlas.passed, "o-r-7", ["story", "cfg", "doc"])
        update = mergeatlas.WORK / "o-r-7.update.json"
        update.write_text(json.dumps({"from": "c" * 40, "touched": [], "hashes": mergeatlas.hashes_of(TWO)}))
        self.assertEqual(self.run_command(mergeatlas.readers, "o-r-7"),
                         "nothing to read: the story and every card passed as they stand\n")
        self.assertNotIn("read", json.loads(update.read_text()))

    def test_editing_an_arrow_sends_the_cards_at_both_ends_back(self):
        data = copy.deepcopy(TWO)
        data["cards"].append({**data["cards"][1], "id": "other", "paths": ["other.md"]})
        self.work(data)
        self.run_command(mergeatlas.passed, "o-r-7", ["story", "cfg", "doc", "other"])
        self.edit(lambda d: d["edges"][0].update(label="Explains the setting"))
        self.assertEqual(self.unread(), ["cfg", "doc"])

    def test_passed_refuses_a_name_the_map_does_not_have(self):
        self.work(TWO)
        with self.assertRaises(SystemExit) as stopped:
            self.run_command(mergeatlas.passed, "o-r-7", ["cfg", "nope"])
        self.assertEqual(str(stopped.exception), "no card nope: choose from story, cfg, doc")
        self.assertFalse((mergeatlas.WORK / "o-r-7.read.json").exists())
        self.assertEqual(self.steps(), [])

    def test_finish_passes_every_card(self):
        self.work()
        self.publish()
        self.run_command(mergeatlas.finish, "o-r-7")
        self.assertEqual(json.loads((mergeatlas.WORK / "o-r-7.read.json").read_text()), mergeatlas.hashes_of(MAP))
        self.assertEqual(self.run_command(mergeatlas.readers, "o-r-7"),
                         "nothing to read: the story and every card passed as they stand\n")

    def test_a_stack_has_only_its_story_to_read(self):
        mergeatlas.WORK.mkdir(parents=True)
        story = {"background": "The stack has [two PRs](#1).", "problem": "p", "solution": "[One](#1) and [two](#2)."}
        (mergeatlas.WORK / "o-r-stack-9.input.json").write_text(json.dumps(story))
        (mergeatlas.WORK / "o-r-stack-9.stack.json").write_text("{}")
        self.assertEqual(list(mergeatlas.hashes_of(story, stack=True)), ["story"])
        out = self.run_command(mergeatlas.readers, "o-r-stack-9")
        self.assertEqual(out, f"story\t{mergeatlas.WORK / 'o-r-stack-9.readers' / 'story.txt'}\n")
        self.assertIn("The stack has two PRs [→ PR #1].", (mergeatlas.WORK / "o-r-stack-9.readers" / "story.txt").read_text(encoding="utf-8"))
        self.run_command(mergeatlas.passed, "o-r-stack-9", ["story"])
        self.assertEqual(self.run_command(mergeatlas.readers, "o-r-stack-9"),
                         "nothing to read: the story and every card passed as they stand\n")
        with self.assertRaises(SystemExit) as stopped:
            self.run_command(mergeatlas.passed, "o-r-stack-9", ["cfg"])
        self.assertEqual(str(stopped.exception), "a stack has only its story to read")

    def test_card_prints_what_it_printed_before(self):
        self.work(MAP)
        self.assertEqual(self.run_command(mergeatlas.card_text, "o-r-7", "story"), (
            "The app reads its settings [→ code].\n\nb is lower case.\n\nCapitalise b [→ card].\n"
            "\nintent i1: Capitalise b\noutcome: After this PR, cfg.txt holds B.\n"))
        self.assertEqual(self.run_command(mergeatlas.card_text, "o-r-7", "cfg"), (
            "# cfg.txt\n\nsummary: Holds the setting.\n\nchange 1, intent i1\nproblem: b is lower case.\n"
            "change: This PR writes B [→ code].\nresult: B is upper case.\nkey lines:\n+B\n"))
        (mergeatlas.WORK / "o-r-7.input.json").write_text(json.dumps(TWO))
        self.assertEqual(self.run_command(mergeatlas.card_text, "o-r-7", "doc"), (
            "# doc.md\n\nsummary: Names the file.\n\nchange 1, intent i1\nproblem: The file is unnamed.\n"
            "change: This PR names it [→ code].\nresult: The file has a name.\nkey lines:\n+# name\n"
            "\narrow from cfg.txt: Describes the setting\n# name\nrelationship: Both name b.\n"
            "connection: doc.md names the setting.\nflow: The setting is described.\n"))


if __name__ == "__main__":
    unittest.main()
