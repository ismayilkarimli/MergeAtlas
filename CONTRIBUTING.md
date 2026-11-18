# Contributing to MergeAtlas

## What is where

- `plugin/skills/mergeatlas/SKILL.md`: the instructions the agent follows to write a map. This is most of the product.
- `plugin/skills/mergeatlas/scripts/mergeatlas.py`: the mechanical half. It fetches the pull request, runs searches, checks the map, serves it and keeps the run record. It uses the Python standard library alone, so there is nothing to install.
- `plugin/skills/mergeatlas/assets/viewer.html`: the viewer, one file with no build step. `site/map/index.html` is a link to it, so the sample map on the site always runs the current viewer.
- `site/`: the landing page at mergeatlas.dev.
- `tests/`: the tests for the script and for what the script and the viewer rely on in each other.
- `plugin/`: everything a user installs, and nothing else. Each release copies it to [ismayilkarimli/mergeatlas-plugin](https://github.com/ismayilkarimli/mergeatlas-plugin), which the marketplace installs from and which refuses any other change, so never edit that repository: change `plugin/` here. To try a change in Claude Code before it is released, run `claude --plugin-dir ./plugin`. Keep tests, notes and images outside it; a test fails when it holds a file `tools/build_dist.py` does not list in `FILES`.
- `tools/build_dist.py`: builds the zip a release attaches, the skill folder alone.

## Running the checks

From the repository root:

```bash
python3 -m unittest discover -s tests
```

```bash
uvx ruff@0.17.4 check .
```

The tests need `git`, and the viewer's tests also need Node.js and are skipped without it. No test reads or writes `~/.cache/mergeatlas` or calls GitHub, unless you set `MERGEATLAS_LIVE=1`, which checks the GitHub adapter against a real repository and needs `gh` signed in.

CI runs both on every pull request, with the tests on Python 3.9 to 3.14. The oldest Python MergeAtlas runs on is 3.9, the one macOS ships, so keep to syntax and library calls it has.

## Changing how maps are written

A change to `SKILL.md` changes every map, and no test can tell you whether maps got better. Measure the change against the fixed set of pull requests in `evals/` before you open the pull request, as `evals/README.md` describes, and paste the comparison table into it.

## Changing the viewer or the server

A map carries text from outside: a pull request's title and description, ticket text, file paths and code. Treat all of it as untrusted.

- In the viewer, every value written into HTML goes through `esc`, and prose through `fmt`, which escapes first.
- The server hands out the viewer and `data/<map-id>.json`, and works out two answers of its own: `maps.json`, the list of published maps, and `pr-now.json`, where a mapped PR stands on GitHub. It serves nothing else. `work/` holds diffs and PR text of private repositories and is never served.

## Commits and pull requests

Write the commit subject as what a user can now do or what is now true, such as "Let fetch take PR and stack links". Add a line to `CHANGELOG.md` under the next version for anything a user would notice.

## Releasing

Claude Code keeps the plugin's users on a release until its version changes, so merging to `main` does not reach them by itself. Installs through skills.sh or a clone do follow `main`.

1. Choose the version. While it starts with 0, bump the minor number for a change to the map format or a command, and the patch number otherwise.
2. Set it in `VERSION` in `plugin/skills/mergeatlas/scripts/mergeatlas.py` and in `plugin/.claude-plugin/plugin.json`, and give it a `## <version> - <date>` heading in `CHANGELOG.md`. A test fails while the three disagree.
3. Merge to `main`, then tag that commit and push the tag:

```bash
git tag v0.2.0
```

```bash
git push origin v0.2.0
```

The release workflow runs CI, copies `plugin/` into the lean repository as one commit with the same tag, checks that its tree is `plugin/` exactly, then publishes a GitHub release with that version's part of the changelog and the zip of the skill. A tag the lean repository already has is never published again, so a release that went wrong gets a new version. The workflow writes there with a deploy key stored as the `PLUGIN_DEPLOY_KEY` secret, the only key that repository's rulesets let through.
