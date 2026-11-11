#!/usr/bin/env python3
"""Mechanical half of the mergeatlas skill.

  mergeatlas.py fetch [number]   Fetch a PR into the work directory.
  mergeatlas.py search <map-id> [--substring | --regex | --paths] <term>
                                 Search the PR's head commit outside its changed files and log the result.
                                 Matches whole words unless --substring or --regex.
  mergeatlas.py publish <map-id> Validate <map-id>.input.json, write the map, serve it.
  mergeatlas.py export <map-id> [path]
                                 Write the published map as one HTML file that opens in any browser, for sharing.
  mergeatlas.py card <map-id> <card-id | story>
                                 Print one card as a cold reader sees it, for the cold read.
  mergeatlas.py serve            Run the viewer server; publish starts it when needed.
  mergeatlas.py config           Print the config file's path and the model each agent gives its cold readers.
  mergeatlas.py config set <agent> <model | own> [effort]
                                 Save the cold readers' model for an agent; own means the agent's own model.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.request
from collections import Counter
from functools import lru_cache, partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

HOME = Path.home() / ".cache" / "mergeatlas"
WORK = HOME / "work"
DATA = HOME / "data"
VIEWER = Path(__file__).resolve().parent.parent / "assets" / "viewer.html"
PORT = 8765
# The viewer's empty slot for a map carried inside the page, which a shared file opens without a server.
MAP_SLOT = '<script type="application/json" id="map-data"></script>'
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "mergeatlas" / "config.json"
# The cold readers' model for each agent; "default" covers any other agent, and an empty entry means its own model.
COLD_READ = {
    "claude-code": {"model": "Sonnet 5.5", "effort": "medium"},
    "codex": {"model": "Sol 6.1", "effort": "medium"},
    "default": {},
}
SETTINGS = ("model", "effort")

KINDS = {"core", "cleanup", "test", "docs", "config"}
EDGE_KINDS = {"enables", "replaces", "verifies", "docs", "depends"}
CARD_FIELDS = ("id", "kind", "title", "paths", "summary", "bullets", "changes")
INTENT_FIELDS = ("id", "title", "outcome")
BUILDS_ON_FIELDS = ("intent", "label", "how")
EDGE_FIELDS = ("from", "to", "kind", "label", "relationship", "connection", "connection_code", "connection_at", "flow")
CARD_TEXT = ("summary", "bullets")
CHANGE_TEXT = ("problem", "change", "result")
EDGE_TEXT = ("relationship", "connection", "flow", "effect")
CARD_LINK = re.compile(r"\[[^\]]+\]\(([\w-]+)\)")
LOCATION = r"([^)#\s]+)#L(\d+)(?:-L(\d+))?"
CODE_LINK = re.compile(r"\[[^\]]+\]\(" + LOCATION + r"\)")
ANY_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
CODE_SPAN = re.compile(r"`[^`]*`")
SENTENCE_END = re.compile(r"(?<=[.!?:])\s+")
# Words that send the reader elsewhere; bare "above" and "below" stay out, as they also place things on screen or compare values.
POINTER = re.compile(
    r"\b((described|mentioned|shown|noted|listed|explained|discussed|covered|see|seen)\s+(above|below|earlier)"
    r"|(earlier|previous|next)\s+cards?)\b",
    re.I,
)
FILE_HEADER = re.compile(r"diff --git a/.* b/(.*)$")
HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@ ?(.*)$")
REACH_KINDS = {"core", "cleanup"}
MECHANICAL_REASONS = {"whitespace", "formatting", "comments", "rename", "generated", "snapshot"}
INDENTED_SUFFIXES = (".py", ".pyi", ".yaml", ".yml", ".mk")
INDENTED_NAMES = {"Makefile", "GNUmakefile", "makefile"}
SURROUNDING_LINES = 4
SHOWN_FILES = 30
SHOWN_MATCHES = 3
COCHANGE_COMMITS = 200
COCHANGE_LARGEST_COMMIT = 50
COCHANGE_MIN_COMMITS = 3
COCHANGE_MIN_SHARE = 0.3
COCHANGE_FILES = 10
# Files that change alongside almost anything, so a co-change with them says nothing about reach.
COCHANGE_NOISE = re.compile(
    r"(^|/)(__snapshots__|goldens?)/"
    r"|\.(snap|golden|lock|min\.js|min\.css|map)$"
    r"|(^|/)(package-lock\.json|npm-shrinkwrap\.json|pnpm-lock\.yaml|go\.sum)$"
    r"|(^|/)(?i:CHANGELOG|CHANGES|HISTORY|RELEASES?|NEWS)(\.(md|markdown|txt|rst|adoc))?$"
)
TICKET_URLS = {
    "Jira": r"https://[\w-]+\.atlassian\.net/browse/[A-Z][A-Z0-9]+-\d+",
    "Linear": r"https://linear\.app/[\w-]+/issue/[A-Z0-9]+-\d+",
    "Trello": r"https://trello\.com/c/\w+",
    "Asana": r"https://app\.asana\.com/[\w/-]+",
    "Shortcut": r"https://app\.shortcut\.com/[\w-]+/story/\d+",
    "ClickUp": r"https://app\.clickup\.com/t/\w+",
    "Azure Boards": r"https://dev\.azure\.com/[\w-]+/[^/\s]+/_workitems/edit/\d+",
}
TICKET_KEY = re.compile(r"(?<![\w/.-])[A-Z][A-Z0-9]{1,9}-\d+\b")
BRANCH_KEY = re.compile(r"(?:^|/)([A-Za-z][A-Za-z0-9]{1,9}-\d+)(?![A-Za-z0-9])")


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def text_only(diff):
    """Drops the sections of binary files, which have nothing to read."""
    sections, current = [], []
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git ") and current:
            sections.append(current)
            current = []
        current.append(line)
    sections.append(current)
    return "".join(
        "".join(s) for s in sections if not any(l.startswith(("Binary files", "GIT binary patch")) for l in s)
    )


def files_at(commit):
    listed = subprocess.run(["git", "ls-tree", "-r", "-z", "--name-only", commit], check=True, capture_output=True, text=True)
    return set(filter(None, listed.stdout.split("\0")))


def co_changes(changed, commit):
    """Maps each changed file to the unchanged files its past commits often touched too."""
    existing, found = {f for f in files_at(commit) - changed if not COCHANGE_NOISE.search(f)}, {}
    for path in sorted(changed):
        log = subprocess.run(
            ["git", "log", "-n", str(COCHANGE_COMMITS), "--format=%x00", "--name-only", "--no-renames", "--full-diff",
             commit, "--", path],
            capture_output=True, text=True, errors="replace",
        ).stdout
        commits = [set(filter(None, c.split("\n"))) for c in log.split("\0")[1:]]
        commits = [c for c in commits if len(c) <= COCHANGE_LARGEST_COMMIT]
        counts = Counter(file for c in commits for file in c & existing)
        together = {file: n for file, n in counts.most_common(COCHANGE_FILES)
                    if n >= COCHANGE_MIN_COMMITS and n / len(commits) >= COCHANGE_MIN_SHARE}
        if together:
            found[path] = together
    return found


def ticket_refs(title, body, branch):
    """Lists what looks like a ticket outside GitHub; the keys are candidates, as UTF-8 matches too."""
    text = f"{title}\n{body}"
    urls = {url: name for name, pattern in TICKET_URLS.items() for url in re.findall(pattern, text)}
    keys = [*TICKET_KEY.findall(text), *(key.upper() for key in BRANCH_KEY.findall(branch))]
    return [*(f"{name} {url}" for url, name in urls.items()), *dict.fromkeys(keys)]


PR_OR_STACK = re.compile(r"(?:https?://)?(?:www\.)?github\.com/([\w.-]+/[\w.-]+)/(pull|stack)/(\d+)(?:[/?#].*)?")


def parse_target(text):
    """Reads a PR or stack link, or a bare PR number, as (kind, repo, number); a bare number has no repo."""
    text = text.strip()
    bare = re.fullmatch(r"#?(\d+)", text)
    if bare:
        return ("pr", None, int(bare[1]))
    link = PR_OR_STACK.fullmatch(text)
    if not link:
        raise ValueError(f"not a GitHub pull request or stack link: {text!r}")
    return ("pr" if link[2] == "pull" else "stack", link[1], int(link[3]))


def parse_fetch_args(args):
    """Splits fetch's arguments into its targets and whether the user asked for the whole stack."""
    return [parse_target(a) for a in args if a != "--stack"], "--stack" in args


