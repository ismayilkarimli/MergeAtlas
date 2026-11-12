# Changelog

What changed in each release of MergeAtlas, newest first. Versions follow [semantic versioning](https://semver.org): while the version starts with 0, a minor release may change the map format or a command.

If you installed the Claude Code plugin, you stay on a release until the next one is published, then `/plugin marketplace update mergeatlas` brings it in. Installs through skills.sh or a clone follow the `main` branch.

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
