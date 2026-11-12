"""The claim check: each code link's words are checked against the lines it cites.

Run from the repository root:
    python3 -m unittest discover -s tests

A claim is one code link in a prose field of a map: its linked words, the sentence it sits in, and the lines it points at.
The script writes each claim not yet checked to a file with the lines it cites, so a checker can judge whether those lines do
what the linked words say, and keeps the hash of every claim that held in <work-dir>/<map-id>.checked.json. A claim is
checked again only when its words, its path or the text of its lines change.

The interface under test, in skills/mergeatlas/scripts/mergeatlas.py:
    claims_of(data, read)               -> {name: [claim, ...]}, the story first, each link under the first name that holds it
    claims(map_id, everything)          -> writes <map-id>.claims/<name>.txt and .json for each name with unchecked claims
    checked(map_id, args)               -> records the claims a checker found to hold
    finish(map_id)                      -> records every claim as checked
"""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from test_run_record import MAP, Cache, mergeatlas

FILES = {"cfg.txt": [f"row {n}" for n in range(1, 31)], "app.py": [f"code {n}" for n in range(1, 11)]}
STORY = {"background": "The app starts.", "problem": "It is slow.", "solution": "It is fast.", "intents": []}


def data_of(summary="Sets [the flag](cfg.txt#L10-L11) once.", **story):
    data = copy.deepcopy(MAP)
    data.update(STORY)
    data.update(story)
    data["cards"][0]["summary"] = summary
    data["cards"][0]["changes"][0]["change"] = "Nothing."
    data["intents"] = [{"id": "i1", "title": "Capitalise b", "outcome": "Done."}]
    return data


class Checking(Cache):
    def setUp(self):
        super().setUp()
        self.files = copy.deepcopy(FILES)
        reader = mock.patch.object(mergeatlas, "reader_of", lambda pr: self.files.get)
        reader.start()
        self.addCleanup(reader.stop)

    def run_command(self, command, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            command(*args)
        return out.getvalue()

    def edit(self, change):
        path = mergeatlas.WORK / "o-r-7.input.json"
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))

    def printed(self, everything=False):
        """The names claims prints, in order."""
        return [line.split("\t")[0] for line in self.run_command(mergeatlas.claims, "o-r-7", everything).splitlines() if "\t" in line]

    def file(self, name, suffix="txt"):
        return (mergeatlas.WORK / "o-r-7.claims" / f"{name}.{suffix}").read_text(encoding="utf-8")