def open_or_merged(pulls):
    return [p for p in pulls if p["state"] != "closed"]


def stack_by_branches(repo, pull, github, known, strict):
    """Finds a stack built without GitHub's stacks: each PR's base branch is the head branch of the PR below it.
    Above a fork the chain has no single next PR, so strict fails there and otherwise stops."""
    chain, seen = [pull], {pull["number"]}
    while True:
        below = open_or_merged(github.pulls_with_head(repo, chain[0]["base"]))
        if len(below) != 1 or below[0]["number"] in seen:
            break
        chain.insert(0, below[0])
        seen.add(below[0]["number"])
    while True:
        above = open_or_merged(github.pulls_with_base(repo, chain[-1]["head"]))
        if len(above) > 1 and strict:
            names = " and ".join(f"#{p['number']}" for p in sorted(above, key=lambda p: p["number"]))
            raise ValueError(f"the stack forks above #{chain[-1]['number']} into {names}, so it is not one stack")
        if len(above) != 1 or above[0]["number"] in seen:
            break
        chain.append(above[0])
        seen.add(above[0]["number"])
    if len(chain) == 1:
        return None
    known.update({p["number"]: p for p in chain})
    return {"number": None, "source": "branches", "base": chain[0]["base"], "prs": [p["number"] for p in chain]}


def stack_of(repo, pull, github, known, strict):
    """The stack a PR sits in: GitHub's own when it has one, else the chain of base branches."""
    if pull.get("stack"):
        found = github.stack(repo, pull["stack"]["number"])
        return {"number": found["number"], "source": "native", "base": found["base"], "prs": found["prs"]}
    return stack_by_branches(repo, pull, github, known, strict)


