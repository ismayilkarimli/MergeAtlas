"""GitLab: merge requests through the glab CLI, so fetch, publish and stacks work on gitlab.com and a self-hosted GitLab.

Run from the repository root:
    python3 -m unittest discover -s tests

Nothing here calls GitLab or needs glab: `glab` and the git remote are replaced by canned answers, and the tests check what
the forge asks and how it reshapes what GitLab says. The answers are real: tests/fixtures/gitlab-merge-request.json holds a
merge request and the issues one closes as GitLab's API returned them, trimmed to the fields MergeAtlas reads. How the
viewer opens GitLab's links is tested beside GitHub's in test_release.py.

The interface under test, in skills/mergeatlas/scripts/mergeatlas.py, is GitHub's, with a host to aim glab at:
    GitLab(host).parse_target(text)  -> ("pr", project path, IID); a project path may nest groups to any depth
    forge_for(link)                  -> GitLab for a merge request link, and for a link-less fetch when the origin remote is
                                        on gitlab.com or a host with "gitlab" in its name
    forge_of(args)                   -> the one forge a fetch's links name, an error when they name more
    GitLab.pr_record, .pull, .pulls_with_head, .pulls_with_base, .files, .fetch_ref, .status, .links
"""
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from test_stack_detection import mergeatlas

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "gitlab-merge-request.json").read_text())
MR = FIXTURE["merge_request"]
GROUP, PROJECT = "g/s", "g/s/p"
ENCODED = "g%2Fs%2Fp"
URL = f"https://gitlab.com/{PROJECT}/-/merge_requests/7"
FORGE = mergeatlas.GitLab()


def merge_request(iid, source, target, state="opened", **more):
    return {"iid": iid, "title": f"MR {iid}", "web_url": f"https://gitlab.com/{PROJECT}/-/merge_requests/{iid}",
            "state": state, "source_branch": source, "target_branch": target,
            "source_project_id": 1, "target_project_id": 1, **more}


def fake_glab(merge_requests=(), others=None):
    """A stand-in for glab that answers an API path from merge requests, as GitLab lists them by branch, or from `others`,
    and records every call."""
    asked, others = [], others or {}

    def glab(*args):
        asked.append(args)
        path = args[-1]
        if path in others:
            if isinstance(others[path], Exception):
                raise others[path]
            return json.dumps(others[path])
        asked_url = urlsplit(path)
        query = parse_qs(asked_url.query)
        if asked_url.path == f"projects/{ENCODED}/merge_requests":
            found = [m for m in merge_requests
                     if all(m[key] == value[0] for key, value in query.items() if key in ("source_branch", "target_branch"))]
            return json.dumps(found)
        for m in merge_requests:
            if asked_url.path == f"projects/{ENCODED}/merge_requests/{m['iid']}":
                return json.dumps(m)
        raise AssertionError(f"unexpected glab call {args}")
    return glab, asked


def origin_at(url):
    """A git whose origin remote is url."""
    if url is None:
        return mock.patch.object(mergeatlas.subprocess, "run", side_effect=subprocess.CalledProcessError(2, "git"))
    done = subprocess.CompletedProcess([], 0, stdout=url + "\n", stderr="")
    return mock.patch.object(mergeatlas.subprocess, "run", return_value=done)


