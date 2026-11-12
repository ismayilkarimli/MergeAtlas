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

A first map is read in two rounds and an update in one. <map-id>.seen.json holds the rounds so far and the hash of each
sentence a reader was given; from the second round on a reader gets the REREADER instructions and the sentences new since
marked with ⟦ ⟧, and a card that gained no sentence passes without a reader:
    card_words(data, name, stack, seen) -> the same words, new sentences marked when seen is given
    sentences_in(data, name, stack)     -> the hash of every sentence of a name
"""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from test_run_record import MAP, PR, Cache, mergeatlas

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
        (mergeatlas.WORK / "o-r-7.seen.json").write_text(json.dumps({"rounds": 0, "seen": {}}))
        self.assertEqual(self.unread(), ["cfg"])

    def test_an_update_whose_words_all_passed_has_nothing_to_read(self):
        self.work(TWO)
        self.run_command(mergeatlas.passed, "o-r-7", ["story", "cfg", "doc"])
        update = mergeatlas.WORK / "o-r-7.update.json"
        update.write_text(json.dumps({"from": "c" * 40, "touched": [], "hashes": mergeatlas.hashes_of(TWO)}))
        self.assertEqual(self.run_command(mergeatlas.readers, "o-r-7"),
                         "nothing to read: the story and every card passed as they stand\n")
        self.assertFalse((mergeatlas.WORK / "o-r-7.seen.json").exists())

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

    def round(self, edits=()):
        """Edits the cards, then runs readers; returns the names it prints."""
        for edit in edits:
            self.edit(edit)
        return self.unread()

    def seen(self):
        return json.loads((mergeatlas.WORK / "o-r-7.seen.json").read_text())

    def test_a_first_round_reader_gets_the_whole_card_unmarked(self):
        self.work(TWO)
        self.assertEqual(self.unread(), ["story", "cfg", "doc"])
        written = (mergeatlas.WORK / "o-r-7.readers" / "cfg.txt").read_text(encoding="utf-8")
        self.assertEqual(written, mergeatlas.READER + "\n\n" + mergeatlas.card_words(TWO, "cfg"))
        self.assertNotIn("⟦", written)
        self.assertEqual(self.seen()["rounds"], 1)
        self.assertEqual(sorted(self.seen()["seen"]), ["cfg", "doc", "story"])
        self.assertEqual(self.seen()["seen"]["cfg"], mergeatlas.sentences_in(TWO, "cfg"))

    def test_a_second_round_marks_only_the_new_sentences(self):
        self.work(TWO)
        self.unread()
        self.assertEqual(self.round([lambda d: d["cards"][0]["changes"][0].update(result="B is upper case everywhere.")]), ["cfg"])
        written = (mergeatlas.WORK / "o-r-7.readers" / "cfg.txt").read_text(encoding="utf-8")
        self.assertIn("result: ⟦B is upper case everywhere.⟧\n", written)
        self.assertIn("change: This PR writes B [→ code].\n", written)
        self.assertEqual(written.count("⟦") - mergeatlas.REREADER.count("⟦"), 1)
        self.assertEqual(self.seen()["rounds"], 2)
        self.assertEqual(len(self.seen()["seen"]["cfg"]), len(mergeatlas.sentences_in(TWO, "cfg")) + 1)

    def test_a_second_round_reader_gets_the_rereader_s_instructions(self):
        self.work(TWO)
        self.unread()
        self.round([lambda d: d["cards"][0].update(summary="Holds the setting twice.")])
        written = (mergeatlas.WORK / "o-r-7.readers" / "cfg.txt").read_text(encoding="utf-8")
        self.assertTrue(written.startswith(mergeatlas.REREADER + "\n\n"))
        self.assertIn("the sentences inside ⟦ ⟧ were written or edited since", mergeatlas.REREADER)
        self.assertIn('If the marked sentences leave nothing open, reply "none".', mergeatlas.REREADER)
        self.assertNotIn("Find the places where it leaves you", mergeatlas.REREADER)
        self.assertEqual(mergeatlas.REREADER.split("\n- ", 1)[1], mergeatlas.READER.split("\n- ", 1)[1].replace(
            'If nothing is missing, reply "none".', 'If the marked sentences leave nothing open, reply "none".'))

    def test_a_card_that_only_lost_a_sentence_passes_without_a_reader(self):
        self.work(TWO)
        self.edit(lambda d: d["cards"][0].update(summary="Holds the setting. It is read at start."))
        self.unread()
        self.edit(lambda d: d["cards"][0].update(summary="Holds the setting."))
        self.assertEqual(self.run_command(mergeatlas.readers, "o-r-7"), "nothing to read: the story and every card passed as they stand\n")
        data = json.loads((mergeatlas.WORK / "o-r-7.input.json").read_text())
        self.assertEqual(json.loads((mergeatlas.WORK / "o-r-7.read.json").read_text()), mergeatlas.hashes_of(data))
        self.assertEqual(self.seen()["rounds"], 1)
        self.assertEqual(len(self.steps()), 3)

    def test_a_third_round_of_a_first_map_has_nothing_more_to_read(self):
        self.work(TWO)
        self.unread()
        self.assertEqual(self.round([lambda d: d["cards"][0].update(summary="Holds the setting twice.")]), ["cfg"])
        self.edit(lambda d: d["cards"][0].update(summary="Holds the setting three times."))
        self.assertEqual(self.run_command(mergeatlas.readers, "o-r-7"),
                         "nothing more to read: a map is read in two rounds, so read your last edits yourself, then run finish\n")
        self.assertEqual([p.name for p in (mergeatlas.WORK / "o-r-7.readers").iterdir()], ["cfg.txt"])
        self.assertEqual(self.seen()["rounds"], 2)

    def test_an_update_marks_only_the_sentences_written_for_it(self):
        self.work(TWO)
        self.run_command(mergeatlas.passed, "o-r-7", ["story", "cfg", "doc"])
        mergeatlas.mark_update("o-r-7", {"headRefOid": "c" * 40}, {"redo": [{"id": "cfg"}]})
        self.assertEqual(self.seen(), {"rounds": 0, "seen": {name: mergeatlas.sentences_in(TWO, name) for name in ("story", "cfg", "doc")}})
        self.edit(lambda d: d["cards"][0]["changes"][0].update(result="B is upper case everywhere."))
        self.assertEqual(self.unread(), ["cfg"])
        written = (mergeatlas.WORK / "o-r-7.readers" / "cfg.txt").read_text(encoding="utf-8")
        self.assertTrue(written.startswith(mergeatlas.REREADER))
        self.assertEqual(written.count("⟦") - mergeatlas.REREADER.count("⟦"), 1)
        self.assertIn("result: ⟦B is upper case everywhere.⟧", written)

    def test_an_update_is_still_read_once(self):
        self.work(TWO)
        self.run_command(mergeatlas.passed, "o-r-7", ["story", "cfg", "doc"])
        mergeatlas.mark_update("o-r-7", {"headRefOid": "c" * 40}, {"redo": [{"id": "cfg"}]})
        self.assertEqual(self.round([lambda d: d["cards"][0]["changes"][0].update(result="B is upper case everywhere.")]), ["cfg"])
        self.edit(lambda d: d["cards"][0]["changes"][0].update(result="B is upper case in every file."))
        self.assertEqual(self.run_command(mergeatlas.readers, "o-r-7"),
                         "nothing more to read: an update is read once, so read your edits yourself, then run finish\n")

    def test_card_words_are_unchanged_when_nothing_is_marked(self):
        self.work(TWO)
        for name in ("story", "cfg", "doc"):
            self.assertEqual(mergeatlas.card_words(TWO, name, seen=None), mergeatlas.card_words(TWO, name))
        self.assertEqual(mergeatlas.card_words(TWO, "doc"), (
            "# doc.md\n\nsummary: Names the file.\n\nchange 1, intent i1\nproblem: The file is unnamed.\n"
            "change: This PR names it [→ code].\nresult: The file has a name.\nkey lines:\n+# name\n"
            "\narrow from cfg.txt: Describes the setting\n# name\nrelationship: Both name b.\n"
            "connection: doc.md names the setting.\nflow: The setting is described."))
        known = set(mergeatlas.sentences_in(TWO, "doc"))
        self.assertNotIn("⟦", mergeatlas.card_words(TWO, "doc", seen=known))
        self.assertEqual(mergeatlas.mark_new("One. Two.", None), "One. Two.")
        self.assertEqual(mergeatlas.mark_new("One.  Two.", {mergeatlas.sentence_hash("One.")}), "One. ⟦Two.⟧")

    def test_a_map_started_over_forgets_its_rounds(self):
        self.work(TWO)
        self.unread()
        (mergeatlas.DATA).mkdir(parents=True)
        (mergeatlas.DATA / "o-r-7.json").write_text("{}")
        with mock.patch.object(mergeatlas, "co_changes", return_value={}):
            self.assertEqual(mergeatlas.refresh_work("o-r-7", dict(PR), "", "b" * 40, fresh=True), ("new", None))
        self.assertFalse((mergeatlas.WORK / "o-r-7.seen.json").exists())
        self.assertFalse((mergeatlas.WORK / "o-r-7.read.json").exists())


if __name__ == "__main__":
    unittest.main()