def resolve(targets, github, whole_stack=False):
    """Decides which PRs to map, bottom to top, and the stack they sit in.
    A stack link maps the whole stack; a PR link maps that PR unless whole_stack; several PRs map the run between them."""
    repos = {repo or github.current_repo() for _, repo, _ in targets}
    if len(repos) != 1:
        raise ValueError(f"links from more than one repository: {', '.join(sorted(repos))}")
    repo = repos.pop()
    stacks = sorted({n for kind, _, n in targets if kind == "stack"})
    listed = list(dict.fromkeys(n for kind, _, n in targets if kind == "pr"))
    if len(stacks) > 1:
        raise ValueError(f"links to more than one stack: {', '.join(f'#{n}' for n in stacks)}")
    known = {n: github.pull(repo, n) for n in listed}
    if len(listed) > 1:
        for n in listed:
            if known[n]["state"] == "merged":
                raise ValueError(f"#{n} is already merged, so it has nothing left to review")
    if stacks:
        found = github.stack(repo, stacks[0])
        stack = {"number": found["number"], "source": "native", "base": found["base"], "prs": found["prs"]}
        whole_stack = True
    else:
        stack = stack_of(repo, known[listed[0]], github, known, strict=whole_stack)
    if stack is None:
        if len(listed) > 1:
            raise ValueError(f"#{listed[0]} is in no stack, so {', '.join(f'#{n}' for n in listed[1:])} cannot share one with it")
        return {"repo": repo, "stack": None, "map": listed, "added": []}
    outside = [n for n in listed if n not in stack["prs"]]
    if outside:
        raise ValueError(f"{', '.join(f'#{n}' for n in outside)} not in the same stack as #{stack['prs'][0]}-#{stack['prs'][-1]}")
    if whole_stack:
        for n in stack["prs"]:
            if n not in known:
                known[n] = github.pull(repo, n)
        chosen = [n for n in stack["prs"] if known[n]["state"] == "open"]
    else:
        positions = [stack["prs"].index(n) for n in listed]
        chosen = stack["prs"][min(positions):max(positions) + 1]
    added = [] if whole_stack else [n for n in chosen if n not in listed]
    return {"repo": repo, "stack": stack, "map": chosen, "added": added}


def pull_record(p):
    """Cuts a pull request from GitHub's REST API down to what stack detection reads."""
    state = "merged" if p.get("merged_at") else p["state"]
    stack = p.get("stack")
    return {
        "number": p["number"], "title": p["title"], "url": p["html_url"], "state": state,
        "base": p["base"]["ref"], "head": p["head"]["ref"],
        "stack": {k: stack[k] for k in ("number", "position", "size")} if stack else None,
    }


class GhGitHub:
    """Reads pull requests and stacks through the signed-in GitHub CLI."""

    def _api(self, path):
        try:
            return json.loads(gh("api", path))
        except subprocess.CalledProcessError as failed:
            raise LookupError(f"GitHub has no {path}: {failed.stderr.strip()}") from None

    def current_repo(self):
        return gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()

    def pull(self, repo, number):
        return pull_record(self._api(f"repos/{repo}/pulls/{number}"))

    def stack(self, repo, number):
        found = self._api(f"repos/{repo}/stacks/{number}")
        return {"number": found["number"], "base": found["base"]["ref"], "prs": [p["number"] for p in found["pull_requests"]]}

    def _pulls(self, repo, query):
        return [pull_record(p) for p in self._api(f"repos/{repo}/pulls?state=all&per_page=100&{query}")]

    def pulls_with_head(self, repo, branch):
        return self._pulls(repo, f"head={quote(repo.split('/')[0])}:{quote(branch)}")

    def pulls_with_base(self, repo, branch):
        return self._pulls(repo, f"base={quote(branch)}")


def fetch(number):
    fields = "number,title,body,additions,deletions,files,headRefName,headRefOid,url,closingIssuesReferences"
    pr = json.loads(gh("pr", "view", *number, "--json", fields))
    repo = pr["url"].split("/pull/")[0].split("github.com/")[1]
    map_id = f"{repo.replace('/', '-')}-{pr['number']}"
    pr["issues"] = [
        json.loads(gh("issue", "view", str(i["number"]), "--repo", repo, "--json", "number,title,body,url"))
        for i in pr.pop("closingIssuesReferences")
    ]
    WORK.mkdir(parents=True, exist_ok=True)
    diff_path = WORK / f"{map_id}.diff"
    diff_path.write_text(text_only(gh("pr", "diff", str(pr["number"]), "--repo", repo)))
    subprocess.run(["git", "fetch", "origin", f"pull/{pr['number']}/head"], check=True, capture_output=True)
    changed = {f["path"] for f in pr["files"]}
    together = co_changes(changed, pr["headRefOid"])
    cochange_path = WORK / f"{map_id}.cochange.json"
    cochange_path.write_text(json.dumps(together, indent=2))
    (WORK / f"{map_id}.searches.json").write_text("[]")
    (WORK / f"{map_id}.pr.json").write_text(json.dumps(pr))
    print(f"map id:      {map_id}")
    print(f"work dir:    {WORK}")
    print(f"head commit: {pr['headRefOid']}")
    print(f"diff:        {diff_path} ({len(diff_path.read_text().splitlines())} lines, binary files omitted)")
    print(f"co-changes:  {cochange_path} ({len({u for file in together.values() for u in file})} unchanged files often change with these)")
    print(f"title:       {pr['title']}")
    print(f"description: {pr['body'] or '(none)'}")
    for issue in pr["issues"]:
        print(f"linked issue #{issue['number']}: {issue['title']}\n{issue['body']}")
    if not pr["issues"]:
        print("linked issue: none")
    for ticket in ticket_refs(pr["title"], pr["body"], pr["headRefName"]):
        print(f"possible ticket: {ticket}")
    print(f"files ({len(pr['files'])}):")
    for f in pr["files"]:
        print(f"  +{f['additions']} -{f['deletions']} {f['path']}")


