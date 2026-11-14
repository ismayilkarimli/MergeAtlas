"""Stack detection: from the links a user gives, which PRs MergeAtlas maps and which stack they sit in.

Run from the repository root:
    python3 -m unittest discover -s tests

The fixture is stack #9 of ismayilkarimli/home-loan-calculator, eight open PRs captured from GitHub's API.
Set MERGEATLAS_LIVE=1 to also check the GitHub adapter against that repository itself (needs `gh` signed in).

The interface under test, in skills/mergeatlas/scripts/mergeatlas.py:
    parse_target(text)                       -> (kind, repo, number): kind is "pr" or "stack", repo is None for a bare number
    parse_fetch_args(args)                   -> (targets, whole_stack)
    resolve(targets, forge, whole_stack)     -> plan dict:
        repo:   "owner/name"
        stack:  None for a PR in no stack, else {number (None when found by branches), source ("native" or "branches"),
                base, prs (every PR in the stack, bottom to top)}
        map:    the PRs to map, bottom to top
        added:  PRs the user did not list but that sit between ones they did
    GitHub(): the forge over `gh`, with the methods FakeGitHub has below; tests/test_forge.py covers the rest of it
"""
import copy
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "mergeatlas" / "scripts"))
import mergeatlas  # noqa: E402

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "loan-calculator-stack.json").read_text())
REPO = FIXTURE["repo"]
STACK = [1, 2, 3, 4, 5, 6, 7, 8]


def pr(number, repo=REPO):
    return f"https://github.com/{repo}/pull/{number}"


def stack_link(number, repo=REPO):
    return f"https://github.com/{repo}/stack/{number}"


class FakeGitHub(mergeatlas.GitHub):
    """Answers from the fixture as GitHub answers from GitHub, and spells links as it does. With native=False the repository has no
    native stacks, as with one built by hand, by Graphite, or with plain branches."""

    def __init__(self, native=True, extra=(), merged=()):
        fixture = copy.deepcopy(FIXTURE)
        self.pulls = {p["number"]: p for p in [*fixture["pulls"], *copy.deepcopy(list(extra))]}
        self.stacks = {s["number"]: s for s in fixture["stacks"]} if native else {}
        for p in self.pulls.values():
            if not native:
                p["stack"] = None
            if p["number"] in merged:
                p["state"] = "merged"

    def _repo(self, repo):
        if repo != REPO:
            raise LookupError(f"no repository {repo}")

    def current_repo(self):
        return REPO

    def pull(self, repo, number):
        self._repo(repo)
        if number not in self.pulls:
            raise LookupError(f"no PR #{number} in {repo}")
        return copy.deepcopy(self.pulls[number])

    def stack(self, repo, number):
        self._repo(repo)
        if number not in self.stacks:
            raise LookupError(f"no stack #{number} in {repo}")
        return copy.deepcopy(self.stacks[number])

    def files(self, repo, number):
        """The paths a PR changes."""
        self._repo(repo)
        return list(FIXTURE["files"][str(number)])

    def pulls_with_head(self, repo, branch):
        """Every PR, in any state, whose head is branch."""
        self._repo(repo)
        return [copy.deepcopy(p) for p in self.pulls.values() if p["head"] == branch]

    def pulls_with_base(self, repo, branch):
        """Every PR, in any state, whose base is branch."""
        self._repo(repo)
        return [copy.deepcopy(p) for p in self.pulls.values() if p["base"] == branch]


def lone_pr(number, base="main", head=None):
    return {"number": number, "title": f"PR {number}", "url": pr(number), "state": "open",
            "base": base, "head": head or f"branch-{number}", "stack": None}


def resolve(args, whole_stack=False, **github):
    targets = [mergeatlas.parse_target(a) for a in args]
    return mergeatlas.resolve(targets, FakeGitHub(**github), whole_stack=whole_stack)


class ParseTarget(unittest.TestCase):
    def test_pr_link(self):
        self.assertEqual(mergeatlas.parse_target("https://github.com/o/r/pull/5"), ("pr", "o/r", 5))

    def test_pr_link_to_a_tab_or_anchor(self):
        for link in ("https://github.com/o/r/pull/5/files", "https://github.com/o/r/pull/5/files#diff-abc",
                     "https://github.com/o/r/pull/5/commits", "https://github.com/o/r/pull/5?w=1"):
            with self.subTest(link=link):
                self.assertEqual(mergeatlas.parse_target(link), ("pr", "o/r", 5))

    def test_pr_link_without_scheme_or_with_www(self):
        for link in ("github.com/o/r/pull/5", "http://github.com/o/r/pull/5", "https://www.github.com/o/r/pull/5"):
            with self.subTest(link=link):
                self.assertEqual(mergeatlas.parse_target(link), ("pr", "o/r", 5))

    def test_stack_link(self):
        self.assertEqual(mergeatlas.parse_target("https://github.com/o/r/stack/9"), ("stack", "o/r", 9))

    def test_bare_number_is_a_pr_in_the_current_repository(self):
        self.assertEqual(mergeatlas.parse_target("5"), ("pr", None, 5))
        self.assertEqual(mergeatlas.parse_target("#5"), ("pr", None, 5))

    def test_rejects_what_is_not_a_github_pr_or_stack(self):
        for text in ("https://gitlab.com/o/r/-/merge_requests/5", "https://github.com/o/r/issues/5",
                     "https://github.com/o/r", "five", ""):
            with self.subTest(text=text), self.assertRaises(ValueError):
                mergeatlas.parse_target(text)