class Claims(Checking):
    def test_a_claim_file_shows_the_cited_lines_marked_and_the_lines_around_them(self):
        self.work(data_of("Sets [the flag](cfg.txt#L10-L11) once. It reads [row](app.py#L2)."))
        lines = self.run_command(mergeatlas.claims, "o-r-7").splitlines()
        self.assertEqual(lines, [f"cfg\t{mergeatlas.WORK / 'o-r-7.claims' / 'cfg.txt'}"])
        first = ["claim 1", "statement: Sets the flag [→ code] once.", "linked words: the flag", "cfg.txt"]
        first += [f"{'> ' if n in (10, 11) else '  '}{n:>2} | row {n}" for n in range(4, 18)]
        second = ["claim 2", "statement: It reads row [→ code].", "linked words: row", "app.py"]
        second += [f"{'> ' if n == 2 else '  '}{n} | code {n}" for n in range(1, 9)]
        self.assertEqual(self.file("cfg"), mergeatlas.CHECKER + "\n\n" + "\n".join(first) + "\n\n" + "\n".join(second))
        self.assertTrue(mergeatlas.CHECKER.endswith("\n\n---"))
        hashes = json.loads(self.file("cfg", "json"))
        self.assertEqual(hashes, [c["hash"] for c in mergeatlas.claims_of(data_of("Sets [the flag](cfg.txt#L10-L11) once. It reads [row](app.py#L2)."),
                                                                         self.files.get)["cfg"]])
        self.assertEqual([s["step"] for s in self.steps()], ["claims"])
        self.assertEqual(self.steps()[0]["links"], 2)

    def test_a_link_checked_before_is_not_written_again(self):
        self.work(data_of())
        self.assertEqual(self.printed(), ["cfg"])
        self.run_command(mergeatlas.checked, "o-r-7", ["cfg"])
        self.assertEqual(self.run_command(mergeatlas.claims, "o-r-7"), "nothing to check: every code link was checked against its lines\n")
        self.assertEqual(list((mergeatlas.WORK / "o-r-7.claims").iterdir()), [])
        self.assertEqual([s["step"] for s in self.steps()], ["claims", "checked"])

    def test_a_link_is_written_again_when_its_words_change(self):
        self.work(data_of())
        self.printed()
        self.run_command(mergeatlas.checked, "o-r-7", ["cfg"])
        self.edit(lambda d: d["cards"][0].update(summary="Sets [the switch](cfg.txt#L10-L11) once."))
        self.assertEqual(self.printed(), ["cfg"])

    def test_a_link_is_written_again_when_its_lines_change(self):
        self.work(data_of())
        self.printed()
        self.run_command(mergeatlas.checked, "o-r-7", ["cfg"])
        self.files["cfg.txt"][10] = "row eleven"
        self.assertEqual(self.printed(), ["cfg"])

    def test_a_link_whose_lines_only_moved_is_not_written_again(self):
        self.work(data_of())
        self.printed()
        self.run_command(mergeatlas.checked, "o-r-7", ["cfg"])
        self.files["cfg.txt"] = ["new top"] + self.files["cfg.txt"]
        self.edit(lambda d: d["cards"][0].update(summary="Sets [the flag](cfg.txt#L11-L12) once."))
        self.assertEqual(self.run_command(mergeatlas.claims, "o-r-7"), "nothing to check: every code link was checked against its lines\n")

    def test_a_link_shared_by_two_cards_is_written_once(self):
        data = data_of("Sets [the flag](cfg.txt#L10-L11) once.", background="See [the flag](cfg.txt#L10-L11).")
        data["cards"].append({**data["cards"][0], "id": "doc", "paths": ["doc.md"], "summary": "Sets [the flag](cfg.txt#L10-L11) once.",
                              "bullets": [], "changes": []})
        self.work(data)
        self.assertEqual(self.printed(), ["story"])
        self.assertEqual(len(json.loads(self.file("story", "json"))), 1)

    def test_an_arrow_s_links_go_with_the_card_it_leaves(self):
        data = data_of("Plain.")
        data["cards"].append({**data["cards"][0], "id": "doc", "paths": ["doc.md"], "summary": "Plain.", "bullets": [], "changes": []})
        data["edges"] = [{"from": "doc", "to": "cfg", "kind": "docs", "label": "L", "relationship": "Both use [it](app.py#L3).",
                          "connection": "x", "connection_code": "x", "connection_at": "app.py#L3", "flow": "Reads [row](cfg.txt#L5)."}]
        self.work(data)
        self.assertEqual(self.printed(), ["doc"])
        found = mergeatlas.claims_of(data, self.files.get)
        self.assertEqual([c["words"] for c in found["doc"]], ["it", "row"])
        self.assertEqual(found["cfg"], [])

    def test_all_writes_every_link(self):
        self.work(data_of())
        self.printed()
        self.run_command(mergeatlas.checked, "o-r-7", ["cfg"])
        self.assertEqual(self.printed(everything=True), ["cfg"])
        self.assertEqual([s["step"] for s in self.steps()], ["claims", "checked"])

    def test_a_stack_story_has_nothing_to_check(self):
        mergeatlas.WORK.mkdir(parents=True)
        (mergeatlas.WORK / "o-r-stack-9.stack.json").write_text("{}")
        self.assertEqual(self.run_command(mergeatlas.claims, "o-r-stack-9"),
                         "nothing to check: a stack story links pull requests, not code\n")
        self.assertFalse((mergeatlas.WORK / "o-r-stack-9.claims").exists())

    def test_finish_counts_every_link_as_checked(self):
        data = data_of()
        self.work(data)
        self.publish()
        self.run_command(mergeatlas.finish, "o-r-7")
        expected = sorted(c["hash"] for found in mergeatlas.claims_of(data, self.files.get).values() for c in found)
        self.assertEqual(len(expected), 1)
        self.assertEqual(json.loads((mergeatlas.WORK / "o-r-7.checked.json").read_text()), expected)
        self.assertEqual(self.run_command(mergeatlas.claims, "o-r-7"), "nothing to check: every code link was checked against its lines\n")

    def test_report_counts_the_links_checked_and_sent_back(self):
        self.work(data_of("Sets [the flag](cfg.txt#L10-L11) once. It reads [row](app.py#L2)."))
        self.printed()
        self.run_command(mergeatlas.checked, "o-r-7", ["cfg:2"])
        self.edit(lambda d: d["cards"][0].update(summary="Sets [the flag](cfg.txt#L10-L11) once. It reads [row](app.py#L3)."))
        self.printed()
        self.run_command(mergeatlas.checked, "o-r-7", ["cfg"])
        lines = mergeatlas.summary_of(self.steps())
        self.assertIn("claim checks   3 links checked over 2 rounds, 1 sent back", lines)


class CheckedLinks(Checking):
    def setUp(self):
        super().setUp()
        self.work(data_of("Sets [the flag](cfg.txt#L10-L11) once. It reads [row](app.py#L2). It has [three](app.py#L3)."))
        self.printed()

    def recorded(self):
        path = mergeatlas.WORK / "o-r-7.checked.json"
        return json.loads(path.read_text()) if path.exists() else []

    def test_checked_leaves_out_the_numbered_links(self):
        hashes = json.loads(self.file("cfg", "json"))
        self.assertEqual(self.run_command(mergeatlas.checked, "o-r-7", ["cfg:2"]), "checked: 2 links hold, 1 sent back\n")
        self.assertEqual(self.recorded(), sorted([hashes[0], hashes[2]]))
        self.assertEqual(self.steps()[-1]["ok"], 2)
        self.assertEqual(self.steps()[-1]["sent_back"], 1)
        self.assertEqual(self.printed(), ["cfg"])
        self.assertEqual(json.loads(self.file("cfg", "json")), [hashes[1]])

    def test_checked_refuses_a_number_the_file_does_not_hold(self):
        with self.assertRaises(SystemExit) as stopped:
            self.run_command(mergeatlas.checked, "o-r-7", ["cfg", "cfg:4"])
        self.assertEqual(str(stopped.exception), "cfg has no claim 4")
        with self.assertRaises(SystemExit) as stopped:
            self.run_command(mergeatlas.checked, "o-r-7", ["cfg", "story"])
        self.assertEqual(str(stopped.exception), "no claims file for story: run claims first")
        self.assertEqual(self.recorded(), [])
        self.assertEqual([s["step"] for s in self.steps()], ["claims"])


if __name__ == "__main__":
    unittest.main()
