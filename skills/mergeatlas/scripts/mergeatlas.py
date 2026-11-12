#!/usr/bin/env python3
"""Mechanical half of the mergeatlas skill.

  mergeatlas.py fetch [link...] [--stack] [--fresh]
                                 Fetch PRs into the work directory. A link is a PR link, a PR number or a
                                 stack link; none means the current branch's PR. A stack link maps the whole
                                 stack, a PR link maps that PR, and --stack maps the whole stack a PR sits in.
  mergeatlas.py search <map-id> [--substring | --regex | --paths] <term>
                                 Search the PR's head commit outside its changed files and log the result.
                                 Matches whole words unless --substring or --regex.
  mergeatlas.py publish <map-id> Validate <map-id>.input.json, write the map as a draft, serve it.
  mergeatlas.py finish <map-id>  Say the map's cold read is done, so the viewer stops showing it as a draft.
  mergeatlas.py publish-stack <stack-id>
                                 Validate the stack story in <stack-id>.input.json, write the stack page, serve it.
  mergeatlas.py export <map-id> [path]
                                 Write the published map as one HTML file that opens in any browser, for sharing.
  mergeatlas.py card <map-id | stack-id> <card-id | story>
                                 Print one card as a cold reader sees it, for a cold read done by hand.
  mergeatlas.py readers <map-id | stack-id>
                                 Write each card no cold reader has passed to a file with the reader's instructions.
  mergeatlas.py passed <map-id | stack-id> <card-id | story>...
                                 Record the cards a cold reader found nothing in, so they are not read again.
  mergeatlas.py claims <map-id> [--all]
                                 Write each code link not yet checked to a file with its lines and a checker's instructions.
  mergeatlas.py checked <map-id> <name>[:<n>,<n>...]...
                                 Record the links a checker found to hold; the numbers after a name are the ones that did not.
  mergeatlas.py serve            Run the viewer server; publish starts it when needed.
  mergeatlas.py config           Print the config file's path and the model each agent gives its cold readers.
  mergeatlas.py config set <agent> <model | own> [effort]
                                 Save the cold readers' model for an agent; own means the agent's own model.
  mergeatlas.py report <map-id>  Sum up how a map's run went, in numbers alone, to paste into a bug report.
  mergeatlas.py version          Print the version.
"""
import difflib
import hashlib
import io
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from functools import lru_cache, partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

# The release this file belongs to. .claude-plugin/plugin.json and CHANGELOG.md name the same one, and a test holds them to it.
VERSION = "0.4.0"
OLDEST_PYTHON = (3, 9)

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
# An id is a slug: the story links to it, and the viewer writes it into the page as it is.
SLUG = re.compile(r"[\w-]+")
# The files the viewer's server hands out: the viewer itself and the published maps.
SERVED = re.compile(r"/(index\.html)?|/data/[\w.-]+\.json")
MAP_ID = re.compile(r"[\w.-]+")
PR_URL = re.compile(r"https://([^/]+)/([^/]+)/([^/]+)/pull/(\d+)")
# How long the server trusts what GitHub last said about a PR before asking again.
PR_NOW_SECONDS = 60
CARD_LINK = re.compile(r"\[[^\]]+\]\(([\w-]+)\)")
LOCATION = r"([^)#\s]+)#L(\d+)(?:-L(\d+))?"
CLAIM = re.compile(r"\[([^\]]+)\]\(" + LOCATION + r"\)")
CLAIM_CONTEXT = 6
CODE_LINK = re.compile(r"\[[^\]]+\]\(" + LOCATION + r"\)")
SHIFTABLE = re.compile(r"(\[[^\]]+\]\()" + LOCATION + r"\)")
STACK_LINK = re.compile(r"\[[^\]]+\]\(#(\d+)\)")
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

    def files(self, repo, number):
        return [f["filename"] for f in self._api(f"repos/{repo}/pulls/{number}/files?per_page=100")]


def stack_context(plan, number):
    """The stack around one mapped PR: the whole stack, where the PR sits in it, and its neighbours."""
    stack = plan["stack"]
    if stack is None:
        return None
    prs, at = stack["prs"], stack["prs"].index(number)
    return {**stack, "position": at + 1, "below": prs[at - 1] if at else None, "above": prs[at + 1] if at + 1 < len(prs) else None}


def map_id_of(repo, number):
    return f"{repo.replace('/', '-')}-{number}"


def stack_id(repo, stack):
    """A native stack is named by its number, a stack of branches by its bottom and top PRs."""
    name = stack["number"] if stack["number"] else f"{stack['prs'][0]}-{stack['prs'][-1]}"
    return f"{repo.replace('/', '-')}-stack-{name}"


def stack_record(plan, github):
    """Everything the maps of one stack share: its PRs bottom to top, each with its map id and changed files."""
    stack, repo = plan["stack"], plan["repo"]
    prs = []
    for number in stack["prs"]:
        p = github.pull(repo, number)
        prs.append({"number": number, "title": p["title"], "url": p["url"], "state": p["state"],
                    "map_id": map_id_of(repo, number), "files": github.files(repo, number)})
    return {"id": stack_id(repo, stack), "repo": repo, "number": stack["number"], "base": stack["base"],
            "source": stack["source"], "url": f"https://github.com/{repo}/stack/{stack['number']}" if stack["number"] else None,
            "prs": prs}


def stack_labels(record, number):
    """Labels each file another PR of the stack changes, and this one leaves alone, with where those PRs sit."""
    numbers = [p["number"] for p in record["prs"]]
    at, own = numbers.index(number), set(record["prs"][numbers.index(number)]["files"])
    places = {}
    for i, p in enumerate(record["prs"]):
        for path in p["files"]:
            if i != at and path not in own:
                places.setdefault(path, []).append(f"#{p['number']} {'below' if i < at else 'above'}")
    return {path: label_of(found) for path, found in places.items()}


def label_of(places):
    """Joins "#1 below", "#4 below", "#7 above" into "changed in #1, #4 below, #7 above"."""
    groups = []
    for place in places:
        number, side = place.split()
        if groups and groups[-1][1] == side:
            groups[-1][0].append(number)
        else:
            groups.append(([number], side))
    return "changed in " + ", ".join(f"{', '.join(ns)} {side}" for ns, side in groups)


def stack_strip(record, number, published):
    """What a map shows of its stack: every PR, which is this one, and which have a published map to open."""
    return {
        "id": record["id"], "number": record["number"], "url": record["url"], "page": record["id"] in published,
        "prs": [{"number": p["number"], "title": p["title"], "url": p["url"], "state": p["state"], "map_id": p["map_id"],
                 "current": p["number"] == number, "published": p["map_id"] in published} for p in record["prs"]],
    }


def card_texts(card):
    """Every piece of prose on a card, where its code links sit."""
    yield card.get("summary", "")
    yield from card.get("bullets", [])
    for change in card.get("changes", []):
        yield from (change.get(k, "") for k in CHANGE_TEXT)
    yield from (r.get("effect", "") for r in card.get("reaches", []))
    yield from (u.get("reason", "") for u in card.get("unaffected", []))


def stubs_for(data, record, number, maps):
    """The "From #N" stubs: each file a card links to or reaches that this PR leaves alone and a PR below it changed, pointing at
    the nearest such PR, and at its map's card for that file when that map is published."""
    if record is None:
        return []
    numbers = [p["number"] for p in record["prs"]]
    below, own = record["prs"][:numbers.index(number)], set(record["prs"][numbers.index(number)]["files"])
    stubs = {}
    for c in data["cards"]:
        reached = [path for entry in c.get("reaches", []) for path in entry.get("paths", [])]
        for path in [*(m[0] for m in CODE_LINK.findall(" ".join(card_texts(c)))), *reached]:
            source = next((p for p in reversed(below) if path in p["files"]), None)
            if path in own or source is None:
                continue
            stub = stubs.setdefault(path, {
                "id": f"from:{path}", "path": path, "pr": source["number"], "map_id": source["map_id"],
                "title": source["title"],
                "card_id": next((pc["id"] for pc in maps.get(source["map_id"], {}).get("cards", []) if path in pc["paths"]), None),
                "cited_by": [],
            })
            if c["id"] not in stub["cited_by"]:
                stub["cited_by"].append(c["id"])
    return list(stubs.values())