class Links(unittest.TestCase):
    def test_a_merge_request_link_names_its_host_project_and_iid(self):
        for link, repo in [(URL, PROJECT), ("https://gitlab.com/a/b/c/d/-/merge_requests/7", "a/b/c/d"),
                           ("https://gitlab.com/solo/project/-/merge_requests/7", "solo/project"),
                           (f"gitlab.com/{PROJECT}/-/merge_requests/7", PROJECT)]:
            with self.subTest(link=link):
                self.assertEqual(FORGE.parse_target(link), ("pr", repo, 7))

    def test_the_diffs_page_a_query_and_a_fragment_may_follow(self):
        for tail in ("/diffs", "/diffs?file_path=a.py#line_abc_3", "?tab=changes", "#note_5", "/"):
            with self.subTest(tail=tail):
                self.assertEqual(FORGE.parse_target(URL + tail), ("pr", PROJECT, 7))

    def test_a_self_hosted_host_is_kept_with_its_port(self):
        forge = mergeatlas.forge_for("https://git.example.com:8443/team/app/-/merge_requests/12/diffs")
        self.assertEqual((forge.name, forge.host), ("gitlab", "git.example.com:8443"))
        self.assertEqual(forge.parse_target("https://git.example.com:8443/team/app/-/merge_requests/12"), ("pr", "team/app", 12))

    def test_a_bare_number_has_no_project(self):
        self.assertEqual(FORGE.parse_target("7"), ("pr", None, 7))
        self.assertEqual(mergeatlas.parse_target("#7"), ("pr", None, 7))

    def test_what_is_not_a_merge_request_is_refused(self):
        for text in ("https://gitlab.com/g/p/-/issues/7", "https://gitlab.com/g/p/merge_requests/7", "https://gitlab.com/g/-/merge_requests/7",
                     "https://github.com/o/r/pull/7", "seven", ""):
            with self.subTest(text=text), self.assertRaises(ValueError):
                FORGE.parse_target(text)

    def test_the_project_of_a_link_is_read_by_the_forge(self):
        self.assertEqual(FORGE.repo_of(URL), PROJECT)
        self.assertEqual(FORGE.repo_of("https://gitlab.com/g/p/-/issues/7"), "")

    def test_a_merge_request_link_is_read_by_the_module_too(self):
        self.assertEqual(mergeatlas.parse_target(URL + "/diffs"), ("pr", PROJECT, 7))


class WhichForge(unittest.TestCase):
    def test_a_link_names_its_forge_without_a_look_at_the_clone(self):
        with origin_at("https://github.com/o/r.git") as run:
            self.assertEqual(mergeatlas.forge_for(URL).name, "gitlab")
            self.assertEqual(mergeatlas.forge_for("https://github.com/o/r/pull/7").name, "github")
            self.assertEqual(mergeatlas.forge_for("https://ghe.example.com/o/r/pull/7").name, "github")
        run.assert_not_called()

    def test_no_link_goes_by_the_origin_remote(self):
        for remote, name, host in [
            ("https://github.com/o/r.git", "github", "github.com"),
            ("git@github.com:o/r.git", "github", "github.com"),
            ("https://gitlab.com/g/s/p.git", "gitlab", "gitlab.com"),
            ("git@gitlab.com:g/s/p.git", "gitlab", "gitlab.com"),
            ("ssh://git@gitlab.com/g/s/p.git", "gitlab", "gitlab.com"),
            ("ssh://git@gitlab.example.com:2222/g/s/p.git", "gitlab", "gitlab.example.com"),
            ("https://oauth2:token@code.gitlab.example.org/g/p", "gitlab", "code.gitlab.example.org"),
            ("https://git.example.com/o/r.git", "github", "github.com"),
            ("git@git.example.com:o/r.git", "github", "github.com"),
        ]:
            with self.subTest(remote=remote), origin_at(remote):
                forge = mergeatlas.forge_for()
                self.assertEqual((forge.name, forge.host), (name, host))

    def test_a_bare_number_goes_by_the_origin_remote_too(self):
        with origin_at("git@gitlab.com:g/s/p.git"):
            self.assertEqual(mergeatlas.forge_for("7").name, "gitlab")

    def test_a_clone_with_no_origin_is_taken_for_github(self):
        with origin_at(None):
            self.assertEqual(mergeatlas.forge_for().name, "github")

    def test_the_origin_is_split_into_host_and_project_path(self):
        for remote, found in [("git@gitlab.com:g/s/p.git", ("gitlab.com", PROJECT)),
                              ("ssh://git@git.example.com:2222/g/s/p.git", ("git.example.com", PROJECT)),
                              ("https://gitlab.com/g/s/p/", ("gitlab.com", PROJECT)),
                              ("https://user:pw@gitlab.com/g/p.git", ("gitlab.com", "g/p")),
                              ("git@host:123/repo.git", ("host", "123/repo")),
                              ("/srv/git/repo.git", None)]:
            with self.subTest(remote=remote), origin_at(remote):
                self.assertEqual(mergeatlas.origin(), found)

    def test_the_current_repo_is_the_origins_project_path(self):
        with origin_at("git@gitlab.com:g/s/p.git"):
            self.assertEqual(FORGE.current_repo(), PROJECT)
        with origin_at(None), self.assertRaises(LookupError):
            FORGE.current_repo()


