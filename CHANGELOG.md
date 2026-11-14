# Changelog

What changed in each release of MergeAtlas, newest first. Versions follow [semantic versioning](https://semver.org): while the version starts with 0, a minor release may change the map format or a command.

If you installed the Claude Code plugin, you stay on a release until the next one is published, then `/plugin marketplace update mergeatlas` brings it in. Installs through skills.sh or a clone follow the `main` branch.

## Unreleased

### Added

- GitLab merge requests, on gitlab.com or a self-hosted GitLab, are mapped as pull requests are, through the `glab` CLI. A merge request link works for fetch, a stack of merge requests is found from the branches they target, and the viewer says "merge request", writes `!7` and opens diff lines in GitLab's own diff where it can.

### Changed

- A map's id now names its host, such as `github-owner-repo-12` and `github-owner-repo-stack-7`, and the viewer takes every address it opens, and the name of the host it shows, from the map. Maps from earlier releases have no such addresses, so publish them again.
- fetch takes a pull request's diff and its file list with their added and removed lines from your clone, where it asked GitHub for them, so a very large pull request no longer fails on a diff GitHub will not send.

### Removed

- The code that kept maps and servers from earlier releases working: a map in the format from before cards held changes is no longer set aside by itself, and a viewer server that names no release is left running with a note instead of being looked up and replaced.

## 0.4.0 - 2026-11-12

### Added

- Every code link is checked against the lines it points at. `claims` writes each link's words and lines to a file for a checker, and `checked` records the links that hold. A link is checked again only when its words or its lines change.
- A fixed set of three pull requests, in `evals/`, to measure a change to the skill against: what a map costs, how many of its links a checker rejects, and how many fixed questions it answers.

### Changed

- A first map is cold read in two rounds, where it took three. From the second round on, and on an update, a reader is asked only about the sentences written or edited since the card was last read.
- A card that only lost sentences passes without a reader.
- `report` says how many links were checked and how many were sent back.

## 0.3.0 - 2026-11-12

### Added

- When a mapped pull request gets new commits, fetch writes a delta file holding only what changed since the last map, and the agent reads that in place of the whole diff.
- A map is now reused change by change: fetch sends back the single changes whose key lines left the diff, lists the changes and arrows whose links to check because a line they link to changed, counts the lines that entered and left each card's diff, and lists the story, intents and arrows to check beside them.
- Fetch runs a changed pull request's logged searches again at the new head and reports the files that newly match or no longer match.
- `readers` writes each unread card to a file for its cold reader, and `passed` records the cards a reader found nothing in, so a card is read again only when its words change.
- `fetch --fresh` maps a pull request again from scratch. A map in a format too old to show starts over by itself.
- A map updated for new commits says which commit it was updated from and marks the cards the new commits changed until you open them. The notice counts the cards still to open.
- An update is cold read in one round, and only on the statements written or edited for it.

### Changed

- The cold reader's instructions now live in the script, and the agent hands each reader a file path where it used to paste the card.
- When more than half of a map's changes would be rewritten, fetch says to map the pull request afresh.
- `report` says how many of a changed map's changes were sent back.

## 0.2.0 - 2026-11-12

### Added

- **A map can be read while it is still being checked.** Publish now serves the map as a draft, and your agent gives you its link then, before the cold read. The viewer says the map is a draft, takes in each later version by itself, and marks the cards whose words changed. In the tree view, or with a card open, it asks before it swaps what you are reading. The new `mergeatlas.py finish <map-id>` ends the draft once the cold read is done.
- **A front page that lists your maps.** `http://127.0.0.1:8765` with no map named lists every map on your machine under its repository, the latest first, with how far you have reviewed each. The MergeAtlas name in a map's panel leads back to it.
- **A map says when it was made, and when the pull request has moved on.** The panel shows the commit a map describes and how long ago it was made. When the pull request has newer commits on GitHub, the map says so and tells you to ask for it to be mapped again.
- Fetch says when a pull request's map was left as a draft by a run that stopped early, so your agent finishes the cold read without writing the map again.

### Changed

- `mergeatlas.py report` gives the time to the first publish and the time to the finished map, and says when the cold read was not finished.
- The viewer's server works out two more answers besides the files it hands out: the list of maps for the front page, and where a mapped pull request stands on GitHub, which it asks `gh` for once a minute per open map at most.
- A map the viewer cannot draw, such as one in the form an older release wrote, says so. Before, it opened as an empty canvas.
- The "No map found" message says "your agent" where it said "Claude".

## 0.1.0 - 2026-11-12

The first numbered release. It holds everything MergeAtlas did before releases had numbers: the map and tree views, the story, intents, arrows and affected files, tickets from other trackers, the cold read, sharing a map as one HTML file, and maps for stacked pull requests.

New in this release:

### Added

- `mergeatlas.py report <map-id>` sums up how a map's run went: the size of the pull request, the searches, what publish rejected the map for, the cold-read rounds, the size of the map and the time it took. It prints numbers alone, with no code, paths, repository name or words from the map, so it can go into a bug report as it stands.
- `mergeatlas.py version` prints the version, and the script says so when it is run on a Python older than 3.9.
- Publish rejects a card or intent whose id is not made of letters, digits, `-` and `_`.

### Security

- The viewer now escapes quotes in the text it shows. Before, a pull request whose title held a `"` could add attributes of its own to the stack strip of a map, and so run script in the viewer or in a shared map file.
- The viewer's server now hands out the viewer and the published maps and nothing else. Before, it served the whole cache folder, which also holds the diff and description of every pull request mapped.
- The server refuses a request made under any host name but `127.0.0.1` and `localhost`, so a web page that points its own domain at your machine cannot read your maps.
- A server left running by an older release is stopped and replaced the next time a map is published.