def stack_problems(data, record):
    """A stack story tells the whole change once: every part present, and the solution an index of the stack's PRs."""
    found, numbers = [], [p["number"] for p in record["prs"]]
    for part in ("background", "problem", "solution"):
        if not str(data.get(part) or "").strip():
            found.append(f"stack story: needs {part}")
    linked = {int(n) for n in STACK_LINK.findall(str(data.get("solution") or ""))}
    missing = [f"#{n}" for n in numbers if n not in linked]
    if missing:
        found.append(f"solution: link every PR as [words](#N); missing {', '.join(missing)}")
    strangers = sorted(linked - set(numbers))
    if strangers:
        found.append(f"solution: {', '.join(f'#{n}' for n in strangers)} not in this stack")
    refs = {f"#{n}" for n in numbers}
    for part in ("background", "problem", "solution"):
        found += open_whys(part, str(data.get(part) or ""), refs)
    return found


def stack_page(data, record, maps):
    """The published stack page: the story once, then each PR with the intents its published map found."""
    return {
        "kind": "stack",
        "stack": {k: record[k] for k in ("id", "repo", "number", "base", "url")},
        **{k: data[k] for k in ("background", "problem", "solution")},
        "prs": [{"number": p["number"], "title": p["title"], "url": p["url"], "state": p["state"], "map_id": p["map_id"],
                 "published": p["map_id"] in maps,
                 "intents": [g["title"] for g in maps.get(p["map_id"], {}).get("intents", []) if not g.get("mechanical")],
                 "files": len(p["files"])} for p in record["prs"]],
    }


def fetch(args):
    fresh = "--fresh" in args
    targets, whole_stack = parse_fetch_args([a for a in args if a != "--fresh"])
    github = GhGitHub()
    if not targets:
        try:
            targets = [("pr", None, int(gh("pr", "view", "--json", "number", "--jq", ".number")))]
        except subprocess.CalledProcessError:
            sys.exit("No pull request for the current branch: give a PR or stack link.")
    try:
        plan = resolve(targets, github, whole_stack=whole_stack)
    except (ValueError, LookupError) as problem:
        sys.exit(str(problem))
    here = github.current_repo()
    if here.lower() != plan["repo"].lower():
        sys.exit(f"Run fetch from inside a clone of {plan['repo']}; this is {here}.")
    stack, record = plan["stack"], None
    if stack:
        record = stack_record(plan, github)
        WORK.mkdir(parents=True, exist_ok=True)
        (WORK / f"{record['id']}.stack.json").write_text(json.dumps(record, indent=2))
        name = f"stack #{stack['number']}" if stack["number"] else "a stack of branches"
        print(f"stack:       {name} on {stack['base']}, bottom to top: {' '.join(f'#{n}' for n in stack['prs'])}")
        print(f"stack id:    {record['id']}")
        print(f"mapping:     {' '.join(f'#{n}' for n in plan['map'])}")
        if plan["added"]:
            print(f"added:       {' '.join(f'#{n}' for n in plan['added'])}, not given but between the PRs given")
    for number in plan["map"]:
        print()
        context = stack_context(plan, number)
        fetch_pr(plan["repo"], number, context and {**context, "id": record["id"]}, fresh)
    if record:
        refresh_stack(record)


def has_commit(sha):
    return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True).returncode == 0


def ensure_commit(sha):
    """Fetches a commit the clone lacks, such as a PR's old head after a force push; GitHub keeps them reachable."""
    if sha and not has_commit(sha):
        subprocess.run(["git", "fetch", "origin", sha], capture_output=True)


def is_ancestor(older, newer):
    return subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], capture_output=True).returncode == 0


def local_diff(built, head):
    """The PR's own changes from the commit it was built on, with their file list, when GitHub's diff would also show a
    squash-merged parent's changes."""
    diff = subprocess.run(["git", "diff", "-M", built, head], capture_output=True, text=True, check=True).stdout
    files = []
    for line in subprocess.run(["git", "diff", "--numstat", "-M", built, head], capture_output=True, text=True,
                               check=True).stdout.splitlines():
        added, deleted, path = line.split("\t", 2)
        files.append({"path": path, "additions": int(added) if added != "-" else 0,
                      "deletions": int(deleted) if deleted != "-" else 0})
    return text_only(diff), files


def fetch_pr(repo, number, stack, fresh=False):
    fields = "number,title,body,additions,deletions,files,headRefName,headRefOid,baseRefName,baseRefOid,url,closingIssuesReferences"
    pr = json.loads(gh("pr", "view", str(number), "--repo", repo, "--json", fields))
    pr["stack"] = stack
    map_id = map_id_of(repo, pr["number"])
    pr["issues"] = [
        json.loads(gh("issue", "view", str(i["number"]), "--repo", repo, "--json", "number,title,body,url"))
        for i in pr.pop("closingIssuesReferences")
    ]
    subprocess.run(["git", "fetch", "origin", f"pull/{pr['number']}/head"], check=True, capture_output=True)
    head, base = pr["headRefOid"], pr.pop("baseRefOid")
    ensure_commit(base)
    merge_base = subprocess.run(["git", "merge-base", head, base], capture_output=True, text=True).stdout.strip() or base
    old_path = WORK / f"{map_id}.pr.json"
    old = json.loads(old_path.read_text()) if old_path.exists() else {}
    for sha in (old.get("pinned"), old.get("headRefOid")):
        ensure_commit(sha)
    built = built_on(merge_base, old.get("pinned"), head, is_ancestor)
    if built == merge_base:
        diff = text_only(gh("pr", "diff", str(pr["number"]), "--repo", repo))
    else:
        diff, pr["files"] = local_diff(built, head)
        pr["additions"], pr["deletions"] = sum(f["additions"] for f in pr["files"]), sum(f["deletions"] for f in pr["files"])
    status, plan = refresh_work(map_id, pr, diff, built, fresh)
    sent = {"back": plan["back"], "total": plan["total"]} if status == "partial" else {}
    note(map_id, "fetch", status=status, files=len(pr["files"]), additions=pr["additions"], deletions=pr["deletions"],
         diff_lines=len(diff.splitlines()), **sent)
    url = f"http://127.0.0.1:{PORT}/?map={map_id}"
    if status == "same-head":
        shutil.copy(VIEWER, HOME / "index.html")
        serve()
        if is_draft(map_id):
            print(f"map id:      {map_id}\nmap:         published as a draft whose cold read did not finish (head {head[:7]}): {url}")
            print(f"work dir:    {WORK}")
        else:
            print(f"map id:      {map_id}\nmap:         unchanged since it was published (head {head[:7]}): {url}")
        return
    if status == "refreshed":
        print(f"map id:      {map_id}\nmap:         refreshed by the script: the same changes on head {head[:7]}; links into "
              f"its files moved with their lines, links outside stay at {pr['pinned'][:7]}: {url}")
        return
    diff_path, cochange_path = WORK / f"{map_id}.diff", WORK / f"{map_id}.cochange.json"
    together = json.loads(cochange_path.read_text())
    print(f"map id:      {map_id}")
    for line in plan_lines(map_id, plan):
        print(line)
    if stack:
        neighbours = [f"below it #{stack['below']}" if stack["below"] else "at the bottom",
                      f"above it #{stack['above']}" if stack["above"] else "at the top"]
        print(f"in stack:    {stack['position']} of {len(stack['prs'])}, {', '.join(neighbours)}")
    print(f"work dir:    {WORK}")
    print(f"head commit: {pr['headRefOid']}")
    print(f"built on:    {pr['pinned']}, where files outside the PR are read and linked")
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


def plan_lines(map_id, plan):
    """Tells the agent what to do with each part of a map whose PR changed, and leaves out a part there is nothing to say of."""
    if not plan:
        return []
    lines = [f"map:         changed since it was published at {plan['from'][:7]}; keep the rest of {WORK / f'{map_id}.input.json'} as it is"]
    if "delta" in plan:
        what = "the commits added since then" if plan["delta"] == "commits" else "the lines that entered or left the PR's diff since then"
        lines.append(f"  delta:     {WORK / f'{map_id}.delta.diff'} ({plan['delta_lines']} lines, {what})")
    for card in plan["redo"]:
        phrases = []
        if card["whole"]:
            phrases.append("write again")
        else:
            if card["changes"]:
                phrases.append(f"write again changes {', '.join(map(str, card['changes']))}")
            if card["linked"]:
                phrases.append(f"check the links in changes {', '.join(map(str, card['linked']))}")
            if card["links"]:
                phrases.append("check the links outside its changes")
            if card["entered"] or card["left"]:
                phrases += ["check the rest of the card against the delta", f"{card['entered']} lines entered and {card['left']} left its diff"]
        lines.append(f"  card {card['id']}: {'; '.join(phrases)}")
    for what, items in [("keep the cards", plan["keep"]), ("add cards for the new files", plan["added"]),
                        ("drop the files no longer in the PR", plan["gone"]), ("check the links in", plan["fix"]),
                        ("check against the delta", plan["recheck"])]:
        if items:
            lines.append(f"  {what}: {', '.join(items)}")
    for found in plan.get("searches", []):
        halves = [f"now also matches {', '.join(found['now'])}" if found["now"] else "",
                  f"no longer matches {', '.join(found['gone'])}" if found["gone"] else ""]
        lines.append(f"  search {found['term']!r} ({found['mode']}): {'; '.join(h for h in halves if h)}")
    if plan.get("words"):
        lines.append("  the PR's title, description or issues changed: check the story against them")
    if plan.get("problems"):
        lines += ["  publish rejected the refreshed map:", plan["problems"]]
    if plan["back"] * 2 > plan["total"]:
        lines.append("  map it afresh: more than half of the map's changes go back")
    return lines


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