class OneForgePerFetch(unittest.TestCase):
    def test_links_on_two_forges_are_an_error(self):
        with self.assertRaisesRegex(ValueError, "more than one forge"):
            mergeatlas.forge_of([URL, "https://github.com/o/r/pull/7"])

    def test_links_on_two_gitlab_hosts_are_an_error(self):
        with self.assertRaisesRegex(ValueError, "more than one forge"):
            mergeatlas.forge_of([URL, "https://git.example.com/g/p/-/merge_requests/7"])

    def test_numbers_and_flags_follow_the_link(self):
        with origin_at("https://github.com/o/r.git"):
            forge = mergeatlas.forge_of(["8", URL, "--stack", "#9"])
        self.assertEqual((forge.name, forge.host), ("gitlab", "gitlab.com"))

    def test_numbers_alone_follow_the_origin(self):
        with origin_at("git@gitlab.com:g/s/p.git"):
            self.assertEqual(mergeatlas.forge_of(["8"]).name, "gitlab")
            self.assertEqual(mergeatlas.forge_of([]).name, "gitlab")


class Ids(unittest.TestCase):
    def test_ids_start_with_the_forge_and_hold_the_whole_project_path(self):
        self.assertEqual(mergeatlas.map_id_of(FORGE, PROJECT, 7), "gitlab-g-s-p-7")
        self.assertEqual(mergeatlas.stack_id(FORGE, PROJECT, {"number": None, "prs": [3, 5, 7]}), "gitlab-g-s-p-stack-3-7")
        self.assertTrue(mergeatlas.MAP_ID.fullmatch(mergeatlas.map_id_of(FORGE, "a/b.c/d-e/f_g", 7)))
        self.assertTrue(mergeatlas.MAP_ID.fullmatch(mergeatlas.stack_id(FORGE, "a/b/c/d", {"number": None, "prs": [3, 7]})))


class Asking(unittest.TestCase):
    def record(self, issues=None, **changed):
        mr = {**MR, **changed}
        path = f"projects/gitlab-org%2Fcli/merge_requests/{mr['iid']}"
        glab, asked = fake_glab(others={path: mr, f"{path}/closes_issues": FIXTURE["closes_issues"] if issues is None else issues})
        with mock.patch.object(mergeatlas, "glab", glab):
            return FORGE.pr_record("gitlab-org/cli", mr["iid"]), asked

    def test_a_pr_record_keeps_pr_jsons_field_names(self):
        record, asked = self.record()
        self.assertEqual(record["number"], 4420)
        self.assertEqual(record["title"], MR["title"])
        self.assertEqual(record["body"], MR["description"])
        self.assertEqual((record["headRefName"], record["baseRefName"]), ("dgruzd/orbit-not-installed-hint", "main"))
        self.assertEqual(record["url"], "https://gitlab.com/gitlab-org/cli/-/merge_requests/4420")
        self.assertEqual([a[-1] for a in asked], ["projects/gitlab-org%2Fcli/merge_requests/4420",
                                                  "projects/gitlab-org%2Fcli/merge_requests/4420/closes_issues"])

    def test_the_head_is_the_head_and_the_base_the_commit_it_branched_from(self):
        record, _ = self.record()
        self.assertEqual(record["headRefOid"], MR["diff_refs"]["head_sha"])
        self.assertEqual(record["baseRefOid"], MR["diff_refs"]["base_sha"])

    def test_the_issues_it_closes_are_kept_by_their_iid(self):
        record, _ = self.record()
        (issue,) = record["issues"]
        closed = FIXTURE["closes_issues"][0]
        self.assertEqual(issue, {"number": 8746, "title": closed["title"], "body": closed["description"], "url": closed["web_url"]})

    def test_an_issue_in_another_tracker_has_no_iid_and_is_skipped(self):
        record, _ = self.record(issues=[{"title": "JIRA-1", "description": "x", "web_url": "https://jira.example.com/1"},
                                        {"iid": 3, "title": "I", "description": None, "web_url": "https://gitlab.com/g/p/-/issues/3"}])
        self.assertEqual(record["issues"], [{"number": 3, "title": "I", "body": "", "url": "https://gitlab.com/g/p/-/issues/3"}])

    def test_a_missing_description_is_empty_text(self):
        self.assertEqual(self.record(description=None)[0]["body"], "")

    def test_a_merge_request_whose_diff_is_not_worked_out_yet_says_so(self):
        with self.assertRaisesRegex(LookupError, "not worked out the diff of !4420"):
            self.record(diff_refs=None)

    def test_a_prs_head_is_fetched_from_its_merge_request_ref(self):
        self.assertEqual(FORGE.fetch_ref(7), "merge-requests/7/head")

    def test_a_failed_call_says_what_gitlab_has_not(self):
        failed = subprocess.CalledProcessError(1, "glab", stderr="404 Not Found\n")
        glab, _ = fake_glab(others={f"projects/{ENCODED}/merge_requests/9": failed})
        with mock.patch.object(mergeatlas, "glab", glab), self.assertRaisesRegex(LookupError, "404 Not Found"):
            FORGE.pull(PROJECT, 9)

    def test_the_files_are_the_paths_the_merge_request_changes(self):
        glab, asked = fake_glab(others={f"projects/{ENCODED}/merge_requests/7/diffs?per_page=100":
                                        [{"new_path": "a.py", "old_path": "a.py"}, {"new_path": "b/c.py", "old_path": "b/old.py"}]})
        with mock.patch.object(mergeatlas, "glab", glab):
            self.assertEqual(FORGE.files(PROJECT, 7), ["a.py", "b/c.py"])