def matches_of(term, mode, commit):
    """Maps the files holding the term to their matching lines."""
    flags = {"word": ["-F", "-w"], "substring": ["-F"], "regex": ["-E"]}[mode]
    found = subprocess.run(
        ["git", "grep", "-n", "-I", "--null", *flags, "-e", term, commit],
        capture_output=True, text=True, errors="replace",
    )
    if found.returncode > 1:
        sys.exit(found.stderr)
    matches = {}
    for match in filter(None, found.stdout.split("\n")):
        location, line, text = match.split("\0", 2)
        matches.setdefault(location.split(":", 1)[1], []).append(f"{line}: {text.strip()[:160]}")
    return matches


def search(map_id, term, mode):
    pr = json.loads((WORK / f"{map_id}.pr.json").read_text())
    commit, changed = pr["headRefOid"], {f["path"] for f in pr["files"]}
    if mode == "paths":
        matches = {path: [] for path in files_at(commit) if term in path}
    else:
        matches = matches_of(term, mode, commit)
    matches = {path: lines for path, lines in sorted(matches.items()) if path not in changed}
    log_path = WORK / f"{map_id}.searches.json"
    log = [s for s in json.loads(log_path.read_text()) if (s["term"], s["mode"]) != (term, mode)]
    log.append({"term": term, "mode": mode, "files": list(matches)})
    log_path.write_text(json.dumps(log, indent=2))
    print(f"{len(matches)} unchanged files match {term!r}")
    for path, lines in list(matches.items())[:SHOWN_FILES]:
        print(path)
        for line in lines[:SHOWN_MATCHES]:
            print(f"  {line}")
        if len(lines) > SHOWN_MATCHES:
            print(f"  ... {len(lines) - SHOWN_MATCHES} more")
    rest = list(matches)[SHOWN_FILES:]
    if rest:
        print(f"... {len(rest)} more files, every one of which needs sorting:")
        for path in rest:
            print(path)


def source_at(commit):
    """Returns a reader for a file's lines at commit, None when it is not there."""
    @lru_cache(maxsize=None)
    def read(path):
        shown = subprocess.run(["git", "show", f"{commit}:{path}"], capture_output=True, text=True, errors="replace")
        return shown.stdout.splitlines() if shown.returncode == 0 else None
    return read


def cited_lines(read, path, first, last):
    lines = read(path)
    last = last or first
    if lines is None or not 1 <= int(first) <= int(last) <= len(lines):
        return None
    return lines[int(first) - 1:int(last)]


def connection_lines(read, at):
    """Shows an arrow's connecting lines as a snippet: the cited lines at the head commit, with the lines around them."""
    path, first, last = re.fullmatch(LOCATION, at).groups()
    lines, first, last = read(path), int(first), int(last or first)
    return [{"text": f" {lines[n - 1]}", "path": path, "line": f"R{n}", "key": first <= n <= last}
            for n in range(max(1, first - SURROUNDING_LINES), min(len(lines), last + SURROUNDING_LINES) + 1)]


def diff_rows(diff):
    """Maps each file to its diff lines as (text, anchor, hunk), with anchors as GitHub numbers them."""
    rows, current, old, new, number = {}, None, 0, 0, 0
    for line in diff.splitlines():
        header = FILE_HEADER.match(line)
        hunk = HUNK_HEADER.match(line)
        if header:
            current = None
            path = header.group(1)
        elif hunk:
            current = rows.setdefault(path, [])
            old, new, number = int(hunk.group(1)), int(hunk.group(2)), number + 1
        elif current is None or line.startswith("\\"):
            continue
        elif line.startswith("-"):
            current.append((line, f"L{old}", number))
            old += 1
        else:
            current.append((line, f"R{new}", number))
            new += 1
            old += not line.startswith("+")
    return rows


def key_lines(card, code, rows):
    """Locates a snippet in its card's diff, taking the tightest in-order match."""
    wanted = [l.rstrip() for l in code.splitlines()]
    best = None
    for path in card["paths"]:
        file_rows = rows.get(path, [])
        for start, row in enumerate(file_rows):
            if row[0].rstrip() != wanted[0]:
                continue
            found = [start]
            for line in wanted[1:]:
                after = found[-1] + 1
                found.append(next((i for i in range(after, len(file_rows)) if file_rows[i][0].rstrip() == line), None))
                if found[-1] is None:
                    break
            if found[-1] is not None and (best is None or found[-1] - found[0] < best[2][-1] - best[2][0]):
                best = (path, file_rows, found)
    if best is None:
        return None
    path, file_rows, found = best
    shown = sorted({
        near for i in found
        for near in range(max(0, i - SURROUNDING_LINES), min(len(file_rows), i + SURROUNDING_LINES + 1))
        if file_rows[near][2] == file_rows[i][2]
    })
    lines = []
    for before, i in zip([shown[0] - 1, *shown], shown):
        if i != before + 1:
            lines.append({"gap": True})
        lines.append({"text": file_rows[i][0], "path": path, "line": file_rows[i][1], "key": i in found})
    return lines