def matching(term, mode, commit, changed):
    """Maps each unchanged file that holds the term, or whose path does, to its matching lines."""
    if mode == "paths":
        matches = {path: [] for path in files_at(commit) if term in path}
    else:
        matches = matches_of(term, mode, commit)
    return {path: lines for path, lines in sorted(matches.items()) if path not in changed}


def found_by(term, mode, commit, changed):
    """Lists the files outside the PR that a search finds at a commit, as the search log keeps them."""
    return sorted(matching(term, mode, commit, changed))


def search(map_id, term, mode):
    pr = json.loads((WORK / f"{map_id}.pr.json").read_text())
    commit, changed = pr["headRefOid"], {f["path"] for f in pr["files"]}
    matches = matching(term, mode, commit, changed)
    log_path = WORK / f"{map_id}.searches.json"
    log = [s for s in json.loads(log_path.read_text()) if (s["term"], s["mode"]) != (term, mode)]
    log.append({"term": term, "mode": mode, "files": list(matches)})
    log_path.write_text(json.dumps(log, indent=2))
    note(map_id, "search", mode=mode, files=len(matches))
    record = stack_of_map(pr)
    labels = stack_labels(record, pr["number"]) if record else {}
    named = lambda path: f"{path}  ({labels[path]})" if path in labels else path
    print(f"{len(matches)} unchanged files match {term!r}")
    for path, lines in list(matches.items())[:SHOWN_FILES]:
        print(named(path))
        for line in lines[:SHOWN_MATCHES]:
            print(f"  {line}")
        if len(lines) > SHOWN_MATCHES:
            print(f"  ... {len(lines) - SHOWN_MATCHES} more")
    rest = list(matches)[SHOWN_FILES:]
    if rest:
        print(f"... {len(rest)} more files, every one of which needs sorting:")
        for path in rest:
            print(named(path))


def source_at(commit):
    """Returns a reader for a file's lines at commit, None when it is not there."""
    @lru_cache(maxsize=None)
    def read(path):
        shown = subprocess.run(["git", "show", f"{commit}:{path}"], capture_output=True, text=True, errors="replace")
        return shown.stdout.splitlines() if shown.returncode == 0 else None
    return read


def reader_of(pr):
    """Returns a reader for the lines a map's links cite: a pull request's own files at its head, every other file at the commit the map was built on."""
    changed = {f["path"] for f in pr["files"]}
    head_read, pinned_read = source_at(pr["headRefOid"]), source_at(pr.get("pinned") or pr["headRefOid"])
    return lambda path: head_read(path) if path in changed else pinned_read(path)


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


def changed_lines(rows, path):
    return [line for line, *_ in rows.get(path, []) if line.startswith(("+", "-"))]


def fingerprint(card, rows):
    """Identifies a card's changes by their added and removed lines alone, so a rebase that only moves them or changes
    the lines around them keeps the value, and the reviewer's marks with it."""
    text = "\n".join(line for path in card["paths"] for line in changed_lines(rows, path))
    return hashlib.sha256(text.encode()).hexdigest()


def patch_id(rows):
    """Identifies a PR's changes as git patch-id does: every file's added and removed lines, with no line numbers."""
    text = "\n".join(f"{path}\n" + "\n".join(changed_lines(rows, path)) for path in sorted(rows))
    return hashlib.sha256(text.encode()).hexdigest()


def line_map(old, new):
    """Maps each line number both versions of a file keep to its number in the new one."""
    found = {}
    for tag, i1, i2, j1, _ in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            found.update({i1 + k + 1: j1 + k + 1 for k in range(i2 - i1)})
    return found


def shift_links(data, maps):
    """Moves every code link and connection into a mapped file to where its lines are now. A link whose lines are gone,
    or no longer sit together, stays as it was and its owner is reported, so the agent checks that part. A card's
    changes are owners of their own, apart from the rest of the card."""
    broken = []

    def moved(path, first, last):
        first, last = int(first), int(last or first)
        lines = maps[path]
        new_first, new_last = lines.get(first), lines.get(last)
        if new_first is None or new_last is None or new_last - new_first != last - first:
            return None
        return f"{path}#L{new_first}" + (f"-L{new_last}" if new_last != new_first else "")

    def walk(item, owner, key=None):
        if isinstance(item, dict):
            return {k: walk(v, owner, k) for k, v in item.items()}
        if isinstance(item, list):
            return [walk(v, owner) for v in item]
        if not isinstance(item, str):
            return item
        def shift(path, first, last, unchanged):
            if path not in maps:
                return unchanged
            at = moved(path, first, last)
            if at is None:
                broken.append(owner)
            return at or unchanged
        at = re.fullmatch(LOCATION, item) if key == "connection_at" else None
        if at:
            return shift(*at.groups(), item)
        return SHIFTABLE.sub(lambda m: f"{m[1]}{shift(m[2], m[3], m[4], m[0][len(m[1]):-1])})", item)

    def walk_card(card):
        owner = f"card {card.get('id')}"
        return {k: [walk(change, f"{owner} change {n}") for n, change in enumerate(v, 1)] if k == "changes" and isinstance(v, list)
                else walk(v, owner, k) for k, v in card.items()}

    shifted = {}
    for key, value in data.items():
        if key == "cards":
            shifted[key] = [walk_card(c) for c in value]
        elif key == "edges":
            shifted[key] = [walk(e, f"arrow {e.get('from')} -> {e.get('to')}") for e in value]
        elif key == "intents":
            shifted[key] = [walk(g, f"intent {g.get('id')}") for g in value]
        else:
            shifted[key] = walk(value, "story", key)
    return shifted, list(dict.fromkeys(broken))


def built_on(merge_base, pinned, head, is_ancestor):
    """The commit a PR's own changes start from. That is its merge base, except when a parent was squash-merged and the
    child not rebased: the child still holds the parent's old head, the commit its last map was built on, while its
    merge base with the default branch falls back to before the parent's changes."""
    if pinned and pinned != merge_base and is_ancestor(pinned, head) and is_ancestor(merge_base, pinned):
        return pinned
    return merge_base


def redo_plan(data, old_rows, new_rows, old_paths, new_paths, broken):
    """Splits a map into the cards and changes whose words the agent writes again and those it keeps, and lists the story,
    intents and arrows to check beside them. A change goes back when its key lines left the diff. One that only links to
    a line that changed may still be true, so its links are checked and its words stay."""
    redo, keep, back, total, intents = [], [], 0, 0, set()
    for c in data["cards"]:
        changes = c.get("changes", [])
        whole = any(p not in new_paths for p in c["paths"])
        gone = [n for n, change in enumerate(changes, 1) if any(key_lines(c, code, new_rows) is None for code in change.get("snippets", []))]
        linked = [n for n in range(1, len(changes) + 1) if n not in gone and f"card {c['id']} change {n}" in broken]
        moved = [lines_moved(changed_lines(old_rows, p), changed_lines(new_rows, p)) for p in c["paths"]]
        entered, left = sum(len(m[0]) for m in moved), sum(len(m[1]) for m in moved)
        links = f"card {c['id']}" in broken
        total += len(changes)
        if whole or gone or linked or links or entered or left:
            redo.append({"id": c["id"], "whole": whole, "changes": gone, "linked": [] if whole else linked, "links": links,
                         "entered": entered, "left": left})
            sent = range(1, len(changes) + 1) if whole else gone
            back += len(sent)
            intents.update(changes[n - 1].get("intent") for n in (sent if whole else gone + linked))
        else:
            keep.append(c["id"])
    touched = {r["id"] for r in redo}
    added, dropped = [p for p in new_paths if p not in old_paths], [p for p in old_paths if p not in new_paths]
    fix = [o for o in broken if not o.startswith("card ")]
    recheck = ["story"] if redo or added or dropped else []
    recheck += [f"intent {g.get('id')}" for g in data.get("intents", []) if g.get("id") in intents]
    recheck += [f"arrow {e.get('from')} -> {e.get('to')}" for e in data.get("edges", []) if {e.get("from"), e.get("to")} & touched]
    return {
        "redo": redo, "keep": keep, "added": added, "gone": dropped, "fix": fix,
        "recheck": [o for o in recheck if o not in fix], "back": back, "total": total,
    }