class States(unittest.TestCase):
    def test_gitlabs_states_become_stack_detections(self):
        for gitlab, ours in [("opened", "open"), ("locked", "open"), ("merged", "merged"), ("closed", "closed")]:
            with self.subTest(state=gitlab):
                glab, _ = fake_glab([merge_request(7, "b", "a", state=gitlab)])
                with mock.patch.object(mergeatlas, "glab", glab):
                    self.assertEqual(FORGE.pull(PROJECT, 7)["state"], ours)

    def test_a_pull_is_cut_down_to_what_stack_detection_reads(self):
        glab, _ = fake_glab([merge_request(7, "b", "a")])
        with mock.patch.object(mergeatlas, "glab", glab):
            self.assertEqual(FORGE.pull(PROJECT, 7), {"number": 7, "title": "MR 7", "url": URL, "state": "open",
                                                      "base": "a", "head": "b", "stack": None})

    def test_the_current_branchs_merge_request(self):
        glab, asked = fake_glab([merge_request(7, "feature/x", "main")])
        with mock.patch.object(mergeatlas, "glab", glab), origin_at("git@gitlab.com:g/s/p.git") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout="feature/x\n", stderr="")
            with mock.patch.object(mergeatlas.GitLab, "current_repo", return_value=PROJECT):
                self.assertEqual(FORGE.current_pr(), 7)
        self.assertEqual(asked[0][-1], f"projects/{ENCODED}/merge_requests?state=opened&source_branch=feature%2Fx")

    def test_a_branch_with_no_merge_request_has_none(self):
        glab, _ = fake_glab([])
        with mock.patch.object(mergeatlas, "glab", glab), origin_at("x") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout="lonely\n", stderr="")
            with mock.patch.object(mergeatlas.GitLab, "current_repo", return_value=PROJECT):
                self.assertIsNone(FORGE.current_pr())

    def test_a_detached_head_has_none(self):
        with mock.patch.object(mergeatlas, "glab", side_effect=AssertionError("asked")), origin_at("x") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout="\n", stderr="")
            self.assertIsNone(FORGE.current_pr())