def whitespace_only(path, rows):
    """Tells whether a file's removed and added lines match once all whitespace is stripped."""
    def stripped(mark):
        return "".join("".join(line[1:].split()) for line, *_ in rows.get(path, []) if line.startswith(mark))
    return stripped("-") == stripped("+")


def indented(path):
    name = Path(path).name
    return name in INDENTED_NAMES or name.endswith(INDENTED_SUFFIXES)


def fingerprint(card, rows):
    """Identifies a card's diff by its text, so moved lines keep the same value."""
    text = "\n".join(line for path in card["paths"] for line, *_ in rows.get(path, []))
    return hashlib.sha256(text.encode()).hexdigest()


def candidates_in(searches, broad, together):
    """Maps each file a kept search or past commits surfaced to where it came from."""
    dropped = {entry.get("term") for entry in broad}
    sources = {}
    for s in searches:
        if s["term"] not in dropped:
            for path in s["files"]:
                sources.setdefault(path, f"search {s['term']!r}")
    for files in together.values():
        for path in files:
            sources.setdefault(path, "co-change")
    return sources


def cites(text, refs):
    """Tells whether text names one of the PR's issues or tickets, such as #123 or ENG-123."""
    return any(re.search(rf"(?<![\w/-]){re.escape(ref)}(?![\w-])", text) for ref in refs)


def open_whys(name, text, refs=()):
    """Finds the two shapes a script can see: a reason that stops short of the code or the issue, and a lean on another card."""
    found = []
    for sentence in SENTENCE_END.split(text):
        words = CODE_SPAN.sub("code", sentence)
        reason = re.search(r"\bbecause\b(.*)", words, re.I)
        if reason and not CODE_LINK.search(reason[1]) and not cites(reason[1], refs):
            found.append(f"{name}: a reason ends with no code link, or issue or ticket it comes from, after its because: {sentence!r}")
        pointer = POINTER.search(ANY_LINK.sub(r"\1", words))
        if pointer:
            found.append(f"{name}: leans on {pointer[0]!r}, so name the thing itself: {sentence!r}")
    return found