def lines_moved(old, new):
    """Tells which of a file's changed lines entered the diff and which left it, as indexes into the new and the old list."""
    entered, left = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag != "equal":
            left.extend(range(i1, i2))
            entered.extend(range(j1, j2))
    return entered, left


def delta_of(old, pr, old_rows, new_rows, old_pinned, built):
    """Writes up what changed in a PR since its last map, as the commits added on top, or else the lines that entered or left its diff."""
    if is_ancestor(old["headRefOid"], pr["headRefOid"]) and old_pinned == built:
        shown = subprocess.run(["git", "diff", "-M", old["headRefOid"], pr["headRefOid"]], capture_output=True, text=True, check=True)
        return text_only(shown.stdout), "commits"
    changed = lambda rows, path: [row for row in rows.get(path, []) if row[0].startswith(("+", "-"))]
    files = []
    for path in sorted(set(old_rows) | set(new_rows)):
        before, after = changed(old_rows, path), changed(new_rows, path)
        entered, left = lines_moved([row[0] for row in before], [row[0] for row in after])
        if not entered and not left:
            continue
        lines = [f"== {path}"]
        if entered:
            lines += ["entered the PR's diff:", *(f"{after[i][1]}\t{after[i][0]}" for i in entered)]
        if left:
            lines += ["left the PR's diff:", *(before[i][0] for i in left)]
        files.append("\n".join(lines))
    return "\n\n".join(files) + "\n" if files else "", "lines"


def cited_paths(data):
    """Every file a map links to, in its prose or in an arrow's connection."""
    found = {m[2] for m in SHIFTABLE.finditer(json.dumps(data))}
    return found | {at[1] for e in data.get("edges", []) if (at := re.fullmatch(LOCATION, e.get("connection_at", "")))}


def mark_update(map_id, old, plan):
    """Notes the head a changed map was updated from, the cards its new changes touch and the words of every card then,
    so publish can say which cards changed with the pull request."""
    data = json.loads((WORK / f"{map_id}.input.json").read_text())
    noted = {"from": old["headRefOid"], "touched": [card["id"] for card in plan["redo"]], "hashes": hashes_of(data)}
    (WORK / f"{map_id}.update.json").write_text(json.dumps(noted, indent=2))
    seen = {"rounds": 0, "seen": {name: sentences_in(data, name) for name in noted["hashes"]}}
    (WORK / f"{map_id}.seen.json").write_text(json.dumps(seen, indent=2))


def keep_read_marks(map_id):
    """Counts a map finished before it had read marks as read, at its words as they stand."""
    if is_draft(map_id):
        return
    data = json.loads((WORK / f"{map_id}.input.json").read_text())
    if not (WORK / f"{map_id}.read.json").exists():
        (WORK / f"{map_id}.read.json").write_text(json.dumps(hashes_of(data), indent=2))
    if not (WORK / f"{map_id}.checked.json").exists():
        write_checked(map_id, data)


def outdated(data):
    """Tells whether a map is in a format from before cards held changes, which cannot be reused card by card."""
    return any("changes" not in card for card in data.get("cards", []))


def refresh_work(map_id, pr, diff, built, fresh=False):
    """Brings the work directory up to a fetched PR. A PR mapped before keeps its map when it can: the same head commit
    changes nothing; the same changes on a new commit get their links shifted and are published again by the script;
    otherwise the links are shifted where they still hold and the plan says which cards the agent writes again. A map
    asked to start over, or in a format too old to reuse, is set aside and the PR mapped as if for the first time."""
    work = {k: WORK / f"{map_id}.{k}" for k in ("pr.json", "input.json", "diff", "searches.json", "cochange.json", "delta.diff")}
    WORK.mkdir(parents=True, exist_ok=True)
    known = all(work[k].exists() for k in ("pr.json", "input.json", "diff")) and (DATA / f"{map_id}.json").exists()
    if known and (fresh or outdated(json.loads(work["input.json"].read_text()))):
        for k in ("input.json", "read.json", "checked.json", "seen.json", "update.json", "delta.diff"):
            (WORK / f"{map_id}.{k}").unlink(missing_ok=True)
        known = False
    old = json.loads(work["pr.json"].read_text()) if known else None
    paths = [f["path"] for f in pr["files"]]
    if old is None:
        pr["pinned"] = built
        work["diff"].write_text(diff)
        work["cochange.json"].write_text(json.dumps(co_changes(set(paths), pr["headRefOid"]), indent=2))
        work["searches.json"].write_text("[]")
        work["pr.json"].write_text(json.dumps(pr))
        return "new", None
    if old["headRefOid"] == pr["headRefOid"]:
        old["stack"] = pr["stack"]
        # a map from before links were pinned takes the commit it was built on once, which the same head leaves unchanged
        unpinned = "pinned" not in old
        old.setdefault("pinned", built)
        old.setdefault("baseRefName", pr.get("baseRefName"))
        work["pr.json"].write_text(json.dumps(old))
        if unpinned:
            publish(map_id, asked=False)
        return "same-head", None
    old_rows, new_rows = diff_rows(work["diff"].read_text()), diff_rows(diff)
    old_paths = [f["path"] for f in old["files"]]
    same = patch_id(old_rows) == patch_id(new_rows) and sorted(old_paths) == sorted(paths)
    old_pinned = old.get("pinned") or old["headRefOid"]
    pr["pinned"] = old_pinned if same else built
    old_head, old_pin = source_at(old["headRefOid"]), source_at(old_pinned)
    new_head, new_pin = source_at(pr["headRefOid"]), source_at(pr["pinned"])
    data, maps = json.loads(work["input.json"].read_text()), {}
    for path in sorted(cited_paths(data)):
        before = (old_head if path in old_paths else old_pin)(path)
        after = (new_head if path in paths else new_pin)(path)
        if before != after:
            maps[path] = line_map(before, after) if before is not None and after is not None else {}
    data, broken = shift_links(data, maps)
    work["input.json"].write_text(json.dumps(data, indent=2))
    work["diff"].write_text(diff)
    work["pr.json"].write_text(json.dumps(pr))
    plan = redo_plan(data, old_rows, new_rows, old_paths, paths, broken)
    plan["from"] = old["headRefOid"]
    if (old["title"], old["body"], [(i["number"], i["title"], i["body"]) for i in old["issues"]]) != \
            (pr["title"], pr["body"], [(i["number"], i["title"], i["body"]) for i in pr["issues"]]):
        plan["words"] = True
    if same and not broken:
        try:
            publish(map_id, asked=False)
            return "refreshed", None
        except SystemExit as rejected:
            plan = {**plan, "redo": [], "keep": [c["id"] for c in data["cards"]], "added": [], "gone": [], "fix": [],
                    "recheck": [], "back": 0, "problems": str(rejected)}
            keep_read_marks(map_id)
            mark_update(map_id, old, plan)
            return "partial", plan
    text, kind = delta_of(old, pr, old_rows, new_rows, old_pinned, built)
    work["delta.diff"].write_text(text)
    plan.update({"delta": kind, "delta_lines": len(text.splitlines())})
    log, plan["searches"] = json.loads(work["searches.json"].read_text()), []
    for entry in log:
        files = found_by(entry["term"], entry["mode"], pr["headRefOid"], set(paths))
        now, gone = sorted(set(files) - set(entry["files"])), sorted(set(entry["files"]) - set(files))
        entry["files"] = files
        if now or gone:
            plan["searches"].append({"term": entry["term"], "mode": entry["mode"], "now": now, "gone": gone})
    work["searches.json"].write_text(json.dumps(log, indent=2))
    work["cochange.json"].write_text(json.dumps(co_changes(set(paths), pr["headRefOid"]), indent=2))
    keep_read_marks(map_id)
    mark_update(map_id, old, plan)
    return "partial", plan


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
        for changes in shown.values():
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
        if not SLUG.fullmatch(str(name)):
            found.append(f"card {name}: an id takes letters, digits, - and _ only")
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
        if not SLUG.fullmatch(str(name)):
            found.append(f"intent {name}: an id takes letters, digits, - and _ only")
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