class Listings(unittest.TestCase):
    def test_merge_requests_are_listed_by_their_source_and_target_branches(self):
        mrs = [merge_request(1, "a", "main"), merge_request(2, "b", "a"), merge_request(3, "c", "b", state="merged")]
        glab, asked = fake_glab(mrs)
        with mock.patch.object(mergeatlas, "glab", glab):
            self.assertEqual([p["number"] for p in FORGE.pulls_with_head(PROJECT, "b")], [2])
            self.assertEqual([p["number"] for p in FORGE.pulls_with_base(PROJECT, "b")], [3])
        self.assertEqual(asked[0][-1], f"projects/{ENCODED}/merge_requests?state=all&per_page=100&source_branch=b")
        self.assertEqual(asked[1][-1], f"projects/{ENCODED}/merge_requests?state=all&per_page=100&target_branch=b")

    def test_a_forks_branch_of_the_same_name_is_not_this_projects(self):
        glab, _ = fake_glab([merge_request(1, "main", "main", source_project_id=2), merge_request(2, "main", "dev")])
        with mock.patch.object(mergeatlas, "glab", glab):
            self.assertEqual([p["number"] for p in FORGE.pulls_with_head(PROJECT, "main")], [2])

    def test_a_branch_name_is_encoded_in_the_query(self):
        glab, asked = fake_glab([])
        with mock.patch.object(mergeatlas, "glab", glab):
            FORGE.pulls_with_head(PROJECT, "a b&c/d")
        self.assertTrue(asked[0][-1].endswith("source_branch=a%20b%26c%2Fd"))


class Stacks(unittest.TestCase):
    """GitLab has no stacks, so a stack is a chain of merge requests, each targeting the branch the one below it comes from."""

    def setUp(self):
        mrs = [merge_request(1, "a", "main"), merge_request(2, "b", "a"), merge_request(3, "c", "b"),
               merge_request(9, "z", "main", state="closed")]
        glab, self.asked = fake_glab(mrs)
        patch = mock.patch.object(mergeatlas, "glab", glab)
        patch.start()
        self.addCleanup(patch.stop)

    def plan(self, *links, whole_stack=False):
        targets = [mergeatlas.parse_target(link) for link in links]
        return mergeatlas.resolve(targets, FORGE, whole_stack=whole_stack)

    def link(self, n):
        return f"https://gitlab.com/{PROJECT}/-/merge_requests/{n}"

    def test_the_whole_chain_is_found_from_any_merge_request_in_it(self):
        for n in (1, 2, 3):
            with self.subTest(n=n):
                plan = self.plan(self.link(n), whole_stack=True)
                self.assertEqual((plan["map"], plan["stack"]["prs"], plan["stack"]["source"]), ([1, 2, 3], [1, 2, 3], "branches"))
                self.assertEqual((plan["stack"]["number"], plan["stack"]["base"]), (None, "main"))

    def test_a_single_link_maps_only_that_merge_request(self):
        plan = self.plan(self.link(2))
        self.assertEqual((plan["map"], plan["stack"]["prs"]), ([2], [1, 2, 3]))

    def test_two_links_map_the_run_between_them(self):
        self.assertEqual(self.plan(self.link(1), self.link(3))["map"], [1, 2, 3])

    def test_a_merge_request_alone_is_in_no_stack(self):
        self.assertIsNone(self.plan(self.link(9))["stack"])

    def test_a_stack_record_has_no_stack_url_and_the_ids_of_its_maps(self):
        plan = self.plan(self.link(2), whole_stack=True)
        with mock.patch.object(mergeatlas.GitLab, "files", lambda self, repo, n: [f"f{n}.py"]):
            record = mergeatlas.stack_record(plan, FORGE)
        self.assertEqual(record["id"], "gitlab-g-s-p-stack-1-3")
        self.assertIsNone(record["url"])
        self.assertEqual([(p["number"], p["map_id"]) for p in record["prs"]],
                         [(n, f"gitlab-g-s-p-{n}") for n in (1, 2, 3)])
        self.assertEqual(record["prs"][0]["url"], self.link(1))


