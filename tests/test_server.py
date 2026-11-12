"""The viewer server: what it hands out, to whom, and how a new release takes over from an old one.

Run from the repository root:
    python3 -m unittest discover -s tests

The cache the server reads holds more than maps: work/ keeps the diffs and PR text of every repository mapped, private
ones included. So the server hands out the viewer and the published maps and nothing else, and it answers only under
its own address. A web page can point its own domain at 127.0.0.1 and read whatever a local server gives that name.

Two answers are worked out when asked for, and neither is a file. maps.json lists the published maps for the viewer's
front page. pr-now.json says where a mapped PR stands on GitHub now, which the server asks gh for, so the viewer can
say when a map describes an older commit.

The interface under test, in skills/mergeatlas/scripts/mergeatlas.py:
    ViewerHandler            -> the request handler; its server's port is the one a Host header must name
    library()                -> what maps.json answers: every published map and stack page, the latest first
    pr_now(map_id)           -> what pr-now.json answers: the commit the map was made at, and the PR's head and state now
    serve()                  -> starts the server unless this release's is running; replaces another release's
    unversioned_server()     -> the process id of a server from before servers named their release, or None
"""
import http.client
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from test_stack_detection import mergeatlas


class Served(unittest.TestCase):
    """A server of its own on a spare port, over a cache of its own."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        (self.home / "data").mkdir()
        (self.home / "work").mkdir()
        (self.home / "index.html").write_text('<div id="world"></div>')
        (self.home / "data" / "o-r-7.json").write_text('{"pr": {}}')
        (self.home / "work" / "o-r-7.diff").write_text("+secret")
        for patch in (mock.patch.object(mergeatlas.ViewerHandler, "log_message", lambda *args: None),
                      mock.patch.object(mergeatlas, "DATA", self.home / "data"),
                      mock.patch.object(mergeatlas, "pr_now_known", {})):
            patch.start()
            self.addCleanup(patch.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(mergeatlas.ViewerHandler, directory=self.home))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.home)

    def get(self, path, host=None, site=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.putrequest("GET", path, skip_host=True)
        connection.putheader("Host", host or f"127.0.0.1:{self.port}")
        if site:
            connection.putheader("Sec-Fetch-Site", site)
        connection.endheaders()
        response = connection.getresponse()
        body = response.read().decode()
        connection.close()
        return response, body

    def publish(self, map_id, data):
        (self.home / "data" / f"{map_id}.json").write_text(json.dumps(data))


class WhatTheServerHandsOut(Served):
    def test_the_viewer_opens_with_and_without_its_file_name(self):
        for path in ("/", "/index.html", "/?map=o-r-7&view=list"):
            response, body = self.get(path)
            self.assertEqual((response.status, body), (200, '<div id="world"></div>'), path)

    def test_a_published_map_is_handed_out(self):
        response, body = self.get("/data/o-r-7.json")
        self.assertEqual((response.status, body), (200, '{"pr": {}}'))

    def test_the_work_directory_is_never_handed_out(self):
        for path in ("/work/o-r-7.diff", "/work/", "/work", "/data/../work/o-r-7.diff", "/data/%2e%2e/work/o-r-7.diff"):
            response, body = self.get(path)
            self.assertEqual(response.status, 404, path)
            self.assertNotIn("secret", body)

    def test_no_directory_is_listed(self):
        for path in ("/data/", "/data"):
            self.assertEqual(self.get(path)[0].status, 404, path)

    def test_another_host_name_is_refused(self):
        for host in ("attacker.example", f"attacker.example:{self.port}", "127.0.0.1", f"127.0.0.1:{self.port + 1}"):
            response, body = self.get("/data/o-r-7.json", host=host)
            self.assertEqual(response.status, 403, host)
            self.assertNotIn("pr", body)

    def test_localhost_is_the_same_machine(self):
        self.assertEqual(self.get("/data/o-r-7.json", host=f"localhost:{self.port}")[0].status, 200)

    def test_a_map_is_never_cached_and_names_its_server(self):
        response, _ = self.get("/data/o-r-7.json")
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.getheader("X-MergeAtlas-Version"), mergeatlas.VERSION)
        self.assertTrue(response.getheader("X-MergeAtlas-Pid").isdigit())


def a_map(number, title, at, head="a" * 40, draft=False, stack=None):
    return {"pr": {"number": number, "title": title, "files": 3, "additions": 40, "deletions": 2, "draft": draft,
                   "url": f"https://github.com/o/r/pull/{number}", "mapped": {"at": at, "head": head}, "stack": stack,
                   "diffs": {"src/secret.py": "+secret"}, "problem": "a secret problem"}, "cards": [{"id": "secret"}]}


class TheListOfMaps(Served):
    def maps(self):
        response, body = self.get("/maps.json")
        self.assertEqual((response.status, response.getheader("Content-Type")), (200, "application/json"))
        return json.loads(body)

    def test_a_cache_with_no_readable_map_lists_none(self):
        (self.home / "data" / "broken.json").write_text("{")
        self.assertEqual(self.maps(), [])

    def test_maps_come_latest_first_with_what_the_front_page_shows(self):
        self.publish("o-r-8", a_map(8, "Older", 100))
        self.publish("o-r-9", a_map(9, "Newer", 200, draft=True))
        newer, older = self.maps()
        self.assertEqual(newer, {"id": "o-r-9", "kind": "map", "repo": "o/r", "number": 9, "title": "Newer", "files": 3,
                                 "additions": 40, "deletions": 2, "url": "https://github.com/o/r/pull/9", "draft": True,
                                 "at": 200, "stack": None})
        self.assertEqual((older["id"], older["draft"]), ("o-r-8", False))

    def test_the_list_holds_none_of_a_maps_code_or_words(self):
        self.publish("o-r-8", a_map(8, "Older", 100))
        self.assertNotIn("secret", self.get("/maps.json")[1])

    def test_a_map_from_before_maps_said_when_they_were_made_takes_its_files_time(self):
        data = a_map(8, "Older", 100)
        del data["pr"]["mapped"]
        self.publish("o-r-8", data)
        self.assertEqual(self.maps()[0]["at"], int((self.home / "data" / "o-r-8.json").stat().st_mtime))

    def test_a_map_in_a_stack_says_its_place(self):
        strip = {"id": "o-r-stack-1", "number": 1, "prs": [{"number": 7}, {"number": 8, "current": True}, {"number": 9}]}
        self.publish("o-r-8", a_map(8, "Middle", 100, stack=strip))
        self.assertEqual(self.maps()[0]["stack"], {"id": "o-r-stack-1", "number": 1, "of": 3, "part": 2})

    def test_a_stack_page_is_listed_with_its_size(self):
        self.publish("o-r-stack-1", {"kind": "stack", "stack": {"id": "o-r-stack-1", "repo": "o/r", "number": 1, "url": "https://x"},
                                     "prs": [{}, {}, {}]})
        (page,) = self.maps()
        self.assertEqual({k: page[k] for k in ("id", "kind", "repo", "number", "prs")},
                         {"id": "o-r-stack-1", "kind": "stack", "repo": "o/r", "number": 1, "prs": 3})

    def test_the_list_is_refused_under_another_host_name(self):
        self.assertEqual(self.get("/maps.json", host="attacker.example")[0].status, 403)

    def test_the_list_is_for_the_viewer_and_not_for_another_sites_page(self):
        self.assertEqual(self.get("/maps.json", site="same-origin")[0].status, 200)
        for site in ("cross-site", "same-site", "none"):
            self.assertEqual(self.get("/maps.json", site=site)[0].status, 403, site)

    def test_a_link_from_another_site_still_opens_a_map(self):
        self.assertEqual(self.get("/?map=o-r-7", site="cross-site")[0].status, 200)


class WhereThePullRequestStandsNow(Served):
    def now(self, map_id="o-r-8", stdout='{"head": "%s", "state": "open"}' % ("b" * 40), returncode=0):
        """What pr-now.json answers, and the gh commands the server ran for it."""
        done = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")
        with mock.patch.object(mergeatlas.subprocess, "run", return_value=done) as run:
            response, body = self.get(f"/pr-now.json?map={map_id}")
        self.assertEqual(response.status, 200)
        return json.loads(body), [call.args[0] for call in run.call_args_list]

    def test_it_gives_the_mapped_commit_beside_the_head_on_github(self):
        self.publish("o-r-8", a_map(8, "Mapped", 100))
        now, ran = self.now()
        self.assertEqual(now, {"mapped": "a" * 40, "head": "b" * 40, "state": "open"})
        self.assertEqual(ran[0][:3], ["gh", "api", "repos/o/r/pulls/8"])

    def test_another_github_host_is_asked_by_name(self):
        data = a_map(8, "Mapped", 100)
        data["pr"]["url"] = "https://github.example.com/o/r/pull/8"
        self.publish("o-r-8", data)
        self.assertEqual(self.now()[1][0][:5], ["gh", "api", "--hostname", "github.example.com", "repos/o/r/pulls/8"])

    def test_github_is_asked_once_a_minute_at_most(self):
        self.publish("o-r-8", a_map(8, "Mapped", 100))
        self.assertEqual(len(self.now()[1]), 1)
        self.assertEqual(self.now(), ({"mapped": "a" * 40, "head": "b" * 40, "state": "open"}, []))

    def test_a_map_made_again_is_asked_about_again(self):
        self.publish("o-r-8", a_map(8, "Mapped", 100))
        self.now()
        self.publish("o-r-8", a_map(8, "Mapped", 200, head="b" * 40))
        now, ran = self.now()
        self.assertEqual((now["mapped"], len(ran)), ("b" * 40, 1))

    def test_it_answers_nothing_when_it_cannot_tell(self):
        self.publish("o-r-8", a_map(8, "Mapped", 100))
        self.assertEqual(self.now(returncode=1, stdout="")[0], {})

    def test_another_sites_page_cannot_have_github_asked(self):
        self.publish("o-r-8", a_map(8, "Mapped", 100))
        done = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
        with mock.patch.object(mergeatlas.subprocess, "run", return_value=done) as run:
            response, _ = self.get("/pr-now.json?map=o-r-8", site="cross-site")
        self.assertEqual((response.status, run.call_count), (403, 0))

    def test_gh_is_not_run_for_a_map_that_is_not_there(self):
        for map_id in ("nope", "../work/o-r-7", "", "o-r-7"):
            self.assertEqual(self.now(map_id=map_id), ({}, []), map_id)


class Answer:
    """What urlopen gives back for the server already on the port."""

    def __init__(self, body, headers):
        self.body, self.headers = body, headers

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


VIEWER = b'<div id="world"></div>'


class TakingOverFromAnotherRelease(unittest.TestCase):
    def serve(self, answer, listening=(True, False), unversioned=None):
        """Runs serve against a port in the given state; returns the process ids stopped and how many servers started."""
        with mock.patch.object(mergeatlas, "listening", side_effect=list(listening)), \
                mock.patch.object(mergeatlas.urllib.request, "urlopen", return_value=answer), \
                mock.patch.object(mergeatlas, "unversioned_server", return_value=unversioned), \
                mock.patch.object(mergeatlas.os, "kill") as kill, \
                mock.patch.object(mergeatlas.subprocess, "Popen") as popen, \
                mock.patch.object(mergeatlas.sys, "stderr"):
            mergeatlas.serve()
        return [call.args[0] for call in kill.call_args_list], popen.call_count

    def test_a_free_port_gets_a_server(self):
        self.assertEqual(self.serve(None, listening=(False,)), ([], 1))

    def test_this_releases_server_is_left_running(self):
        answer = Answer(VIEWER, {"X-MergeAtlas-Version": mergeatlas.VERSION, "X-MergeAtlas-Pid": "41"})
        self.assertEqual(self.serve(answer, listening=(True,)), ([], 0))

    def test_another_releases_server_is_stopped_and_replaced(self):
        answer = Answer(VIEWER, {"X-MergeAtlas-Version": "0.0.1", "X-MergeAtlas-Pid": "41"})
        self.assertEqual(self.serve(answer), ([41], 1))

    def test_a_server_from_before_releases_is_replaced_when_its_process_is_found(self):
        self.assertEqual(self.serve(Answer(VIEWER, {}), unversioned="52"), ([52], 1))

    def test_a_server_from_before_releases_is_left_when_its_process_is_not_found(self):
        self.assertEqual(self.serve(Answer(VIEWER, {}), listening=(True,)), ([], 0))

    def test_something_else_on_the_port_stops_the_run(self):
        with self.assertRaises(SystemExit):
            self.serve(Answer(b"<h1>another app</h1>", {}), listening=(True,))


if __name__ == "__main__":
    unittest.main()
