# Security

## Reporting a problem

Report a vulnerability privately through GitHub: on the repository's **Security** tab, choose **Report a vulnerability**. Please don't open a public issue for it.

Fixes go into the next release, and `CHANGELOG.md` lists them under **Security**. Only the latest release gets fixes.

## What MergeAtlas does on your machine

Knowing this helps you judge a report, or a risk.

- **It reads a pull request through your own tools.** The script calls `gh` and `git` with the access you already have. It stores no credentials, and it reads tickets through whatever tracker connection your agent has.
- **It keeps what it reads in `~/.cache/mergeatlas`.** `work/` holds each mapped pull request's diff, title, description and linked issues, along with the map being written. `data/` holds the published maps. For a private repository, both hold private code.
- **It serves maps on `127.0.0.1:8765`.** The server hands out the viewer and the files in `data/`, and nothing in `work/`. It refuses requests made under any host name but `127.0.0.1` and `localhost`. It has no login, so any program running as you on the same machine can read published maps, as it can read the folder itself.
- **A shared map is a file that runs script.** The HTML file from the Share button or `export` holds the viewer and one map, including the code lines the map quotes. Open one only from someone you would accept a pull request link from.
- **The viewer loads its fonts from Google Fonts.** That is the only request a map makes to another machine. Links in a map open GitHub or your tracker when you click them.

## What counts as a vulnerability

A map carries text that someone else wrote: a pull request's title and description, ticket text, file paths and code. These are in scope:

- text in a map that runs script in the viewer or in a shared map file;
- a web page, or another machine on your network, reading maps or working files from the server;
- the script running a command, or writing a file outside its cache and the path you gave `export`, because of what a pull request or ticket contains.

A map that states something untrue about the code is a bug, not a vulnerability. Please report it as a [bad map](https://github.com/ismayilkarimli/MergeAtlas/issues/new/choose).