# What a rejection was for, by the words publish and publish-stack use, so report can count rejections without quoting
# the map. The first match wins, so the rules whose messages quote a sentence of the map come first.
RULES = (
    ("open-why", "a reason ends with no code link"),
    ("leans-on-another-card", ": leans on "),
    ("stack-story", "stack story: needs"),
    ("stack-story", "solution: link every PR"),
    ("stack-story", "not in this stack"),
    ("ticket", "ticket "),
    ("link-to-missing-lines", ": no such lines "),
    ("claim-without-code-link", "has no code link"),
    ("no-key-lines", ": has no key lines"),
    ("snippet-not-in-diff", ": a snippet is not in the diff"),
    ("key-lines-change-nothing", ": its key lines change nothing"),
    ("shared-lines-repeat-a-problem", " share lines, so each states its own problem"),
    ("several-files-on-one-card", " card holds one file"),
    ("unaffected-without-reason", ": an unaffected entry has no reason"),
    ("reach-names-missing-file", ": no such file "),
    ("unknown-kind", ": unknown kind "),
    ("duplicate-id", ": duplicate id"),
    ("id-not-a-slug", ": an id takes letters"),
    ("file-not-in-pr", " is not in this PR"),
    ("file-on-two-cards", " is already in another card"),
    ("file-without-card", "no card holds "),
    ("no-searches", "no searches logged"),
    ("broad-search", "broad search "),
    ("reach-not-sorted", "not accounted for: "),
    ("builds-on-order", ": builds only on an intent listed before it"),
    ("mechanical", "one mechanical intent holds"),
    ("mechanical", "a mechanical change names its reason"),
    ("mechanical", "only a change in the mechanical intent"),
    ("not-whitespace-only", "indentation is logic in"),
    ("not-whitespace-only", " changes more than whitespace"),
    ("change-without-intent", ": no intent "),
    ("intent-without-change", ": no change"),
    ("intent-of-tests-only", ": every change is a test"),
    ("arrow-to-itself", ": points at itself"),
    ("arrow-to-missing-card", ": no card "),
    ("connection-code-not-found", ": not at "),
    ("story-links", "solution links to unknown"),
    ("story-links", "solution has no link to intent"),
    ("missing-part", "missing "),
)


def rule_of(problem):
    return next((rule for rule, words in RULES if words in problem), "other")


def note(map_id, step, **numbers):
    """Adds one step to a map's run record: when it ran and its counts, never code, paths or the map's words. The record
    stays on this machine, and report sums it up."""
    try:
        WORK.mkdir(parents=True, exist_ok=True)
        with (WORK / f"{map_id}.run.jsonl").open("a") as record:
            record.write(json.dumps({"at": round(time.time(), 1), "step": step, "version": VERSION, **numbers}) + "\n")
    except OSError:
        pass  # a record that cannot be written never costs the map


def words_in(data):
    """How much a map asks its reader to read: every piece of prose, counted without its link targets."""
    texts = [data.get(k, "") for k in ("background", "problem", "solution")]
    texts += [t for c in data.get("cards", []) for t in card_texts(c)]
    texts += [e.get(k, "") for e in data.get("edges", []) for k in EDGE_TEXT]
    texts += [g.get("outcome", "") for g in data.get("intents", [])]
    return sum(len(ANY_LINK.sub(r"\1", str(t or "")).split()) for t in texts)


def minutes(seconds):
    return f"{seconds:.0f} s" if seconds < 90 else f"{seconds / 60:.0f} min"


def summary_of(steps):
    """The lines report prints for a map's latest run. A run starts where fetch hands the agent work to do."""
    starts = [i for i, s in enumerate(steps) if s["step"] == "fetch" and s.get("status") in ("new", "partial")]
    run = steps[starts[-1]:] if starts else steps
    of = lambda step: [s for s in run if s["step"] == step]
    lines = [f"run            {len(starts) or 1} of {len(starts) or 1} for this map, MergeAtlas {', '.join(sorted({s['version'] for s in run}))}"]
    for f in of("fetch")[:1]:
        again = "new" if f["status"] == "new" else "changed since its last map"
        sent = f", {f['back']} of {f['total']} changes sent back" if "back" in f else ""
        lines.append(f"pull request   {f['files']} files, +{f['additions']} -{f['deletions']}, {f['diff_lines']} diff lines, {again}{sent}")
    searches = of("search")
    if searches:
        modes = Counter(s["mode"] for s in searches)
        lines.append(f"searches       {len(searches)} ({', '.join(f'{n} {mode}' for mode, n in modes.most_common())}), "
                     f"{sum(s['files'] for s in searches)} files matched")
    publishes = of("publish")
    rejected = Counter()
    for attempt in publishes:
        rejected.update(attempt.get("rejected_for", {}))
    if publishes:
        lines.append(f"publishes      {len(publishes)}, of which {sum(not a['accepted'] for a in publishes)} rejected")
    if rejected:
        lines.append(f"rejected for   {', '.join(f'{rule} {n}' for rule, n in rejected.most_common())}")
    rounds = sum(1 for before, s in zip([None, *run], run) if s["step"] == "card" and (before or {}).get("step") != "card")
    if rounds:
        lines.append(f"cold reads     {len(of('card'))} cards and stories printed, over {rounds} rounds")
    if of("claims"):
        lines.append(f"claim checks   {sum(s['links'] for s in of('claims'))} links checked over {len(of('claims'))} rounds, "
                     f"{sum(s['sent_back'] for s in of('checked'))} sent back")
    accepted = [a for a in publishes if a["accepted"]]
    if accepted:
        last = accepted[-1]
        lines.append(f"map            {last['cards']} cards, {last['intents']} intents, {last['arrows']} arrows, {last['words']} words")
        done = of("finish")
        end = f"{minutes(done[-1]['at'] - run[0]['at'])} to the finished map" if done else \
            f"{minutes(run[-1]['at'] - run[0]['at'])} to the last step, and the cold read was not finished"
        lines.append(f"time           {minutes(accepted[0]['at'] - run[0]['at'])} to the first accepted publish, {end}")
    return lines


def report(map_id):
    """Sums up a map's latest run in numbers alone, so it can go into a bug report as it stands."""
    path = WORK / f"{map_id}.run.jsonl"
    if not path.exists():
        sys.exit(f"no run record for {map_id}: one is kept from the next fetch on")
    steps = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    print(f"MergeAtlas {VERSION}, Python {platform.python_version()}, {platform.system()} {platform.machine()}")
    print("Numbers alone: no code, no paths, no repository name and no words from the map.")
    print("\n".join(summary_of(steps)))


def published(map_id):
    """A published map or stack page, {} when there is none to read."""
    try:
        return json.loads((DATA / f"{map_id}.json").read_text())
    except (OSError, ValueError):
        return {}


def is_draft(map_id):
    return bool(published(map_id).get("pr", {}).get("draft"))


def library():
    """What the viewer's front page lists: every published map and stack page, the latest first."""
    found = []
    for path in DATA.glob("*.json"):
        data = published(path.stem)
        pr, stack = data.get("pr"), data.get("stack")
        if data.get("kind") == "stack" and stack:
            found.append({"id": path.stem, "kind": "stack", "repo": stack["repo"], "number": stack.get("number"),
                          "url": stack.get("url"), "prs": len(data.get("prs", [])), "at": int(path.stat().st_mtime)})
        elif pr:
            link = PR_URL.fullmatch(pr["url"])
            strip = pr.get("stack") or {}
            found.append({
                "id": path.stem, "kind": "map", "repo": f"{link[2]}/{link[3]}" if link else "", "number": pr["number"],
                "title": pr["title"], "url": pr["url"], "files": pr["files"], "additions": pr["additions"],
                "deletions": pr["deletions"], "draft": bool(pr.get("draft")),
                # a map from before maps said when they were made takes the time its file was written
                "at": (pr.get("mapped") or {}).get("at") or int(path.stat().st_mtime),
                "stack": {"id": strip["id"], "number": strip.get("number"), "of": len(strip["prs"]),
                          "part": next((i for i, p in enumerate(strip["prs"], 1) if p.get("current")), None)} if strip else None,
            })
    return sorted(found, key=lambda m: -m["at"])


pr_now_known = {}


