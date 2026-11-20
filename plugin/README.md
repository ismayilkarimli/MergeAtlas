# MergeAtlas plugin

This repository is the MergeAtlas plugin for Claude Code, and nothing else: its manifest, the skill's `SKILL.md`, the script, the viewer and the license. It is published from [`plugin/`](https://github.com/ismayilkarimli/MergeAtlas/tree/main/plugin) in [ismayilkarimli/MergeAtlas](https://github.com/ismayilkarimli/MergeAtlas) at each release, and takes no other changes. Develop there, and report issues there.

Each commit here names the MergeAtlas commit it was copied from. To check that a release here is exactly that commit's `plugin/`, compare the two trees:

```bash
git rev-parse v0.6.5^{tree}
```

```bash
git -C <MergeAtlas clone> rev-parse v0.6.5:plugin
```

## Installing

From Claude Code:

```
/plugin marketplace add ismayilkarimli/MergeAtlas
```

```
/plugin install mergeatlas@mergeatlas
```

The marketplace installs this repository. To list MergeAtlas in your own marketplace, point at this repository and pin a release:

```json
{
  "name": "mergeatlas",
  "source": { "source": "github", "repo": "ismayilkarimli/mergeatlas-plugin", "ref": "v0.6.5" }
}
```

What MergeAtlas needs to run, and how to use it, is in the [MergeAtlas README](https://github.com/ismayilkarimli/MergeAtlas#readme).
