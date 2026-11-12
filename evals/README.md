# Judging a change to the skill

## What the set is and why it is fixed

No test can tell you whether a change to `SKILL.md` made maps better, so this folder holds three pull requests to map before and after the change and a script that measures both. The pull requests are fixed so that two runs differ only by the change: all three are merged, so their heads cannot move, and `set.json` pins each head by its full commit id. `prepare` stops with a message when GitHub no longer serves that head.

Each run gets a label of your choosing. A label has a folder of its own under `~/.cache/mergeatlas-evals/runs/<label>`, with its own copy of the skill, its own work folder and its own viewer port, so a run never touches `~/.cache/mergeatlas` and two labels never share state.

## The three pulls

| Key | Pull request | Budget | Time limit | Fixed questions |
|---|---|---|---|---|
| `small` | [excalidraw/excalidraw#10903](https://github.com/excalidraw/excalidraw/pull/10903) | 6 USD | 45 min | 6 |
| `medium` | [excalidraw/excalidraw#11859](https://github.com/excalidraw/excalidraw/pull/11859) | 10 USD | 60 min | 6 |
| `large` | [excalidraw/excalidraw#8613](https://github.com/excalidraw/excalidraw/pull/8613) | 25 USD | 120 min | none |

The questions are in `questions/`, each with the answer a reader should be able to give from the map alone. `large` has no questions file, so its answers are not scored.

## The five commands

Run them from the repository root. The label comes first, then the keys.

`prepare` clones the repository if needed, checks out the pinned head, gives the label a copy of the skill, clears what an earlier run of that key left, and prints the agent's prompt. A label keeps the skill it was first given, so use a new label for a new version.

```bash
python3 evals/run.py prepare v0.4.0 small
```

`collect` writes `<key>.result.json` from the run record and the published map, and stops the label's viewer server.

```bash
python3 evals/run.py collect v0.4.0 small
```

`map` does `prepare`, runs the mapping agent with `claude -p` on Sonnet 5.5 at high effort within the pull's budget and time limit, and then `collect`. Pass `--skill <dir>` to map with another copy of the skill, such as a checkout of an earlier release.

```bash
python3 evals/run.py map v0.4.0 small medium
```

`score` runs the newest `claims` check over every link of the label's maps, and asks each question of the cards alone. A model reads each claim file, and a second model judges the answers against the reference answers.

```bash
python3 evals/run.py score v0.4.0
```

`compare` prints two labels side by side as a Markdown table, one for each pull request both hold a result for.

```bash
python3 evals/run.py compare v0.3.0 v0.4.0
```

## How to measure a change

Map and score the release before the change under one label, and the working tree under another, then compare.

```bash
git worktree add /tmp/mergeatlas-before <the release before the change>
```

```bash
python3 evals/run.py map before small medium --skill /tmp/mergeatlas-before/skills/mergeatlas
```

```bash
python3 evals/run.py map after small medium
```

```bash
python3 evals/run.py score before
```

```bash
python3 evals/run.py score after
```

```bash
python3 evals/run.py compare before after
```

Paste the table into the pull request and say what moved. The `claude` command line has to be signed in first.

## What it costs

A mapping run spends real model usage: each pull has a budget in `set.json` that stops the agent when it is spent, from 6 USD for `small` to 25 USD for `large`, and scoring spends a little more on the checkers and the judge. Run `small` and `medium` for most changes. Run `large` only when a change is about large maps, with `run.py map <label> large`.

## How to read it

The questions are six for each pull and a model judges the answers, so a number that moves a little is noise. Treat a difference of under 2 answers, or under 3 rejected links, as no difference. Time and cost vary from run to run too; they say something only when they move a lot. Rejected publishes, cold-read rounds and cards handed to readers are counts of what the run did, and are steadier.