def problems_in(data, stats, read, rows, searches, together, issues=()):
    found, seen, ids, accounted = [], set(), set(), set()
    refs = {f"#{i['number']}" for i in issues} | {t["key"] for t in data.get("tickets", []) if t.get("key")}
    whys = partial(open_whys, refs=refs)
    for ticket in data.get("tickets", []):
        if not (ticket.get("key") and ticket.get("title")):
            found.append(f"ticket {ticket}: needs key and title")
        if not str(ticket.get("url")).startswith("https://"):
            found.append(f"ticket {ticket.get('key')}: url must start with https://")

    def check_links(name, item, fields):
        for path, first, last in CODE_LINK.findall(" ".join(str(item.get(k, "")) for k in fields)):
            if cited_lines(read, path, first, last) is None:
                found.append(f"{name}: no such lines {path}#L{first}" + (f"-L{last}" if last else ""))

    for c in data.get("cards", []):
        name = c.get("id", "?")
        found += [f"card {name}: missing {k}" for k in CARD_FIELDS if not c.get(k)]
        shown = {}
        has_lines = any(rows.get(path) for path in c.get("paths", []))
        for number, change in enumerate(c.get("changes", []), 1):
            where = f"card {name} change {number}"
            found += [f"{where}: missing {k}" for k in CHANGE_TEXT if not change.get(k)]
            check_links(where, change, CHANGE_TEXT)
            for field in CHANGE_TEXT:
                found += whys(f"{where} {field}", change.get(field) or "")
            if not CODE_LINK.search(change.get("change", "")):
                found.append(f"{where}: change has no code link")
            if has_lines and not change.get("snippets"):
                found.append(f"{where}: has no key lines")
            for code in change.get("snippets", []):
                shown.setdefault(code, []).append(change)
                if not key_lines(c, code, rows):
                    found.append(f"{where}: a snippet is not in the diff of one of its files, in order")
                if not any(line.startswith(("+", "-")) for line in code.splitlines()):
                    found.append(f"{where}: its key lines change nothing, so this is no change of this PR")
        for code, changes in shown.items():
            if len({change.get("problem") for change in changes}) < len(changes):
                found.append(f"card {name}: changes {[number for number, change in enumerate(c['changes'], 1) if change in changes]} share lines, so each states its own problem")
        if c.get("kind") in REACH_KINDS and len(c.get("paths", [])) > 1:
            found.append(f"card {name}: a {c['kind']} card holds one file")
        check_links(f"card {name}", c, CARD_TEXT)
        found += whys(f"card {name} summary", c.get("summary") or "")
        reaches, unaffected = c.get("reaches", []), c.get("unaffected", [])
        for entry in reaches:
            check_links(f"card {name}", entry, ("effect",))
            found += whys(f"card {name} reach", entry.get("effect", ""))
            if not CODE_LINK.search(entry.get("effect", "")):
                found.append(f"card {name}: a reaches entry has no code link in its effect")
        found += [f"card {name}: an unaffected entry has no reason" for entry in unaffected if not entry.get("reason")]
        listed = {p for entry in reaches + unaffected for p in entry.get("paths", [])}
        found += [f"card {name}: no such file {p}" for p in sorted(listed) if read(p) is None]
        accounted |= listed
        if c.get("kind") not in KINDS:
            found.append(f"card {name}: unknown kind {c.get('kind')}")
        if name in ids:
            found.append(f"card {name}: duplicate id")
        ids.add(name)
        for p in c.get("paths", []):
            if p not in stats:
                found.append(f"card {name}: {p} is not in this PR")
            if p in seen:
                found.append(f"card {name}: {p} is already in another card")
            seen.add(p)
    found += [f"no card holds {p}" for p in sorted(set(stats) - seen)]
    broad = data.get("broad_searches", [])
    logged = {s["term"] for s in searches}
    if not searches and any(c.get("kind") in REACH_KINDS for c in data.get("cards", [])):
        found.append("no searches logged: run search for what this PR changes")
    found += [f"broad search {e.get('term')!r}: not in the search log" for e in broad if e.get("term") not in logged]
    found += [f"broad search {e.get('term')!r}: no reason" for e in broad if not e.get("reason")]
    reach_paths = {p for c in data.get("cards", []) if c.get("kind") in REACH_KINDS for p in c.get("paths", [])}
    sources = candidates_in(searches, broad, {path: files for path, files in together.items() if path in reach_paths})
    found += [f"not accounted for: {p} (from {sources[p]})" for p in sorted(sources.keys() - accounted)]
    intents = data.get("intents", [])
    intent_ids = [g.get("id", "?") for g in intents]
    for at, g in enumerate(intents):
        name = g.get("id", "?")
        found += [f"intent {name}: missing {k}" for k in INTENT_FIELDS if not g.get(k)]
        if name in ids or intent_ids.index(name) != at:
            found.append(f"intent {name}: duplicate id")
        found += whys(f"intent {name} outcome", g.get("outcome") or "")
        for base in g.get("builds_on", []):
            where = f"intent {name} builds on {base.get('intent')}"
            found += [f"{where}: missing {k}" for k in BUILDS_ON_FIELDS if not base.get(k)]
            if base.get("intent") not in intent_ids[:at]:
                found.append(f"{where}: builds only on an intent listed before it")
            check_links(where, base, ("how",))
            found += whys(f"{where} how", base.get("how") or "")
            if not CODE_LINK.search(base.get("how", "")):
                found.append(f"{where}: how has no code link")
    mechanical = [g.get("id") for g in intents if g.get("mechanical")]
    if len(mechanical) > 1:
        found.append(f"intents {mechanical}: one mechanical intent holds every mechanical change")
    used = {}
    for c in data.get("cards", []):
        reasons = set()
        for number, change in enumerate(c.get("changes", []), 1):
            where = f"card {c.get('id', '?')} change {number}"
            if change.get("intent") not in intent_ids:
                found.append(f"{where}: no intent {change.get('intent')}")
            used.setdefault(change.get("intent"), set()).add(c.get("kind"))
            reason = change.get("mechanical")
            reasons.add(reason)
            if change.get("intent") in mechanical and reason not in MECHANICAL_REASONS:
                found.append(f"{where}: a mechanical change names its reason, one of {sorted(MECHANICAL_REASONS)}")
            if change.get("intent") not in mechanical and reason:
                found.append(f"{where}: only a change in the mechanical intent has a mechanical reason")
        if reasons == {"whitespace"}:
            for p in c.get("paths", []):
                if indented(p):
                    found.append(f"card {c.get('id', '?')}: indentation is logic in {p}, so its changes are not whitespace")
                elif not whitespace_only(p, rows):
                    found.append(f"card {c.get('id', '?')}: {p} changes more than whitespace")
    found += [f"intent {i}: no change" for i in intent_ids if i not in used]
    found += [f"intent {i}: every change is a test, so it joins the intent its assertions check"
              for i in intent_ids if i not in mechanical and used.get(i) == {"test"}]
    for e in data.get("edges", []):
        name = f"{e.get('from')} -> {e.get('to')}"
        found += [f"arrow {name}: missing {k}" for k in EDGE_FIELDS if not e.get(k)]
        if e.get("kind") not in EDGE_KINDS:
            found.append(f"arrow {name}: unknown kind {e.get('kind')}")
        if e.get("from") == e.get("to"):
            found.append(f"arrow {name}: points at itself")
        found += [f"arrow {name}: no card {e[k]}" for k in ("from", "to") if e.get(k) not in ids]
        check_links(f"arrow {name}", e, EDGE_TEXT)
        for field in EDGE_TEXT:
            found += whys(f"arrow {name} {field}", e.get(field) or "")
        found += [f"arrow {name}: {k} has no code link" for k in ("relationship", "flow") if not CODE_LINK.search(e.get(k, ""))]
        at = re.fullmatch(LOCATION, e.get("connection_at", ""))
        cited = at and cited_lines(read, *at.groups())
        if not cited:
            found.append(f"arrow {name}: no such lines {e.get('connection_at')}")
        else:
            source = "\n".join(cited)
            found += [f"arrow {name}: not at {e['connection_at']}: {l.strip()}"
                      for l in e.get("connection_code", "").splitlines() if l.strip() not in source]
    found += [f"missing {k}" for k in ("background", "problem", "solution") if not data.get(k)]
    linked = set(CARD_LINK.findall(data.get("solution", "")))
    found += [f"solution links to unknown card or intent {i}" for i in sorted(linked - ids - set(intent_ids))]
    found += [f"solution has no link to intent {i}" for i in intent_ids if i not in mechanical and i not in linked]
    return found


