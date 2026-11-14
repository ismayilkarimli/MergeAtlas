"""The forge: everything MergeAtlas asks of the host a pull request lives on, so another host is another class.

Run from the repository root:
    python3 -m unittest discover -s tests

Nothing here calls GitHub: `gh` is replaced by canned answers, and the tests check what the forge asks of it and how it
reshapes the answers. The stack queries are covered in test_stack_detection.py.

The interface under test, in skills/mergeatlas/scripts/mergeatlas.py:
    forge_for(link)                  -> the forge a link, or the clone's origin when there is none, belongs to
    GitHub.name, .label              -> "github", used in map ids, and "GitHub", shown to the reader
    GitHub.current_pr()              -> the current branch's PR number, None when it has none
    GitHub.pr_record(repo, number)   -> the PR as pr.json keeps it, before the clone adds its files and line counts
    GitHub.fetch_ref(number)         -> what to fetch from origin to get the PR's head commit
    GitHub.status(url)               -> {head, state} now, state being open, closed or merged; {} when it cannot be told
    GitHub.repo_of(url)              -> the owner/name a PR link is in
    GitHub.links(url, paths)         -> the templates the viewer builds every address on the host from
    map_id_of(forge, repo, number)   -> the map's id, which starts with the forge's name
"""
import json
import subprocess
import unittest
from unittest import mock

from test_stack_detection import mergeatlas

FORGE = mergeatlas.GitHub()
URL = "https://github.com/o/r/pull/7"


def answers(canned):
    """A stand-in for gh that answers by its arguments and records them."""
    asked = []

    def gh(*args):
        asked.append(args)
        for start, answer in canned:
            if args[:len(start)] == start:
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise AssertionError(f"unexpected gh call {args}")
    return gh, asked


class WhichForge(unittest.TestCase):
    def test_github_is_the_only_forge_so_far(self):
        for link in (None, "7", URL, "https://github.com/o/r/stack/9"):
            self.assertEqual(mergeatlas.forge_for(link).name, "github")

    def test_a_forge_names_itself_for_ids_and_for_readers(self):
        self.assertEqual((FORGE.name, FORGE.label), ("github", "GitHub"))

    def test_ids_start_with_the_forge(self):
        self.assertEqual(mergeatlas.map_id_of(FORGE, "o/r", 7), "github-o-r-7")
        self.assertEqual(mergeatlas.stack_id(FORGE, "o/r", {"number": 9, "prs": [1, 2]}), "github-o-r-stack-9")
        self.assertTrue(mergeatlas.MAP_ID.fullmatch(mergeatlas.map_id_of(FORGE, "o/r.js", 7)))

    def test_a_link_is_read_by_the_forge(self):
        self.assertEqual(mergeatlas.parse_target(URL), FORGE.parse_target(URL))
        self.assertEqual(FORGE.repo_of(URL), "o/r")
        self.assertEqual(FORGE.repo_of("https://example.com/elsewhere"), "")


class Asking(unittest.TestCase):
    def test_the_current_branchs_pr(self):
        gh, asked = answers([(("pr", "view"), "12\n")])
        with mock.patch.object(mergeatlas, "gh", gh):
            self.assertEqual(FORGE.current_pr(), 12)
        self.assertEqual(asked, [("pr", "view", "--json", "number", "--jq", ".number")])

    def test_a_branch_with_no_pr_has_none(self):
        gh, _ = answers([(("pr", "view"), subprocess.CalledProcessError(1, "gh"))])
        with mock.patch.object(mergeatlas, "gh", gh):
            self.assertIsNone(FORGE.current_pr())

    def test_a_pr_record_keeps_pr_jsons_field_names_and_reads_the_issues_it_closes(self):
        pr = {"number": 7, "title": "T", "body": "B", "url": URL, "headRefName": "br", "headRefOid": "h" * 40,
              "baseRefName": "main", "baseRefOid": "b" * 40, "closingIssuesReferences": [{"number": 3}]}
        issue = {"number": 3, "title": "I", "body": "IB", "url": "https://github.com/o/r/issues/3"}
        gh, asked = answers([(("pr", "view"), json.dumps(pr)), (("issue", "view"), json.dumps(issue))])
        with mock.patch.object(mergeatlas, "gh", gh):
            record = FORGE.pr_record("o/r", 7)
        self.assertEqual(record, {**{k: v for k, v in pr.items() if k != "closingIssuesReferences"}, "issues": [issue]})
        fields = asked[0][asked[0].index("--json") + 1].split(",")
        self.assertNotIn("files", fields)
        self.assertNotIn("additions", fields)
        self.assertEqual(asked[1][:5], ("issue", "view", "3", "--repo", "o/r"))

    def test_a_prs_head_is_fetched_from_its_pull_ref(self):
        self.assertEqual(FORGE.fetch_ref(7), "pull/7/head")


class Status(unittest.TestCase):
    def status(self, url=URL, stdout='{"head": "h", "state": "merged"}', returncode=0, error=None):
        done = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")
        with mock.patch.object(mergeatlas.subprocess, "run", return_value=done, side_effect=error) as run:
            return FORGE.status(url), run

    def test_it_asks_gh_with_a_timeout_of_fifteen_seconds(self):
        now, run = self.status()
        self.assertEqual(now, {"head": "h", "state": "merged"})
        self.assertEqual(run.call_args.args[0][:3], ["gh", "api", "repos/o/r/pulls/7"])
        self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_another_github_host_is_asked_by_name(self):
        _, run = self.status("https://git.example.com/o/r/pull/7")
        self.assertEqual(run.call_args.args[0][:5], ["gh", "api", "--hostname", "git.example.com", "repos/o/r/pulls/7"])

    def test_it_answers_nothing_when_it_cannot_tell(self):
        self.assertEqual(self.status(returncode=1, stdout="")[0], {})
        self.assertEqual(self.status(stdout="not json")[0], {})
        self.assertEqual(self.status(error=subprocess.TimeoutExpired("gh", 15))[0], {})
        self.assertEqual(self.status("https://example.com/elsewhere")[0], {})


class Links(unittest.TestCase):
    def test_the_templates_for_a_pr_and_its_files(self):
        links = FORGE.links(URL, ["src/a.py"])
        self.assertEqual(links, {
            "host": "GitHub", "pr": URL, "ref": "#{n}",
            "diff": f"{URL}/files#diff-{{key}}", "diff_line": "{side}{first}", "diff_range": "{side}{first}-{side}{last}",
            "blob": "https://github.com/o/r/blob/{sha}/{path}", "blob_line": "#L{first}", "blob_range": "#L{first}-L{last}",
            "commit": "https://github.com/o/r/commit/{sha}", "tree": "https://github.com/o/r/tree/{ref}",
            "pr_number": "https://github.com/o/r/pull/{n}",
            "keys": {"src/a.py": FORGE.diff_key("src/a.py")},
        })

    def test_a_files_diff_key_is_the_hash_of_its_path(self):
        self.assertEqual(FORGE.diff_key("a"), "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb")


if __name__ == "__main__":
    unittest.main()
