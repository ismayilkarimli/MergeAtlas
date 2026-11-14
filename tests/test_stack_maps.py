"""Stack maps: what ties the maps of one stack together once each PR has its own map.

Run from the repository root:
    python3 -m unittest discover -s tests

The interface under test, in skills/mergeatlas/scripts/mergeatlas.py:
    stack_id(forge, repo, stack)                -> the stack page's map id, which starts with the forge's name
    stack_record(plan, forge)                   -> {id, repo, number, base, source, url,
                                                    prs: [{number, title, url, state, map_id, files}]}, bottom to top
    stack_labels(record, number)                -> {path: "changed in #N below, #M above"} for files other PRs change
    stack_strip(record, number, published)      -> what a map shows of its stack: {id, number, url, page, prs}
    stubs_for(data, record, number, maps)       -> the "From #N" stubs: files a card links to that a PR below changed
    stack_problems(data, record)                -> what is wrong with a stack story
    stack_page(data, record, maps)              -> the published stack page
"""
import copy
import unittest

from test_stack_detection import FIXTURE, REPO, FakeGitHub, mergeatlas, pr, stack_link

STACK_ID = "github-ismayilkarimli-home-loan-calculator-stack-9"


def map_id(n):
    return f"github-ismayilkarimli-home-loan-calculator-{n}"


def record(**kw):
    github = FakeGitHub(**kw)
    plan = mergeatlas.resolve([mergeatlas.parse_target(stack_link(9) if kw.get("native", True) else pr(1))], github,
                              whole_stack=True)
    return mergeatlas.stack_record(plan, github)


class StackRecord(unittest.TestCase):
    def test_native_stack_id_names_the_stack(self):
        self.assertEqual(mergeatlas.stack_id(FakeGitHub(), REPO, {"number": 9, "prs": [1, 2]}), STACK_ID)

    def test_branch_stack_id_names_its_ends(self):
        self.assertEqual(mergeatlas.stack_id(FakeGitHub(), REPO, {"number": None, "prs": [3, 4, 5]}),
                         "github-ismayilkarimli-home-loan-calculator-stack-3-5")

    def test_record_lists_every_pr_bottom_to_top_with_its_files(self):
        r = record()
        self.assertEqual(r["id"], STACK_ID)
        self.assertEqual((r["repo"], r["number"], r["base"], r["source"]), (REPO, 9, "main", "native"))
        self.assertEqual(r["url"], stack_link(9))
        self.assertEqual([p["number"] for p in r["prs"]], [1, 2, 3, 4, 5, 6, 7, 8])
        first = r["prs"][0]
        self.assertEqual(first["map_id"], map_id(1))
        self.assertEqual(first["title"], "Add landing page, shared layout and navigation")
        self.assertEqual(first["url"], pr(1))
        self.assertEqual(first["state"], "open")
        self.assertEqual(first["files"], FIXTURE["files"]["1"])

    def test_branch_stack_has_no_stack_url(self):
        r = record(native=False)
        self.assertIsNone(r["number"])
        self.assertIsNone(r["url"])
        self.assertEqual(r["id"], "github-ismayilkarimli-home-loan-calculator-stack-1-8")

    def test_record_keeps_a_merged_pr(self):
        self.assertEqual(record(merged=[1])["prs"][0]["state"], "merged")


class StackLabels(unittest.TestCase):
    def test_labels_name_the_prs_below_and_above_that_change_a_file(self):
        labels = mergeatlas.stack_labels(record(), 3)
        self.assertEqual(labels["about.html"], "changed in #2 below")
        self.assertEqual(labels["css/styles.css"], "changed in #1 below, #4, #5, #6, #7 above")

    def test_files_this_pr_changes_get_no_label(self):
        labels = mergeatlas.stack_labels(record(), 6)
        self.assertNotIn("js/nav.js", labels)
        self.assertNotIn("calculator.html", labels)

    def test_bottom_pr_sees_only_prs_above(self):
        labels = mergeatlas.stack_labels(record(), 1)
        self.assertEqual(labels["about.html"], "changed in #2 above")
        self.assertEqual(labels["js/loan.js"], "changed in #6, #7, #8 above")


