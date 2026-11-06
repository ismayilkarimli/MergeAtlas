<p align="center"><img src="skills/mergeatlas/assets/logo-3d.png" width="180" alt="MergeAtlas logo"></p>

<h1 align="center">MergeAtlas</h1>

<p align="center"><strong>Review code you don't know</strong></p>

<p align="center"><a href="https://mergeatlas.dev">mergeatlas.dev</a></p>

![Map view of a pull request](docs/map-view.png)

![Tree view of a pull request](docs/tree-view.png)

<p align="center"><sub>MergeAtlas mapping <a href="https://github.com/excalidraw/excalidraw/pull/10903">excalidraw/excalidraw#10903</a>, which makes image exports follow the editor's theme.</sub></p>

## What is MergeAtlas?

When you're asked to review a change that reaches further than its diff, in a project you don't know well, MergeAtlas helps you quickly build the mental model you're missing. You can give a real review without having to reconstruct the change and hold it all in your head.

It's made for changes with a medium to large blast radius: several files, some of them affected only indirectly. A config tweak doesn't need a map. Your agent or the PR description can tell you what it touches.

It's an agent skill that turns a pull request into an interactive map on localhost. The story of the change comes first: what this part of the project does, the problem, and what the PR does about it. Each changed file is a card, the cards sit in frames by the outcome they serve, and arrows show how a change in one reaches another, including through files the PR never touches. The map stops at understanding, so it doesn't find bugs, give verdicts, or tell you what to do. Those stay with you.

## Features

- **Map view:** an infinite canvas of cards and cause-and-effect arrows that you can pan, zoom and rearrange.
- **Neighbourhoods:** in Files view, cards sit in a frame per intent, ordered so arrows run left to right. Arrows take the direct way between cards, and hovering a card highlights its own.
- **Atlas zoom:** zoom out and cards turn compact, then each neighbourhood becomes one block with its title and progress.
- **Compact and Detailed:** switch cards between a one-line summary and the full story of the change.
- **Tree view:** a collapsible outline of the same cards and their affected files, with keyboard navigation.
- **The story:** background, problem and solution in plain words, linked to the cards that did each part.
- **Affected files:** unchanged files that behave differently because of the PR sit in a stack beside the card that reaches them.
- **Tests and no-behaviour-change files:** tests stack beside the card they verify, and whitespace, formatting, renames and generated files stack apart with a reason each, so your attention goes to what matters.
- **Key lines:** the lines most worth your attention on each card, the file they come from, and why they matter.
- **Code links:** claims link to their lines, in the PR's Files changed tab or at the head commit.
- **Review marks:** mark a file as reviewed and go straight to the next one. A progress bar counts the files that matter, and Previous and Next step through reading order.
- **Jump to a file:** press ⌘K to find a file by name.
- **Light and dark themes:** the viewer follows your system setting.

### Tickets

GitHub issues linked to the PR work out of the box. For other trackers, MergeAtlas spots the ticket in the PR's title, description or branch name, and your agent reads it through the connection it already has, such as an MCP server. MergeAtlas stores no tracker credentials of its own.

It recognises links from Jira, Linear, Trello, Asana, Shortcut, ClickUp and Azure Boards, and bare keys like `ENG-123`. If your agent can't reach the tracker, it tells you which ticket it couldn't read and builds the map from the PR alone.

## Running it

You'll need:

- An agent that runs skills, such as Claude Code
- Python 3
- `git`
- The [GitHub CLI](https://cli.github.com), signed in with `gh auth login`

Clone the repository and link the skill into your skills folder:

```bash
git clone https://github.com/ismayilkarimli/MergeAtlas.git
```

```bash
ln -s "$PWD/MergeAtlas/skills/mergeatlas" ~/.claude/skills/mergeatlas
```

Then, from inside the PR's repository, ask your agent to map it, or run `/mergeatlas` in Claude Code. The map opens at `http://127.0.0.1:8765`.

### Choosing the cold readers' model

Before publishing, your agent hands each card to a fresh subagent that has never seen the project, to find what the card leaves unexplained. The defaults for that subagent are Sonnet 5.5 at medium effort in Claude Code, Sol 6.1 at medium effort in Codex, and your agent's own model anywhere else.

On the first run, your agent asks which model to use, with the default already selected, so pressing Enter keeps it. Your answer is saved to `~/.config/mergeatlas/config.json` (or under `$XDG_CONFIG_HOME`). To use another model for a single run, say so when you ask, such as "map this PR using Haiku 5.5 high"; the saved choice stays as it was.

To change the saved choice later, run:

```bash
python3 skills/mergeatlas/scripts/mergeatlas.py config set claude-code "Opus 5.5" high
```

The first argument is your agent's entry: `claude-code`, `codex`, or `default` for any other agent. Use `own` as the model to run on your agent's own model. Running `config` alone shows what applies. You can also edit the file directly. Each entry replaces only the settings it names:

```json
{
  "cold_read": {
    "claude-code": {"model": "Opus 5.5", "effort": "high"},
    "codex": {"effort": "low"},
    "default": {"model": "Kimi K2"}
  }
}
```

## How it works

The analysis comes from your agent, which reads the issue, the diff and the surrounding source. `skills/mergeatlas/scripts/mergeatlas.py` does the mechanical part: it fetches the PR, runs the searches your agent chooses for affected files, checks the map against the diff, and serves it. Those searches are plain text, so MergeAtlas works in any language. Maps and working files stay on your machine in `~/.cache/mergeatlas`.

## License

[MIT](LICENSE)