def pr_now(map_id):
    """Where a mapped PR stands on GitHub now, beside the commit its map was made at, so the viewer can say when the PR
    has moved on. It asks through gh as fetch does, once a minute per map at most, and answers {} when it cannot tell."""
    pr = published(map_id).get("pr", {}) if MAP_ID.fullmatch(map_id) else {}
    link, mapped = PR_URL.fullmatch(pr.get("url", "")), (pr.get("mapped") or {}).get("head")
    if not (link and mapped):
        return {}
    at, now, head = pr_now_known.get(map_id, (0, {}, None))
    # a map made again describes a later commit, so what was heard for the earlier one no longer answers
    if time.time() - at > PR_NOW_SECONDS or head != mapped:
        host, owner, repo, number = link.groups()
        try:
            asked = subprocess.run(
                ["gh", "api", *(["--hostname", host] if host != "github.com" else []), f"repos/{owner}/{repo}/pulls/{number}",
                 "--jq", "{head: .head.sha, state: (if .merged then \"merged\" else .state end)}"],
                capture_output=True, text=True, timeout=15)
            now = json.loads(asked.stdout) if asked.returncode == 0 else {}
        except (OSError, ValueError, subprocess.SubprocessError):
            now = {}
        pr_now_known[map_id] = (time.time(), now, mapped)
    return {"mapped": mapped, **now} if now.get("head") else {}


class ViewerHandler(SimpleHTTPRequestHandler):
    """Serves the viewer and the published maps to this machine alone. The cache also holds the diffs and PR text of
    private repositories, so nothing else in it is served. A request made under another host name is refused, since
    that is how a web page whose own domain points at 127.0.0.1 would ask for them. Two more answers are worked out
    when asked for: the list of maps for the front page, and where a mapped PR stands on GitHub now."""

    def send_head(self):
        port = self.server.server_address[1]
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self.send_error(403, "MergeAtlas answers on 127.0.0.1 and localhost only")
            return None
        asked = urlsplit(self.path)
        if asked.path in ("/maps.json", "/pr-now.json"):
            # the viewer alone asks for these: a browser says when another site's page is the one asking, and that page
            # could otherwise have this machine call GitHub
            if self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
                self.send_error(403)
                return None
            if asked.path == "/maps.json":
                return self.answer(library())
            return self.answer(pr_now(parse_qs(asked.query).get("map", [""])[0]))
        if not SERVED.fullmatch(asked.path):
            self.send_error(404)
            return None
        return super().send_head()

    def answer(self, found):
        body = json.dumps(found).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return io.BytesIO(body)

    def end_headers(self):
        # no-store keeps browsers from pairing a cached viewer with a newly published map
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # serve reads these two to tell a server from another release, and to stop that one
        self.send_header("X-MergeAtlas-Version", VERSION)
        self.send_header("X-MergeAtlas-Pid", str(os.getpid()))
        super().end_headers()


def plain(text):
    """Keeps a link's words and marks where it points, so a cold reader can tell a linked claim from a bare one."""
    text = CODE_LINK.sub(lambda m: f"{m[0][1:m[0].index('](')]} [→ code]", text or "")
    text = STACK_LINK.sub(lambda m: f"{m[0][1:m[0].index('](')]} [→ PR #{m[1]}]", text)
    return ANY_LINK.sub(r"\1 [→ card]", text)


READER = """You are a skilled engineer who has never seen this project, and the card below the line is all you have. Read no other file and run no command. Find the places where it leaves you unable to follow what the code does:
- a statement whose how or why the card does not give, so you cannot see how it follows;
- a project term or name the card uses without saying what it is;
- a statement that contradicts another statement or the key lines on this card.

Words marked [→ code] link to the source, so accept what they state unless the card contradicts it. Words marked [→ card] link to another card, and words marked [→ PR #N] link to another pull request. Skip what a skilled engineer knows from the language and its common libraries. Do not ask why the change was wanted or designed this way, about alternatives, about whether it was tested or verified, about versions or tooling, or about code the card does not mention. For each one, quote the statement and say which step is missing or which statements disagree. Most important first. If nothing is missing, reply "none".

---"""
REREADER = READER.replace(
    "Find the places where it leaves you unable to follow what the code does:",
    "This card was read before, and the sentences inside ⟦ ⟧ were written or edited since. Find the places where those sentences leave you "
    "unable to follow what the code does, and report nothing about a sentence outside ⟦ ⟧, which is there so you can follow the marked ones:",
).replace('If nothing is missing, reply "none".', 'If the marked sentences leave nothing open, reply "none".')


def words_of(data, name, stack, via):
    """Gives one card as a cold reader sees it, each piece of prose passed through via after its link targets gave way to a mark."""
    words = lambda text: via(plain(text))
    story = lambda: "\n\n".join(words(data.get(k)) for k in ("background", "problem", "solution"))
    if stack:
        if name != "story":
            sys.exit("a stack has only its story to read")
        return story()
    lines = []
    if name == "story":
        lines.append(story())
        for g in data.get("intents", []):
            lines.append(f"\nintent {g['id']}: {g['title']}\noutcome: {words(g['outcome'])}")
            for base in g.get("builds_on", []):
                lines.append(f"builds on {base['intent']}: {words(base['how'])}")
        return "\n".join(lines)
    cards = {c["id"]: c for c in data["cards"]}
    if name not in cards:
        sys.exit(f"no card {name}: choose from story, {', '.join(cards)}")
    c = cards[name]
    lines.append(f"# {', '.join(c['paths'])}")
    lines.append(f"\nsummary: {words(c['summary'])}")
    for number, change in enumerate(c["changes"], 1):
        lines.append(f"\nchange {number}, intent {change['intent']}")
        for field in CHANGE_TEXT:
            lines.append(f"{field}: {words(change[field])}")
        for code in change.get("snippets", []):
            lines.append(f"key lines:\n{code}")
    for r in c.get("reaches", []):
        lines.append(f"\nalso reaches {', '.join(r['paths'])}: {words(r['effect'])}")
    for u in c.get("unaffected", []):
        lines.append(f"\nunaffected {', '.join(u['paths'])}: {words(u['reason'])}")
    for e in data["edges"]:
        if name in (e["from"], e["to"]):
            other = cards[e["to"] if e["from"] == name else e["from"]]
            direction = "to" if e["from"] == name else "from"
            lines.append(f"\narrow {direction} {', '.join(other['paths'])}: {e['label']}\n{e['connection_code']}")
            for field in EDGE_TEXT:
                if e.get(field):
                    lines.append(f"{field}: {words(e[field])}")
    return "\n".join(lines)


def card_words(data, name, stack=False, seen=None):
    """Gives one card as a cold reader sees it: link targets give way to a mark, so only the words count, and with seen the sentences it has not held before are marked."""
    return words_of(data, name, stack, lambda text: mark_new(text, seen))


def sentence_hash(sentence):
    return hashlib.sha256(sentence.encode()).hexdigest()[:16]


def sentences_of(text):
    return [part.strip() for part in SENTENCE_END.split(text or "") if part.strip()]


def mark_new(text, seen):
    """Marks each sentence of a text that a reader has not seen with ⟦ ⟧, and leaves the text alone when there is no record of what was seen."""
    if seen is None:
        return text
    return " ".join(sentence if sentence_hash(sentence) in seen else f"⟦{sentence}⟧" for sentence in sentences_of(text))


def sentences_in(data, name, stack=False):
    """Lists the hash of every sentence a card or the story holds, which is what a reader that read them has seen."""
    found = set()
    words_of(data, name, stack, lambda text: found.update(sentence_hash(x) for x in sentences_of(text)) or text)
    return sorted(found)


def hashes_of(data, stack=False):
    """Fingerprints the words of the story and of every card, which is what a cold reader passes or does not."""
    names = ["story"] if stack else ["story", *(c["id"] for c in data["cards"])]
    return {name: hashlib.sha256(card_words(data, name, stack).encode()).hexdigest() for name in names}


def card_text(map_id, card_id):
    """Prints one card as a cold reader sees it, for a cold read done by hand."""
    data = json.loads((WORK / f"{map_id}.input.json").read_text())
    stack = (WORK / f"{map_id}.stack.json").exists()
    words = card_words(data, card_id, stack)
    note(map_id, "card", story=card_id == "story")
    print(words)


def read_marks(map_id):
    """The hash of the words that last passed, for each name of a map."""
    path = WORK / f"{map_id}.read.json"
    return json.loads(path.read_text()) if path.exists() else {}


def seen_marks(map_id):
    """How many rounds of cold readers a map has had and the hash of each sentence of each name that a reader has been given."""
    path = WORK / f"{map_id}.seen.json"
    return json.loads(path.read_text()) if path.exists() else {"rounds": 0, "seen": {}}