class NoStoreHandler(SimpleHTTPRequestHandler):
    """Keeps browsers from pairing a cached viewer with a newly published map."""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def plain(text):
    """Keeps a link's words and marks where it points, so a cold reader can tell a linked claim from a bare one."""
    text = CODE_LINK.sub(lambda m: f"{m[0][1:m[0].index('](')]} [→ code]", text or "")
    return ANY_LINK.sub(r"\1 [→ card]", text)


def card_text(map_id, card_id):
    """Prints one card as a cold reader sees it: link targets give way to a mark, so only the words count."""
    data = json.loads((WORK / f"{map_id}.input.json").read_text())
    if card_id == "story":
        print("\n\n".join(plain(data.get(k)) for k in ("background", "problem", "solution")))
        for g in data.get("intents", []):
            print(f"\nintent {g['id']}: {g['title']}\noutcome: {plain(g['outcome'])}")
            for base in g.get("builds_on", []):
                print(f"builds on {base['intent']}: {plain(base['how'])}")
        return
    cards = {c["id"]: c for c in data["cards"]}
    if card_id not in cards:
        sys.exit(f"no card {card_id}: choose from story, {', '.join(cards)}")
    c = cards[card_id]
    print(f"# {', '.join(c['paths'])}")
    print(f"\nsummary: {plain(c['summary'])}")
    for number, change in enumerate(c["changes"], 1):
        print(f"\nchange {number}, intent {change['intent']}")
        for field in CHANGE_TEXT:
            print(f"{field}: {plain(change[field])}")
        for code in change.get("snippets", []):
            print(f"key lines:\n{code}")
    for r in c.get("reaches", []):
        print(f"\nalso reaches {', '.join(r['paths'])}: {plain(r['effect'])}")
    for u in c.get("unaffected", []):
        print(f"\nunaffected {', '.join(u['paths'])}: {plain(u['reason'])}")
    for e in data["edges"]:
        if card_id in (e["from"], e["to"]):
            other = cards[e["to"] if e["from"] == card_id else e["from"]]
            direction = "to" if e["from"] == card_id else "from"
            print(f"\narrow {direction} {', '.join(other['paths'])}: {e['label']}\n{e['connection_code']}")
            for field in EDGE_TEXT:
                if e.get(field):
                    print(f"{field}: {plain(e[field])}")


def run_server():
    ThreadingHTTPServer(("127.0.0.1", PORT), partial(NoStoreHandler, directory=HOME)).serve_forever()


def serve():
    with socket.socket() as s:
        running = s.connect_ex(("127.0.0.1", PORT)) == 0
    if running:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/index.html", timeout=3) as res:
                if b"id=\"world\"" in res.read():
                    return
        except OSError:
            pass
        sys.exit(f"Port {PORT} is in use by something other than the MergeAtlas viewer.")
    subprocess.Popen(
        [sys.executable, __file__, "serve"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )


def publish(map_id):
    pr = json.loads((WORK / f"{map_id}.pr.json").read_text())
    data = json.loads((WORK / f"{map_id}.input.json").read_text())
    stats = {f["path"]: (f["additions"], f["deletions"]) for f in pr["files"]}
    read = source_at(pr["headRefOid"])
    rows = diff_rows((WORK / f"{map_id}.diff").read_text())
    searches = json.loads((WORK / f"{map_id}.searches.json").read_text())
    together = json.loads((WORK / f"{map_id}.cochange.json").read_text())
    problems = problems_in(data, stats, read, rows, searches, together, pr["issues"])
    if problems:
        sys.exit("Map rejected:\n" + "\n".join(f"  {p}" for p in problems))
    for c in data["cards"]:
        c["add"] = sum(stats[p][0] for p in c["paths"])
        c["del"] = sum(stats[p][1] for p in c["paths"])
        c["fingerprint"] = fingerprint(c, rows)
        for change in c["changes"]:
            change["snippets"] = [key_lines(c, code, rows) for code in change.get("snippets", [])]
        if c.get("kind") in REACH_KINDS:
            c["checked"] = len({p for entry in c.get("reaches", []) + c.get("unaffected", []) for p in entry["paths"]})
    for i, e in enumerate(data["edges"]):
        e["id"] = f"e{i + 1}"
        e["connection_lines"] = connection_lines(read, e.pop("connection_at"))
        del e["connection_code"]
    output = {
        "pr": {
            "number": pr["number"], "title": pr["title"], "files": len(stats),
            "additions": pr["additions"], "deletions": pr["deletions"],
            "url": pr["url"],
            "blob": f"{pr['url'].split('/pull/')[0]}/blob/{pr['headRefOid']}/",
            "diffs": {p: hashlib.sha256(p.encode()).hexdigest() for p in stats},
            "issues": [
                *({"label": f"#{i['number']}", "title": i["title"], "url": i["url"]} for i in pr["issues"]),
                *({"label": t["key"], "title": t["title"], "url": t["url"]} for t in data.get("tickets", [])),
            ],
            "background": data["background"], "problem": data["problem"], "solution": data["solution"],
        },
        "cards": data["cards"],
        "edges": data["edges"],
        "intents": data["intents"],
    }
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f"{map_id}.json").write_text(json.dumps(output, indent=2))
    shutil.copy(VIEWER, HOME / "index.html")
    serve()
    print(f"{len(data['cards'])} cards, {len(data['intents'])} intents, {len(data['edges'])} arrows")
    print(f"http://127.0.0.1:{PORT}/?map={map_id}")