class StackStrip(unittest.TestCase):
    def test_strip_marks_the_current_pr_and_which_maps_are_published(self):
        strip = mergeatlas.stack_strip(record(), 6, {map_id(1), map_id(6)})
        self.assertEqual((strip["id"], strip["number"], strip["url"]), (STACK_ID, 9, stack_link(9)))
        self.assertFalse(strip["page"])
        self.assertEqual([p["number"] for p in strip["prs"]], [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual([p["number"] for p in strip["prs"] if p["current"]], [6])
        self.assertEqual([p["number"] for p in strip["prs"] if p["published"]], [1, 6])
        self.assertEqual(strip["prs"][0], {"number": 1, "title": "Add landing page, shared layout and navigation",
                                           "url": pr(1), "state": "open", "map_id": map_id(1),
                                           "current": False, "published": True})

    def test_strip_knows_when_the_stack_page_is_published(self):
        self.assertTrue(mergeatlas.stack_strip(record(), 6, {STACK_ID})["page"])


def card(cid, paths, summary="", changes=(), reaches=(), unaffected=()):
    return {"id": cid, "kind": "core", "title": cid, "paths": paths, "summary": summary,
            "changes": [{"problem": "", "change": c, "result": ""} for c in changes],
            "reaches": list(reaches), "unaffected": list(unaffected)}


class Stubs(unittest.TestCase):
    """PR #8 extends the calculator. Its cards link to code that PRs below it wrote."""

    def setUp(self):
        self.data = {"cards": [
            card("calc", ["js/calculator.js"], summary="Builds on [the shared nav](js/nav.js#L3-L9).",
                 changes=["Reads [the about link](about.html#L4) and [the nav again](js/nav.js#L12)."]),
            card("page", ["calculator.html"], changes=["Uses [the layout](css/styles.css#L1-L20)."],
                 reaches=[{"paths": ["contact.html"], "effect": "Links [the contact form](contact.html#L8)."}]),
            card("loan", ["js/loan.js"], summary="Calls [its own helper](js/loan.js#L2)."),
        ]}
        parent = {"cards": [{"id": "about-page", "paths": ["about.html"]}]}
        self.stubs = mergeatlas.stubs_for(self.data, record(), 8, {map_id(2): parent})

    def by_path(self):
        return {s["path"]: s for s in self.stubs}

    def test_stub_for_each_linked_file_a_pr_below_changed(self):
        self.assertEqual(sorted(self.by_path()), ["about.html", "contact.html", "css/styles.css", "js/nav.js"])

    def test_files_this_pr_changes_get_no_stub(self):
        self.assertNotIn("js/loan.js", self.by_path())

    def test_stub_points_at_the_nearest_pr_below(self):
        styles = self.by_path()["css/styles.css"]
        self.assertEqual((styles["pr"], styles["map_id"]), (7, map_id(7)))
        self.assertEqual(self.by_path()["js/nav.js"]["pr"], 6)

    def test_stub_links_the_parent_card_when_that_map_is_published(self):
        about = self.by_path()["about.html"]
        self.assertEqual(about, {"id": "from:about.html", "path": "about.html", "pr": 2, "map_id": map_id(2),
                                 "title": FakeGitHub().pulls[2]["title"], "card_id": "about-page",
                                 "cited_by": ["calc"]})
        self.assertIsNone(self.by_path()["css/styles.css"]["card_id"])

    def test_stub_lists_every_card_citing_it_once(self):
        self.data["cards"][2]["summary"] += " Styled by [the layout](css/styles.css#L4)."
        stubs = mergeatlas.stubs_for(self.data, record(), 8, {})
        self.assertEqual({s["path"]: s["cited_by"] for s in stubs}["css/styles.css"], ["page", "loan"])

    def test_files_a_card_reaches_count_as_cited(self):
        self.data["cards"][1]["reaches"].append({"paths": ["pricing.html"], "effect": "Links it."})
        stubs = mergeatlas.stubs_for(self.data, record(), 8, {})
        self.assertEqual({s["path"]: s["cited_by"] for s in stubs}["pricing.html"], ["page"])

    def test_a_pr_with_nothing_below_gets_no_stubs(self):
        self.assertEqual(mergeatlas.stubs_for(self.data, record(), 1, {}), [])

    def test_no_stack_no_stubs(self):
        self.assertEqual(mergeatlas.stubs_for(self.data, None, 8, {}), [])


def story(solution=None):
    links = " ".join(f"[part {n}](#{n})." for n in range(1, 9))
    return {"background": "The site is static HTML.", "problem": "There is no calculator.",
            "solution": links if solution is None else solution}


class StackStory(unittest.TestCase):
    def test_a_complete_story_has_no_problems(self):
        self.assertEqual(mergeatlas.stack_problems(story(), record()), [])

    def test_story_needs_all_three_parts(self):
        data = story()
        del data["background"]
        data["problem"] = " "
        problems = mergeatlas.stack_problems(data, record())
        self.assertTrue(any("background" in p for p in problems))
        self.assertTrue(any("problem" in p for p in problems))

    def test_solution_links_every_pr(self):
        problems = mergeatlas.stack_problems(story("[part one](#1). [part two](#2)."), record())
        self.assertTrue(any("#3" in p and "#8" in p for p in problems), problems)

    def test_solution_links_only_prs_in_the_stack(self):
        problems = mergeatlas.stack_problems(story(story()["solution"] + " [other](#42)."), record())
        self.assertTrue(any("#42" in p for p in problems), problems)

    def test_story_reasons_close_like_a_map_story(self):
        data = story()
        data["problem"] = "The page breaks because it is wrong."
        self.assertTrue(any("because" in p for p in mergeatlas.stack_problems(data, record())))


class StackPage(unittest.TestCase):
    def test_page_carries_the_story_and_each_pr_with_its_intents(self):
        intents = [{"id": "a", "title": "Let a buyer price a loan"}, {"id": "m", "title": "Tidy", "mechanical": True}]
        maps = {map_id(6): {"intents": intents}}
        page = mergeatlas.stack_page(story(), record(), maps)
        self.assertEqual(page["kind"], "stack")
        self.assertEqual(page["stack"], {"id": STACK_ID, "repo": REPO, "number": 9, "base": "main", "url": stack_link(9)})
        self.assertEqual(page["links"], mergeatlas.GitHub().links(pr(1)))
        self.assertEqual(page["background"], story()["background"])
        self.assertEqual(page["solution"], story()["solution"])
        six = page["prs"][5]
        self.assertEqual(six, {"number": 6, "title": FakeGitHub().pulls[6]["title"], "url": pr(6), "state": "open",
                               "map_id": map_id(6), "published": True, "intents": ["Let a buyer price a loan"],
                               "files": len(FIXTURE["files"]["6"])})
        self.assertFalse(page["prs"][0]["published"])
        self.assertEqual(page["prs"][0]["intents"], [])

    def test_page_does_not_change_the_record(self):
        r = record()
        before = copy.deepcopy(r)
        mergeatlas.stack_page(story(), r, {})
        self.assertEqual(r, before)


if __name__ == "__main__":
    unittest.main()