class ParseFetchArgs(unittest.TestCase):
    def test_no_arguments_keeps_the_current_branch_pr(self):
        self.assertEqual(mergeatlas.parse_fetch_args([]), ([], False))

    def test_stack_flag_asks_for_the_whole_stack(self):
        targets, whole = mergeatlas.parse_fetch_args([pr(5), "--stack"])
        self.assertEqual((targets, whole), ([("pr", REPO, 5)], True))

    def test_several_links(self):
        targets, whole = mergeatlas.parse_fetch_args([pr(6), pr(8)])
        self.assertEqual((targets, whole), ([("pr", REPO, 6), ("pr", REPO, 8)], False))


class StackLink(unittest.TestCase):
    """A stack link always maps the whole stack."""

    def test_maps_every_pr_in_stack_order(self):
        plan = resolve([stack_link(9)])
        self.assertEqual(plan["repo"], REPO)
        self.assertEqual(plan["map"], STACK)
        self.assertEqual(plan["stack"], {"number": 9, "source": "native", "base": "main", "prs": STACK})
        self.assertEqual(plan["added"], [])

    def test_maps_the_whole_stack_even_when_asked_for_a_pr(self):
        self.assertEqual(resolve([stack_link(9)], whole_stack=False)["map"], STACK)

    def test_unknown_stack(self):
        with self.assertRaises(LookupError):
            resolve([stack_link(99)])


class PrLink(unittest.TestCase):
    """A PR link maps only that PR, unless the user asks for the stack."""

    def test_maps_only_that_pr_with_its_stack_as_context(self):
        plan = resolve([pr(5)])
        self.assertEqual(plan["map"], [5])
        self.assertEqual(plan["stack"], {"number": 9, "source": "native", "base": "main", "prs": STACK})

    def test_bottom_and_top_of_the_stack(self):
        self.assertEqual(resolve([pr(1)])["map"], [1])
        self.assertEqual(resolve([pr(8)])["map"], [8])
        self.assertEqual(resolve([pr(8)])["stack"]["prs"], STACK)

    def test_asked_for_the_stack_maps_the_whole_stack(self):
        self.assertEqual(resolve([pr(5)], whole_stack=True)["map"], STACK)

    def test_bare_number_uses_the_current_repository(self):
        plan = resolve(["5"])
        self.assertEqual((plan["repo"], plan["map"]), (REPO, [5]))

    def test_pr_in_no_stack(self):
        plan = resolve([pr(11)], extra=[lone_pr(11)])
        self.assertEqual((plan["map"], plan["stack"]), ([11], None))

    def test_pr_in_no_stack_asked_for_the_stack_maps_just_that_pr(self):
        plan = resolve([pr(11)], whole_stack=True, extra=[lone_pr(11)])
        self.assertEqual((plan["map"], plan["stack"]), ([11], None))


class PrList(unittest.TestCase):
    """A list of PR links maps those PRs as part of their stack, bottom to top."""

    def test_ordered_by_the_stack_not_by_the_list(self):
        plan = resolve([pr(8), pr(6), pr(7)])
        self.assertEqual((plan["map"], plan["added"]), ([6, 7, 8], []))

    def test_fills_a_gap_and_says_so(self):
        plan = resolve([pr(6), pr(8)])
        self.assertEqual((plan["map"], plan["added"]), ([6, 7, 8], [7]))

    def test_same_pr_twice(self):
        self.assertEqual(resolve(["5", pr(5)])["map"], [5])

    def test_links_from_two_repositories(self):
        with self.assertRaisesRegex(ValueError, "repositor"):
            resolve([pr(5), pr(6, repo="someone/else")])

    def test_prs_from_different_stacks(self):
        with self.assertRaisesRegex(ValueError, "#11"):
            resolve([pr(5), pr(11)], extra=[lone_pr(11)])

    def test_rejects_a_merged_pr(self):
        with self.assertRaisesRegex(ValueError, "#1 .*merged"):
            resolve([pr(1), pr(2)], merged={1})