def export(map_id, target=None):
    """Writes the viewer with the published map inside it, so the file opens from disk with no server or install."""
    source = DATA / f"{map_id}.json"
    if not source.exists():
        sys.exit(f"no published map {map_id}: run publish first")
    viewer = VIEWER.read_text()
    if MAP_SLOT not in viewer:
        sys.exit(f"{VIEWER} has no map slot to fill")
    # every < escaped, so code in the map can never close or reopen the script tag that carries it
    carried = json.dumps(json.loads(source.read_text()), separators=(",", ":")).replace("<", "\\u003c")
    filled = f'<script type="application/json" id="map-data" data-map="{map_id}">{carried}</script>'
    path = Path(target).expanduser() if target else Path.cwd() / f"{map_id}.html"
    path.write_text(viewer.replace(MAP_SLOT, filled, 1))
    print(f"{path} ({path.stat().st_size // 1024} KB)")


def cold_read_models():
    """Merges the config file over the defaults, entry by entry, so a file may change only the effort."""
    models = {agent: dict(entry) for agent, entry in COLD_READ.items()}
    if not CONFIG.exists():
        return models, {}
    try:
        config = json.loads(CONFIG.read_text())
    except json.JSONDecodeError as error:
        sys.exit(f"{CONFIG} is not valid JSON: {error}")
    chosen = config.get("cold_read", {}) if isinstance(config, dict) else None
    if not isinstance(chosen, dict):
        sys.exit(f"{CONFIG}: cold_read must map an agent to its settings")
    for agent, entry in chosen.items():
        if not isinstance(entry, dict):
            sys.exit(f"{CONFIG}: cold_read.{agent} must be an object with {' and/or '.join(SETTINGS)}")
        if unknown := sorted(set(entry) - set(SETTINGS)):
            sys.exit(f"{CONFIG}: cold_read.{agent} has unknown settings {', '.join(unknown)}; use {' and/or '.join(SETTINGS)}")
        if not all(isinstance(v, str) for v in entry.values()):
            sys.exit(f"{CONFIG}: cold_read.{agent} takes text values only")
        models.setdefault(agent, {}).update(entry)
    return models, chosen


def set_config(agent, model, effort=None):
    """Replaces one agent's entry and keeps the rest of the file."""
    cold_read_models()  # refuses to rewrite a file it cannot read
    config = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    entry = {"model": "" if model == "own" else model}  # empty, since a missing model keeps the default
    if effort:
        entry["effort"] = effort
    config.setdefault("cold_read", {})[agent] = entry
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(config, indent=2) + "\n")
    show_config()


def show_config():
    models, chosen = cold_read_models()
    print(f"config file: {CONFIG}" + ("" if CONFIG.exists() else " (not created, so the defaults apply)"))
    print("cold read model, by agent (default covers any other agent):")
    for agent, entry in models.items():
        model = f"model {entry['model']}" if entry.get("model") else "the agent's own model"
        setting = model + (f", effort {entry['effort']}" if entry.get("effort") else "")
        print(f"  {agent}: {setting}" + (" (from the config file)" if agent in chosen else ""))


def main():
    command, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if command == "fetch" and len(args) <= 1:
        fetch(args)
    elif command == "search" and len(args) in (2, 3) and args[1:-1] in ([], ["--substring"], ["--regex"], ["--paths"]):
        search(args[0], args[-1], args[1].removeprefix("--") if len(args) == 3 else "word")
    elif command == "publish" and len(args) == 1:
        publish(args[0])
    elif command == "export" and len(args) in (1, 2):
        export(*args)
    elif command == "card" and len(args) == 2:
        card_text(*args)
    elif command == "serve" and not args:
        run_server()
    elif command == "config" and not args:
        show_config()
    elif command == "config" and args[:1] == ["set"] and len(args) in (3, 4) and all(a.strip() for a in args):
        set_config(*args[1:])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
