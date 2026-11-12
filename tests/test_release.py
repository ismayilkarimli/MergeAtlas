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
    the server for, esc and unesc, and ago, which says how long ago a map was made
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

    def test_a_link_target_comes_back_as_it_was_written(self):
        path = '''src/a&b/it's "x".ts#L1-L2'''
        ran = self.node(f"{self.escaping()}\nconsole.log(unesc(esc({json.dumps(path)})));\nconsole.log(unesc(esc('&lt;')));")
        self.assertEqual(ran.stdout.splitlines(), [path, "&lt;"], ran.stderr)


if __name__ == "__main__":
    unittest.main()
