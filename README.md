<p align="center"><img src="skills/mergeatlas/assets/logo-3d.png" width="180" alt="MergeAtlas logo"></p>

# MergeAtlas

An atlas of a change, so you can review code you don't know.

MergeAtlas is an agent skill that turns a pull request into an interactive map on localhost. Each changed component is a card, and arrows show how a change in one reaches another. Unchanged files the PR still affects sit beside the cards that reach them, and every claim links to its lines in the PR.

It's built for one situation: you're asked to review a large change in a project you don't know well. The map gives you the context to review it yourself. It doesn't find bugs, give verdicts, or tell you what to do.

## Requirements

- An agent that runs skills, such as Claude Code
- Python 3
- `git`
- The [GitHub CLI](https://cli.github.com), signed in with `gh auth login`

## Install

Clone the repository and link the skill into your skills folder:

```bash
git clone https://github.com/ismayilkarimli/MergeAtlas.git
```

```bash
ln -s "$PWD/MergeAtlas/skills/mergeatlas" ~/.claude/skills/mergeatlas
```

## Use

From inside the PR's repository, ask your agent to map it, or run `/mergeatlas` in Claude Code. It opens at `http://127.0.0.1:8765`.

The map has two views. **Map** is the canvas of cards and arrows, and **Tree** is a collapsible outline of the same cards with their affected files.

## Tickets

GitHub issues linked to the PR work out of the box. For other trackers, MergeAtlas spots the ticket in the PR's title, description or branch name, and your agent reads it through the connection it already has, such as an MCP server. MergeAtlas stores no tracker credentials of its own.

It recognises links from Jira, Linear, Trello, Asana, Shortcut, ClickUp and Azure Boards, and bare keys like `ENG-123`. If your agent can't reach the tracker, it tells you which ticket it couldn't read and builds the map from the PR alone.

## How it works

The analysis comes from your agent, which reads the issue, the diff and the surrounding source. `skills/mergeatlas/scripts/mergeatlas.py` does the mechanical part: it fetches the PR, lists the candidates for reach, checks the map against the diff, and serves it. Maps and working files stay on your machine in `~/.cache/mergeatlas`.

## License

[MIT](LICENSE)
