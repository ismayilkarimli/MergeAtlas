"""A release: the places that name it agree, and the viewer still holds what the script and its readers rely on.

Run from the repository root:
    python3 -m unittest discover -s tests

Claude Code keeps a plugin's users on the version in .claude-plugin/plugin.json until that string changes, so a push
reaches them only when the version moves. The script carries the same version for installs that copy the skill alone,
and CHANGELOG.md says what the version holds.

The viewer checks need Node.js and are skipped without it. They run the viewer's own escaping, since a map carries text
from outside, such as a pull request's title, and the viewer writes that text into attributes.

What is under test:
    mergeatlas.VERSION, .claude-plugin/plugin.json, .claude-plugin/marketplace.json, CHANGELOG.md, README.md
    skills/mergeatlas/assets/viewer.html: the map slot export fills, the mark serve knows the viewer by, what it asks
    the server for, esc and unesc, ago, which says how long ago a map was made, and codeUrl, which opens a link into code
    on the host from the templates in the map's `links`, and keyLine, which does the same for a line of a diff,
    for GitHub's templates and GitLab's
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_stack_detection import ROOT, mergeatlas

VIEWER = (ROOT / "skills" / "mergeatlas" / "assets" / "viewer.html").read_text()
NODE = shutil.which("node")


class OneVersion(unittest.TestCase):
    def test_the_plugin_names_the_scripts_version(self):
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(plugin["version"], mergeatlas.VERSION)

    def test_the_marketplace_leaves_the_version_to_the_plugin(self):
        marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual([p["name"] for p in marketplace["plugins"] if "version" in p], [])

    def test_the_changelog_has_the_version(self):
        changelog = (ROOT / "CHANGELOG.md").read_text()
        self.assertRegex(changelog, rf"(?m)^## {re.escape(mergeatlas.VERSION)}\b")

    def test_the_version_is_three_numbers(self):
        self.assertRegex(mergeatlas.VERSION, r"^\d+\.\d+\.\d+$")

    def test_the_readme_names_the_oldest_python(self):
        oldest = ".".join(map(str, mergeatlas.OLDEST_PYTHON))
        self.assertIn(f"Python {oldest} or newer", (ROOT / "README.md").read_text())


class WhatTheScriptNeedsOfTheViewer(unittest.TestCase):
    def test_the_viewer_has_one_empty_map_slot_for_export_to_fill(self):
        self.assertEqual(VIEWER.count(mergeatlas.MAP_SLOT), 1)

    def test_the_viewer_carries_the_mark_serve_knows_it_by(self):
        self.assertIn('id="world"', VIEWER)

    def test_the_viewer_asks_the_server_only_for_what_it_hands_out(self):
        asked = set(re.findall(r"fetch\([`']([^`']*)[`']", VIEWER))
        self.assertEqual(asked, {"data/${encodeURIComponent(id)}.json", "maps.json", "pr-now.json?map=${encodeURIComponent(id)}"})
        self.assertTrue(mergeatlas.SERVED.fullmatch("/data/owner-repo.name_1-42.json"))

    def test_the_viewer_names_no_host_of_its_own(self):
        self.assertNotRegex(VIEWER, r"(?i)github|gitlab")


@unittest.skipUnless(NODE, "needs Node.js")
class ViewerScript(unittest.TestCase):
    def node(self, script):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "check.js"
            path.write_text(script)
            return subprocess.run([NODE, str(path)], capture_output=True, text=True)

    def escaping(self):
        """The viewer's own escaping, lifted out of the page."""
        lines = [line for line in VIEWER.splitlines() if re.match(r"const (ENTITY|esc|unesc) = ", line)]
        self.assertEqual(len(lines), 3)
        return "\n".join(lines)

    def test_the_script_parses(self):
        scripts = re.findall(r"<script>(.*?)</script>", VIEWER, re.S)
        self.assertTrue(scripts)
        with tempfile.TemporaryDirectory() as tmp:
            for i, script in enumerate(scripts):
                path = Path(tmp) / f"viewer-{i}.js"
                path.write_text(script)
                checked = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True)
                self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_text_from_a_map_cannot_leave_an_attribute(self):
        title = '''Fix "quotes" & <tags> ' onmouseover='alert(1)'''
        ran = self.node(f"{self.escaping()}\nconsole.log(esc({json.dumps(title)}));")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        escaped = ran.stdout.strip()
        for character in '"\'<>':
            self.assertNotIn(character, escaped)
        self.assertEqual(escaped, "Fix &quot;quotes&quot; &amp; &lt;tags&gt; &apos; onmouseover=&apos;alert(1)")

    def test_how_long_ago_a_map_was_made_reads_in_the_largest_unit_that_fits(self):
        ago = re.search(r"const UNITS = .*?\n}\n", VIEWER, re.S)
        self.assertTrue(ago)
        asked = [20, 60, 59 * 60, 3 * 3600, 26 * 3600, 20 * 86400]
        ran = self.node(f"{ago[0]}\nconst now = Date.now() / 1000;\n"
                        f"for (const s of {json.dumps(asked)}) console.log(ago(now - s));\nconsole.log(ago(86400));")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        *recent, dated = ran.stdout.splitlines()
        self.assertEqual(recent, ["just now", "1 minute ago", "59 minutes ago", "3 hours ago", "1 day ago", "20 days ago"])
        self.assertRegex(dated, r"^on .*1970")

    def key_lines(self, links, rows):
        """Runs the viewer's own keyLine against a map's links and gives the address each row opens."""
        lifted = re.search(r"const fill = .*?\n};\n(?=const codeLink)", VIEWER, re.S)
        self.assertTrue(lifted)
        meta = {"pinned": {"commit": "c0ffee"}, "mapped": {"head": "beef00"}}
        ran = self.node(f"{self.escaping()}\nconst META = {json.dumps(meta)}, LINKS = {json.dumps(links)};\n{lifted[0]}\n"
                        f"for (const row of {json.dumps(rows)}) console.log(keyLine(row).match(/href=\"([^\"]*)\"/)[1]);")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        return ran.stdout.splitlines()

    def addresses(self, links, asked, mapped=None):
        """Runs the viewer's own codeUrl and keyLine addresses against a map's links."""
        lifted = re.search(r"const fill = .*?\n};\n(?=const keyLine)", VIEWER, re.S)
        self.assertTrue(lifted)
        meta = {"pinned": {"commit": "c0ffee"}, "mapped": mapped}
        ran = self.node(f"const META = {json.dumps(meta)}, LINKS = {json.dumps(links)};\n{lifted[0]}\n"
                        f"for (const at of {json.dumps(asked)}) console.log(codeUrl(at));\n"
                        "console.log(hostUrl('src/a.py', '7', null, 'L'), hostUrl('b.py', '7', null, 'L'));")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        return ran.stdout.splitlines()

    def test_a_link_into_code_opens_where_the_hosts_templates_say(self):
        links = mergeatlas.GitHub().links("https://github.com/o/r/pull/7", ["src/a.py"])
        found = self.addresses(links, ["src/a.py", "src/a.py#L5", "src/a.py#L5-L9", "b.py#L5-L9", "b.py"])
        key = links["keys"]["src/a.py"]
        self.assertEqual(found, [
            f"https://github.com/o/r/pull/7/files#diff-{key}", f"https://github.com/o/r/pull/7/files#diff-{key}R5",
            f"https://github.com/o/r/pull/7/files#diff-{key}R5-R9", "https://github.com/o/r/blob/c0ffee/b.py#L5-L9",
            "https://github.com/o/r/blob/c0ffee/b.py", f"https://github.com/o/r/pull/7/files#diff-{key}L7 "
            "https://github.com/o/r/blob/c0ffee/b.py#L7"])

    def test_another_host_spells_its_lines_in_its_own_templates(self):
        links = {"diff": "https://git.example/mr/7/diffs#{key}", "diff_line": "_{first}", "diff_range": "_{first}_{last}",
                 "blob": "https://git.example/-/blob/{sha}/{path}", "blob_line": "#L{first}", "blob_range": "#L{first}-{last}",
                 "keys": {"src/a.py": "k1"}}
        found = self.addresses(links, ["src/a.py#L5-L9", "b.py#L5-L9"])
        self.assertEqual(found[:2], ["https://git.example/mr/7/diffs#k1_5_9", "https://git.example/-/blob/c0ffee/b.py#L5-9"])

    def test_a_github_diff_line_is_named_by_its_side_and_a_context_line_too(self):
        links = mergeatlas.GitHub().links("https://github.com/o/r/pull/7", ["src/a.py"])
        rows = [{"text": "+new", "path": "src/a.py", "line": "R39", "key": True},
                {"text": "-old", "path": "src/a.py", "line": "L89", "key": True},
                {"text": " same", "path": "src/a.py", "line": "R12", "key": False},
                {"text": " else", "path": "b.py", "line": "R3", "key": False}]
        key = links["keys"]["src/a.py"]
        self.assertEqual(self.key_lines(links, rows), [
            f"https://github.com/o/r/pull/7/files#diff-{key}R39", f"https://github.com/o/r/pull/7/files#diff-{key}L89",
            f"https://github.com/o/r/pull/7/files#diff-{key}R12", "https://github.com/o/r/blob/c0ffee/b.py#L3"])

    def test_gitlab_sends_each_kind_of_line_where_its_diff_can_name_it(self):
        url = "https://gitlab.com/g/s/p/-/merge_requests/7"
        links = mergeatlas.GitLab().links(url, ["src/a.py"])
        rows = [{"text": "+new", "path": "src/a.py", "line": "R39", "key": True},
                {"text": "-old", "path": "src/a.py", "line": "L89", "key": True},
                {"text": " same", "path": "src/a.py", "line": "R12", "key": False},
                {"text": " else", "path": "b.py", "line": "R3", "key": False}]
        key = links["keys"]["src/a.py"]
        self.assertEqual(self.key_lines(links, rows), [
            f"{url}/diffs?file_path=src%2Fa.py#line_{key}_A39", f"{url}/diffs?file_path=src%2Fa.py#line_{key}_89",
            "https://gitlab.com/g/s/p/-/blob/beef00/src/a.py#L12", "https://gitlab.com/g/s/p/-/blob/c0ffee/b.py#L3"])

    def test_gitlab_opens_a_link_in_text_at_the_blob_where_its_diff_cannot_name_the_lines(self):
        url = "https://gitlab.com/g/s/p/-/merge_requests/7"
        links = mergeatlas.GitLab().links(url, ["src/a.py"])
        found = self.addresses(links, ["src/a.py", "src/a.py#L5", "src/a.py#L5-L9", "b.py#L5-L9", "b.py"], {"head": "beef00"})
        self.assertEqual(found[:5], [
            f"{url}/diffs?file_path=src%2Fa.py", "https://gitlab.com/g/s/p/-/blob/beef00/src/a.py#L5",
            "https://gitlab.com/g/s/p/-/blob/beef00/src/a.py#L5-9", "https://gitlab.com/g/s/p/-/blob/c0ffee/b.py#L5-9",
            "https://gitlab.com/g/s/p/-/blob/c0ffee/b.py"])

    def test_a_pr_is_named_as_its_host_names_it(self):
        refs = re.search(r"const prRef = .*\n(?://.*\n)?const prName = .*\n", VIEWER)
        fill = re.search(r"const fill = .*\n", VIEWER)
        self.assertTrue(refs and fill)
        for links, named in [(mergeatlas.GitHub().links("https://github.com/o/r/pull/7"), "PR #7"),
                             (mergeatlas.GitLab().links("https://gitlab.com/g/p/-/merge_requests/7"), "merge request !7")]:
            ran = self.node(f"const LINKS = {json.dumps(links)};\n{fill[0]}{refs[0]}\nconsole.log(prName(7), prRef(7));")
            self.assertEqual(ran.stdout.strip(), f"{named} {named.split()[-1]}", ran.stderr)

    def test_a_link_target_comes_back_as_it_was_written(self):
        path = '''src/a&b/it's "x".ts#L1-L2'''
        ran = self.node(f"{self.escaping()}\nconsole.log(unesc(esc({json.dumps(path)})));\nconsole.log(unesc(esc('&lt;')));")
        self.assertEqual(ran.stdout.splitlines(), [path, "&lt;"], ran.stderr)


if __name__ == "__main__":
    unittest.main()