def readers(map_id):
    """Writes each card whose words no cold reader has passed to a file with the reader's instructions, and lists the files.
    A first map is read in two rounds and an update in one; from the second round on a reader is asked only about the sentences new since."""
    data = json.loads((WORK / f"{map_id}.input.json").read_text())
    stack, read = (WORK / f"{map_id}.stack.json").exists(), read_marks(map_id)
    now = hashes_of(data, stack)
    unread = [name for name, hashed in now.items() if read.get(name) != hashed]
    marks = seen_marks(map_id)
    update = (WORK / f"{map_id}.update.json").exists()
    if unread and marks["rounds"] >= (1 if update else 2):
        print("nothing more to read: an update is read once, so read your edits yourself, then run finish" if update else
              "nothing more to read: a map is read in two rounds, so read your last edits yourself, then run finish")
        return
    folder = WORK / f"{map_id}.readers"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir()
    given = []
    for name in unread:
        before = marks["seen"].get(name)
        if before is not None and set(sentences_in(data, name, stack)) <= set(before):
            read[name] = now[name]
            continue
        path = folder / f"{name}.txt"
        if before is None:
            text = f"{READER}\n\n{card_words(data, name, stack)}"
        else:
            text = f"{REREADER}\n\n{card_words(data, name, stack, seen=set(before))}"
        path.write_text(text, encoding="utf-8")
        note(map_id, "card", story=name == "story")
        print(f"{name}\t{path}")
        given.append(name)
    if len(given) < len(unread):
        (WORK / f"{map_id}.read.json").write_text(json.dumps(read, indent=2))
    if given:
        marks["rounds"] += 1
        for name in given:
            marks["seen"][name] = sorted(set(marks["seen"].get(name, [])) | set(sentences_in(data, name, stack)))
        (WORK / f"{map_id}.seen.json").write_text(json.dumps(marks, indent=2))
    else:
        print("nothing to read: the story and every card passed as they stand")


def passed(map_id, names):
    """Records that a cold reader found nothing in the story or these cards as their words stand."""
    data = json.loads((WORK / f"{map_id}.input.json").read_text())
    stack = (WORK / f"{map_id}.stack.json").exists()
    for name in names:
        card_words(data, name, stack)
    now = hashes_of(data, stack)
    (WORK / f"{map_id}.read.json").write_text(json.dumps({**read_marks(map_id), **{name: now[name] for name in names}}, indent=2))
    print(f"passed: {', '.join(names)}")


CHECKER = """You are checking a description of a code change against the code. Below the line are numbered claims. Each gives a statement, the words in it that link to the code, and the lines that link points at, marked with >, with a few lines around them as they stand after the change. Read no other file and run no command. Decide for each claim:
- ok: the marked lines do what the linked words say. When the linked words are only a name, the marked lines declare or use that name.
- wrong: the marked lines do something that contradicts the linked words.
- elsewhere: the marked lines neither show nor contradict what the linked words say, so the link points at the wrong place or the words say more than those lines do.

Judge the linked words alone: the rest of the statement is there so you can read them. Judge what the code does, never why it was written. Use the unmarked lines only to make sense of the marked ones. Reply with one line for each claim that is not ok: its number, then wrong or elsewhere, then what the marked lines do, in one sentence. If every claim is ok, reply "none".

---"""


def claims_in(text, read):
    """Lists the code links of one piece of prose with the sentence each sits in and a hash of its words and the lines it cites."""
    sentences = [s.strip() for s in SENTENCE_END.split(text or "") if s.strip()]
    found = []
    for m in CLAIM.finditer(text or ""):
        words, path, first, last = m[1], m[2], int(m[3]), int(m[4] or m[3])
        lines = cited_lines(read, path, first, last)
        if lines is None:
            continue
        sentence = next((s for s in sentences if m[0] in s), text)
        digest = hashlib.sha256("\n".join([words, path, "\n".join(lines)]).encode()).hexdigest()
        found.append({"words": words, "sentence": sentence, "path": path, "first": first, "last": last, "hash": digest})
    return found


def claims_of(data, read):
    """Gives the code links of the story and of each card, in reading order, each link under the first name that holds it."""
    texts = {"story": [data.get(k, "") for k in ("background", "problem", "solution")]}
    for g in data.get("intents", []):
        texts["story"] += [g.get("outcome", ""), *(base.get("how", "") for base in g.get("builds_on", []))]
    for c in data.get("cards", []):
        texts[c["id"]] = [*card_texts(c), *(e.get(k, "") for e in data.get("edges", []) if e["from"] == c["id"] for k in EDGE_TEXT)]
    found, seen = {}, set()
    for name, parts in texts.items():
        found[name] = [claim for text in parts for claim in claims_in(text, read) if claim["hash"] not in seen]
        seen |= {claim["hash"] for claim in found[name]}
    return found


def claim_block(number, claim, read):
    """Shows one link as a checker sees it: the statement, the linked words and the cited lines among the lines around them."""
    lines = read(claim["path"])
    shown = range(max(1, claim["first"] - CLAIM_CONTEXT), min(len(lines), claim["last"] + CLAIM_CONTEXT) + 1)
    width = len(str(shown[-1]))
    rows = [f"{'> ' if claim['first'] <= n <= claim['last'] else '  '}{n:>{width}} | {lines[n - 1]}" for n in shown]
    return "\n".join([f"claim {number}", f"statement: {plain(claim['sentence'])}", f"linked words: {claim['words']}", claim["path"], *rows])


def write_checked(map_id, data):
    """Records every code link of a map as it stands as checked."""
    read = reader_of(json.loads((WORK / f"{map_id}.pr.json").read_text()))
    hashes = sorted({claim["hash"] for found in claims_of(data, read).values() for claim in found})
    (WORK / f"{map_id}.checked.json").write_text(json.dumps(hashes, indent=2))


def checked_hashes(map_id):
    """The hashes of the code links a checker has found to hold."""
    path = WORK / f"{map_id}.checked.json"
    return set(json.loads(path.read_text())) if path.exists() else set()


def claims(map_id, everything=False):
    """Writes each code link not yet checked to a file with the lines it cites and a checker's instructions, and lists the files."""
    if (WORK / f"{map_id}.stack.json").exists():
        print("nothing to check: a stack story links pull requests, not code")
        return
    data = json.loads((WORK / f"{map_id}.input.json").read_text())
    read = reader_of(json.loads((WORK / f"{map_id}.pr.json").read_text()))
    done = set() if everything else checked_hashes(map_id)
    folder = WORK / f"{map_id}.claims"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir()
    written = 0
    for name, found in claims_of(data, read).items():
        todo = [claim for claim in found if claim["hash"] not in done]
        if not todo:
            continue
        blocks = [claim_block(number, claim, read) for number, claim in enumerate(todo, 1)]
        (folder / f"{name}.txt").write_text(CHECKER + "\n\n" + "\n\n".join(blocks), encoding="utf-8")
        (folder / f"{name}.json").write_text(json.dumps([claim["hash"] for claim in todo]))
        written += len(todo)
        print(f"{name}\t{folder / f'{name}.txt'}")
    if not written:
        print("nothing to check: every code link was checked against its lines")
    elif not everything:
        note(map_id, "claims", links=written)


def checked(map_id, args):
    """Records the code links a checker found to hold; the numbers after a name are the links that did not."""
    held, ok, failed = set(), 0, 0
    for arg in args:
        name, _, numbers = arg.partition(":")
        path = WORK / f"{map_id}.claims" / f"{name}.json"
        if not path.exists():
            sys.exit(f"no claims file for {name}: run claims first")
        hashes = json.loads(path.read_text())
        bad = set()
        for n in (n.strip() for n in numbers.split(",") if n.strip()):
            if not n.isdigit() or not 1 <= int(n) <= len(hashes):
                sys.exit(f"{name} has no claim {n}")
            bad.add(int(n))
        held |= {h for i, h in enumerate(hashes, 1) if i not in bad}
        ok += len(hashes) - len(bad)
        failed += len(bad)
    (WORK / f"{map_id}.checked.json").write_text(json.dumps(sorted(checked_hashes(map_id) | held), indent=2))
    note(map_id, "checked", ok=ok, sent_back=failed)
    print(f"checked: {ok} links hold, {failed} sent back")


def run_server():
    ThreadingHTTPServer(("127.0.0.1", PORT), partial(ViewerHandler, directory=HOME)).serve_forever()


