"""The viewer server: what it hands out, to whom, and how a new release takes over from an old one.

Run from the repository root:
    python3 -m unittest discover -s tests

The cache the server reads holds more than maps: work/ keeps the diffs and PR text of every repository mapped, private
ones included. So the server hands out the viewer and the published maps and nothing else, and it answers only under
its own address. A web page can point its own domain at 127.0.0.1 and read whatever a local server gives that name.

The interface under test, in skills/mergeatlas/scripts/mergeatlas.py:
    ViewerHandler            -> the request handler; its server's port is the one a Host header must name
    serve()                  -> starts the server unless this release's is running; replaces another release's
    unversioned_server()     -> the process id of a server from before servers named their release, or None
"""
import http.client
import shutil
import tempfile
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from test_stack_detection import mergeatlas


class WhatTheServerHandsOut(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        (self.home / "data").mkdir()
        (self.home / "work").mkdir()
        (self.home / "index.html").write_text('<div id="world"></div>')
        (self.home / "data" / "o-r-7.json").write_text('{"pr": {}}')
        (self.home / "work" / "o-r-7.diff").write_text("+secret")
        quiet = mock.patch.object(mergeatlas.ViewerHandler, "log_message", lambda *args: None)
        quiet.start()
        self.addCleanup(quiet.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(mergeatlas.ViewerHandler, directory=self.home))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.home)

    def get(self, path, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.putrequest("GET", path, skip_host=True)
        connection.putheader("Host", host or f"127.0.0.1:{self.port}")
        connection.endheaders()
        response = connection.getresponse()
        body = response.read().decode()
        connection.close()
        return response, body

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