class Status(unittest.TestCase):
    def status(self, url=URL, stdout=None, returncode=0, error=None):
        stdout = json.dumps({**MR, "sha": "h" * 40, "state": "merged"}) if stdout is None else stdout
        done = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")
        with mock.patch.object(mergeatlas.subprocess, "run", return_value=done, side_effect=error) as run:
            return mergeatlas.forge_for(url).status(url), run

    def test_it_asks_glab_with_a_timeout_of_fifteen_seconds(self):
        now, run = self.status()
        self.assertEqual(now, {"head": "h" * 40, "state": "merged"})
        self.assertEqual(run.call_args.args[0], ["glab", "api", f"projects/{ENCODED}/merge_requests/7"])
        self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_a_self_hosted_gitlab_is_asked_by_name(self):
        _, run = self.status("https://git.example.com/g/s/p/-/merge_requests/7")
        self.assertEqual(run.call_args.args[0], ["glab", "api", "--hostname", "git.example.com", f"projects/{ENCODED}/merge_requests/7"])

    def test_it_answers_nothing_when_it_cannot_tell(self):
        self.assertEqual(self.status(returncode=1, stdout="")[0], {})
        self.assertEqual(self.status(stdout="not json")[0], {})
        self.assertEqual(self.status(stdout='{"sha": "h", "state": "weird"}')[0], {})
        self.assertEqual(self.status(error=subprocess.TimeoutExpired("glab", 15))[0], {})
        self.assertEqual(self.status(error=FileNotFoundError("glab"))[0], {})

    def test_the_server_asks_the_forge_of_the_maps_url(self):
        self.assertEqual(mergeatlas.forge_for(URL).label, "GitLab")
        self.assertEqual(mergeatlas.forge_for("https://github.com/o/r/pull/7").label, "GitHub")


class HostArguments(unittest.TestCase):
    def asked(self, forge):
        with mock.patch.object(mergeatlas, "glab", return_value="{}") as run:
            forge._api("projects/x")
        return run.call_args.args

    def test_gitlab_dot_com_is_glabs_default(self):
        self.assertEqual(self.asked(mergeatlas.GitLab("gitlab.com")), ("api", "projects/x"))

    def test_any_other_host_is_named(self):
        self.assertEqual(self.asked(mergeatlas.GitLab("git.example.com")), ("api", "--hostname", "git.example.com", "projects/x"))

    def test_glab_is_run_as_the_gh_adapter_runs_gh(self):
        done = subprocess.CompletedProcess([], 0, stdout="out", stderr="")
        with mock.patch.object(mergeatlas.subprocess, "run", return_value=done) as run:
            self.assertEqual(mergeatlas.glab("api", "x"), "out")
        self.assertEqual(run.call_args.args[0], ["glab", "api", "x"])


class LinkTemplates(unittest.TestCase):
    def test_the_templates_for_a_merge_request_and_its_files(self):
        key = FORGE.diff_key("src/a.py")
        self.assertEqual(FORGE.links(URL, ["src/a.py"]), {
            "host": "GitLab", "noun": "merge request", "pr": URL, "ref": "!{n}",
            "diff": f"{URL}/diffs?file_path={{epath}}", "diff_line": "#line_{key}_{side}{first}", "diff_range": None,
            "marks": {"+": "A", "-": "", " ": None},
            "blob": f"https://gitlab.com/{PROJECT}/-/blob/{{sha}}/{{path}}", "blob_line": "#L{first}", "blob_range": "#L{first}-{last}",
            "commit": f"https://gitlab.com/{PROJECT}/-/commit/{{sha}}", "tree": f"https://gitlab.com/{PROJECT}/-/tree/{{ref}}",
            "pr_number": f"https://gitlab.com/{PROJECT}/-/merge_requests/{{n}}",
            "keys": {"src/a.py": key},
        })

    def test_a_files_diff_key_is_the_start_of_the_hash_of_its_path(self):
        self.assertEqual(FORGE.diff_key("a"), "86f7e437f")

    def test_a_stack_has_no_url_on_gitlab(self):
        self.assertIsNone(FORGE.stack_url(PROJECT, 3))

    def test_the_forge_is_found_again_from_the_url_a_map_keeps(self):
        self.assertEqual(mergeatlas.forge_for(URL).repo_of(URL), PROJECT)


if __name__ == "__main__":
    unittest.main()