def listening():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def unversioned_server():
    """The process id of a viewer server from before servers named their release, None when it cannot be told. Such a
    server hands out the whole cache, so serve replaces it. Only a process running this script's serve command counts."""
    try:
        pids = subprocess.run(["lsof", "-ti", f"tcp:{PORT}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
        for pid in pids:
            command = subprocess.run(["ps", "-p", pid, "-o", "command="], capture_output=True, text=True).stdout
            if "mergeatlas.py" in command and command.split()[-1:] == ["serve"]:
                return pid
    except OSError:
        pass
    return None


def serve():
    """Starts the viewer server unless this release's is running, and replaces one left running by another release."""
    if listening():
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/index.html", timeout=3) as res:
                ours, version, pid = b"id=\"world\"" in res.read(), res.headers.get("X-MergeAtlas-Version"), res.headers.get("X-MergeAtlas-Pid")
        except OSError:
            ours = False
        if not ours:
            sys.exit(f"Port {PORT} is in use by something other than the MergeAtlas viewer.")
        if version == VERSION:
            return
        pid = pid if version else unversioned_server()
        if not (pid and pid.isdigit()):
            print(f"An older MergeAtlas viewer server is running on port {PORT} and could not be replaced. "
                  f"Stop it, then publish again.", file=sys.stderr)
            return
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
        for _ in range(30):
            if not listening():
                break
            time.sleep(0.1)
    subprocess.Popen(
        [sys.executable, __file__, "serve"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )


def publish(map_id, asked=True):
    """Checks the map and serves it as a draft, which it stays until finish says its cold read is done. asked is False
    when fetch republishes a map by itself: the run record leaves that out, and the map stays as finished as it was."""
    pr = json.loads((WORK / f"{map_id}.pr.json").read_text())
    data = json.loads((WORK / f"{map_id}.input.json").read_text())
    stats = {f["path"]: (f["additions"], f["deletions"]) for f in pr["files"]}
    # the PR's own files are read at its head; every other file at the commit the map was built on
    pinned = pr.get("pinned") or pr["headRefOid"]
    read = reader_of(pr)
    rows = diff_rows((WORK / f"{map_id}.diff").read_text())
    searches = json.loads((WORK / f"{map_id}.searches.json").read_text())
    together = json.loads((WORK / f"{map_id}.cochange.json").read_text())
    problems = problems_in(data, stats, read, rows, searches, together, pr["issues"])
    if problems:
        if asked:
            note(map_id, "publish", accepted=False, rejected_for=Counter(rule_of(p) for p in problems))
        sys.exit("Map rejected:\n" + "\n".join(f"  {p}" for p in problems))
    now, update_path = hashes_of(data), WORK / f"{map_id}.update.json"
    was = json.loads(update_path.read_text()) if update_path.exists() else None
    if asked:
        note(map_id, "publish", accepted=True, cards=len(data["cards"]), intents=len(data["intents"]),
             arrows=len(data["edges"]), words=words_in(data))
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
            "blob": f"{pr['url'].split('/pull/')[0]}/blob/{pinned}/",
            "pinned": {"commit": pinned, "base": pr.get("baseRefName"), "below": (pr.get("stack") or {}).get("below")},
            "mapped": {"at": int(time.time()), "head": pr["headRefOid"]},
            "draft": asked or is_draft(map_id),
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
    if was:
        # a card changed with the pull request when it is new or its changes were touched; one reworded for a reader did not
        changed = [c["id"] for c in data["cards"] if c["id"] not in was["hashes"]
                   or (c["id"] in was["touched"] and was["hashes"][c["id"]] != now[c["id"]])]
        output["pr"]["update"] = {"from": was["from"], "cards": changed, "story": was["hashes"].get("story") != now["story"]}
    record = stack_of_map(pr)
    if record:
        output["stubs"] = stubs_for(data, record, pr["number"], published_maps(record))
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f"{map_id}.json").write_text(json.dumps(output, indent=2))
    if record:
        refresh_stack(record)
    shutil.copy(VIEWER, HOME / "index.html")
    serve()
    print(f"{len(data['cards'])} cards, {len(data['intents'])} intents, {len(data['edges'])} arrows")
    print(f"http://127.0.0.1:{PORT}/?map={map_id}")


def finish(map_id):
    """Ends a map's draft: its cold read is done, so every card counts as passed. The viewer of an open draft picks the change up by itself."""
    data = published(map_id)
    if "pr" not in data:
        sys.exit(f"no published map {map_id}: run publish first")
    data["pr"]["draft"] = False
    (DATA / f"{map_id}.json").write_text(json.dumps(data, indent=2))
    done = json.loads((WORK / f"{map_id}.input.json").read_text())
    (WORK / f"{map_id}.read.json").write_text(json.dumps(hashes_of(done), indent=2))
    write_checked(map_id, done)
    note(map_id, "finish")
    print(f"finished: http://127.0.0.1:{PORT}/?map={map_id}")


def stack_of_map(pr):
    """The stack record fetch saved for a PR's stack, None for a PR in no stack."""
    stack = pr.get("stack")
    path = WORK / f"{stack['id']}.stack.json" if stack and stack.get("id") else None
    return json.loads(path.read_text()) if path and path.exists() else None


def published_maps(record):
    """The stack's maps that are published, by map id."""
    paths = {p["map_id"]: DATA / f"{p['map_id']}.json" for p in record["prs"]}
    return {i: json.loads(path.read_text()) for i, path in paths.items() if path.exists()}


def refresh_stack(record):
    """Rewrites what every published map and the stack page say about the stack, so each links the maps there now."""
    maps = published_maps(record)
    page_path = DATA / f"{record['id']}.json"
    published = set(maps) | ({record["id"]} if page_path.exists() else set())
    for i, data in maps.items():
        data["pr"]["stack"] = stack_strip(record, next(p["number"] for p in record["prs"] if p["map_id"] == i), published)
        (DATA / f"{i}.json").write_text(json.dumps(data, indent=2))
    if page_path.exists():
        page = json.loads(page_path.read_text())
        page_path.write_text(json.dumps(stack_page(page, record, maps), indent=2))


def publish_stack(stack_id):
    """Publishes the stack page: the story of the whole change, written once, and every PR with its map."""
    record_path, story_path = WORK / f"{stack_id}.stack.json", WORK / f"{stack_id}.input.json"
    if not record_path.exists():
        sys.exit(f"no stack {stack_id}: run fetch with the stack link first")
    record, data = json.loads(record_path.read_text()), json.loads(story_path.read_text())
    problems = stack_problems(data, record)
    if problems:
        note(stack_id, "publish-stack", accepted=False, rejected_for=Counter(rule_of(p) for p in problems))
        sys.exit("Stack story rejected:\n" + "\n".join(f"  {p}" for p in problems))
    note(stack_id, "publish-stack", accepted=True, words=words_in(data))
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f"{stack_id}.json").write_text(json.dumps(stack_page(data, record, published_maps(record)), indent=2))
    refresh_stack(record)
    shutil.copy(VIEWER, HOME / "index.html")
    serve()
    print(f"{len(record['prs'])} PRs, {len(published_maps(record))} maps published")
    print(f"http://127.0.0.1:{PORT}/?map={stack_id}")


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
    note(map_id, "export")
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
    if sys.version_info < OLDEST_PYTHON:
        sys.exit(f"MergeAtlas needs Python {'.'.join(map(str, OLDEST_PYTHON))} or newer; this is {platform.python_version()}.")
    command, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if command in ("version", "--version") and not args:
        print(VERSION)
    elif command == "report" and len(args) == 1:
        report(args[0])
    elif command == "fetch":
        fetch(args)
    elif command == "search" and len(args) in (2, 3) and args[1:-1] in ([], ["--substring"], ["--regex"], ["--paths"]):
        search(args[0], args[-1], args[1].removeprefix("--") if len(args) == 3 else "word")
    elif command == "publish" and len(args) == 1:
        publish(args[0])
    elif command == "finish" and len(args) == 1:
        finish(args[0])
    elif command == "publish-stack" and len(args) == 1:
        publish_stack(args[0])
    elif command == "export" and len(args) in (1, 2):
        export(*args)
    elif command == "card" and len(args) == 2:
        card_text(*args)
    elif command == "readers" and len(args) == 1:
        readers(args[0])
    elif command == "passed" and len(args) >= 2:
        passed(args[0], args[1:])
    elif command == "claims" and len(args) in (1, 2) and args[1:] in ([], ["--all"]):
        claims(args[0], bool(args[1:]))
    elif command == "checked" and len(args) >= 2:
        checked(args[0], args[1:])
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