class MergedBase(unittest.TestCase):
    """Merged PRs stay in the stack as context, but have nothing left to review."""

    def test_whole_stack_leaves_out_merged_prs(self):
        plan = resolve([stack_link(9)], merged={1, 2})
        self.assertEqual(plan["map"], [3, 4, 5, 6, 7, 8])
        self.assertEqual(plan["stack"]["prs"], STACK)


class StackFoundByBranches(unittest.TestCase):
    """With no native stack, each PR's base branch is the head branch of the PR below it."""

    def test_pr_link_finds_the_same_stack_by_branches(self):
        plan = resolve([pr(5)], native=False)
        self.assertEqual(plan["map"], [5])
        self.assertEqual(plan["stack"], {"number": None, "source": "branches", "base": "main", "prs": STACK})

    def test_asked_for_the_stack(self):
        self.assertEqual(resolve([pr(5)], whole_stack=True, native=False)["map"], STACK)

    def test_list_in_any_order_with_a_gap(self):
        plan = resolve([pr(8), pr(6)], native=False)
        self.assertEqual((plan["map"], plan["added"]), ([6, 7, 8], [7]))

    def test_matches_the_native_stack(self):
        for args, whole in (([pr(1)], False), ([pr(5)], True), ([pr(8)], False), ([pr(3), pr(6)], False)):
            with self.subTest(args=args, whole=whole):
                native, branches = resolve(args, whole, native=True), resolve(args, whole, native=False)
                self.assertEqual((native["map"], native["stack"]["prs"], native["added"]),
                                 (branches["map"], branches["stack"]["prs"], branches["added"]))

    def test_a_fork_cannot_be_mapped_as_one_stack(self):
        # PR 10 also builds on #5's branch, so above #5 the chain splits into #6 and #10
        fork = lone_pr(10, base="05-contact-page", head="05b-newsletter")
        with self.assertRaisesRegex(ValueError, r"#6.*#10|#10.*#6"):
            resolve([pr(5)], whole_stack=True, native=False, extra=[fork])

    def test_a_fork_above_still_lets_a_single_pr_be_mapped(self):
        fork = lone_pr(10, base="05-contact-page", head="05b-newsletter")
        plan = resolve([pr(3)], native=False, extra=[fork])
        self.assertEqual((plan["map"], plan["stack"]["prs"][:3]), ([3], [1, 2, 3]))


class StackContext(unittest.TestCase):
    """What fetch records for each mapped PR about the stack around it."""

    def test_mid_stack_pr(self):
        context = mergeatlas.stack_context(resolve([pr(5)]), 5)
        self.assertEqual(context, {"number": 9, "source": "native", "base": "main", "prs": STACK,
                                   "position": 5, "below": 4, "above": 6})

    def test_bottom_and_top(self):
        plan = resolve([stack_link(9)])
        self.assertEqual((mergeatlas.stack_context(plan, 1)["below"], mergeatlas.stack_context(plan, 1)["above"]), (None, 2))
        self.assertEqual((mergeatlas.stack_context(plan, 8)["below"], mergeatlas.stack_context(plan, 8)["above"]), (7, None))

    def test_pr_in_no_stack(self):
        self.assertIsNone(mergeatlas.stack_context(resolve([pr(11)], extra=[lone_pr(11)]), 11))


@unittest.skipUnless(os.environ.get("MERGEATLAS_LIVE"), "set MERGEATLAS_LIVE=1 to call GitHub")
class LiveGitHub(unittest.TestCase):
    """The real adapter answers as the fixture does, so the fake stays honest."""

    def setUp(self):
        self.github = mergeatlas.GitHub()

    def test_stack(self):
        self.assertEqual(self.github.stack(REPO, 9), FIXTURE["stacks"][0])

    def test_pull(self):
        for expected in FIXTURE["pulls"]:
            with self.subTest(number=expected["number"]):
                self.assertEqual(self.github.pull(REPO, expected["number"]), expected)

    def test_pulls_by_branch(self):
        self.assertEqual([p["number"] for p in self.github.pulls_with_head(REPO, "05-contact-page")], [5])
        self.assertEqual([p["number"] for p in self.github.pulls_with_base(REPO, "05-contact-page")], [6])

    def test_resolves_the_stack_end_to_end(self):
        plan = mergeatlas.resolve([mergeatlas.parse_target(pr(5))], self.github, whole_stack=False)
        self.assertEqual((plan["map"], plan["stack"]["number"], plan["stack"]["prs"]), ([5], 9, STACK))


if __name__ == "__main__":
    unittest.main()
