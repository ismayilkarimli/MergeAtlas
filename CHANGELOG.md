# Changelog

What changed in each release of MergeAtlas, newest first. Versions follow [semantic versioning](https://semver.org): while the version starts with 0, a minor release may change the map format or a command.

If you installed the Claude Code plugin, you stay on a release until the next one is published, then `/plugin marketplace update mergeatlas` brings it in. Installs through skills.sh or a clone follow the `main` branch.

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
