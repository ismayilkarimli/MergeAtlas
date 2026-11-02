#!/usr/bin/env python3
"""Mechanical half of the mergeatlas skill.

  mergeatlas.py fetch [number]   Fetch a PR into the work directory.
  mergeatlas.py search <map-id> [--regex | --paths] <term>
                                 Search the PR's head commit outside its changed files and log the result.
  mergeatlas.py publish <map-id> Validate <map-id>.input.json, write the map, serve it.
  mergeatlas.py card <map-id> <card-id | story>
                                 Print one card as a cold reader sees it, for the cold read.
  mergeatlas.py serve            Run the viewer server; publish starts it when needed.
"""
import hashlib
import json
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

HOME = Path.home() / ".cache" / "mergeatlas"
WORK = HOME / "work"
DATA = HOME / "data"
VIEWER = Path(__file__).resolve().parent.parent / "assets" / "viewer.html"
PORT = 8765

KINDS = {"core", "cleanup", "test", "docs", "config"}
EDGE_KINDS = {"enables", "replaces", "verifies", "docs", "depends"}
CARD_FIELDS = ("id", "kind", "title", "paths", "summary", "bullets", "changes")
COMPONENT_FIELDS = ("id", "title", "summary", "cards")
EDGE_FIELDS = ("from", "to", "kind", "label", "connection", "connection_code", "connection_at", "flow")
CARD_TEXT = ("summary", "bullets", "problem")
CHANGE_TEXT = ("problem", "change", "result")
EDGE_TEXT = ("connection", "flow", "effect")
CARD_LINK = re.compile(r"\[[^\]]+\]\(([\w-]+)\)")
LOCATION = r"([^)#\s]+)#L(\d+)(?:-L(\d+))?"
CODE_LINK = re.compile(r"\[[^\]]+\]\(" + LOCATION + r"\)")
ANY_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
CODE_SPAN = re.compile(r"`[^`]*`")
SENTENCE_END = re.compile(r"(?<=[.!?:])\s+")
POINTER = re.compile(r"\b(above|below|as mentioned|as noted|mentioned earlier|earlier card|previous card|other cards?|next card)\b", re.I)
FILE_HEADER = re.compile(r"diff --git a/.* b/(.*)$")
HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@ ?(.*)$")
REACH_KINDS = {"core", "cleanup"}
SURROUNDING_LINES = 4
SHOWN_FILES = 30
SHOWN_MATCHES = 3
COCHANGE_COMMITS = 200
COCHANGE_LARGEST_COMMIT = 50
COCHANGE_MIN_COMMITS = 3
COCHANGE_MIN_SHARE = 0.3
COCHANGE_FILES = 10
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
    existing, found = files_at(commit) - changed, {}
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


def fetch(number):
    fields = "number,title,body,state,additions,deletions,files,headRefName,headRefOid,url,closingIssuesReferences"
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


def matches_of(term, regex, commit):
    """Maps the files holding the term to their matching lines."""
    found = subprocess.run(
        ["git", "grep", "-n", "-I", "--null", "-E" if regex else "-F", "-e", term, commit],
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
        matches = matches_of(term, mode == "regex", commit)
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
    if len(matches) > SHOWN_FILES:
        print(f"... {len(matches) - SHOWN_FILES} more files")


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


def open_whys(name, text):
    """Finds the two shapes a script can see: a reason that stops short of the code, and a lean on another card."""
    found = []
    for sentence in SENTENCE_END.split(text):
        words = CODE_SPAN.sub("code", sentence)
        reason = re.search(r"\bbecause\b(.*)", words, re.I)
        if reason and not CODE_LINK.search(reason[1]):
            found.append(f"{name}: a reason ends with no code link after its because: {sentence!r}")
        pointer = POINTER.search(ANY_LINK.sub(r"\1", words))
        if pointer:
            found.append(f"{name}: leans on {pointer[0]!r}, so name the thing itself: {sentence!r}")
    return found


def problems_in(data, stats, read, rows, searches, together):
    found, seen, ids, accounted = [], set(), set(), set()
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
        for number, change in enumerate(c.get("changes", []), 1):
            where = f"card {name} change {number}"
            found += [f"{where}: missing {k}" for k in ("title", "change") if not change.get(k)]
            check_links(where, change, CHANGE_TEXT)
            for field in CHANGE_TEXT:
                found += open_whys(f"{where} {field}", change.get(field) or "")
            if not CODE_LINK.search(change.get("change", "")):
                found.append(f"{where}: change has no code link")
            if c.get("kind") == "core" and not change.get("result"):
                found.append(f"{where}: missing result")
            for code in change.get("snippets", []):
                shown.setdefault(code, []).append(change)
                if not key_lines(c, code, rows):
                    found.append(f"{where}: a snippet is not in the diff of one of its files, in order")
        for code, changes in shown.items():
            if len(changes) > 1 and len({change.get("problem") for change in changes}) < len(changes):
                found.append(f"card {name}: changes {[change.get('title') for change in changes]} share lines, so each states its own problem")
        for term in c.get("terms", []):
            found += [f"card {name}: a term needs term and meaning" for k in ("term", "meaning") if not term.get(k)]
            check_links(f"card {name} term", term, ("meaning",))
            found += open_whys(f"card {name} term", term.get("meaning", ""))
        if c.get("kind") in REACH_KINDS and len(c.get("paths", [])) > 1:
            found.append(f"card {name}: a {c['kind']} card holds one file")
        if c.get("kind") == "core" and not c.get("problem"):
            found.append(f"card {name}: missing problem")
        check_links(f"card {name}", c, CARD_TEXT)
        for field in ("summary", "problem"):
            found += open_whys(f"card {name} {field}", c.get(field) or "")
        reaches, unaffected = c.get("reaches", []), c.get("unaffected", [])
        for entry in reaches:
            check_links(f"card {name}", entry, ("effect",))
            found += open_whys(f"card {name} reach", entry.get("effect", ""))
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
    grouped, component_ids, component_of = set(), set(), {}
    for g in data.get("components", []):
        name = g.get("id", "?")
        found += [f"component {name}: missing {k}" for k in COMPONENT_FIELDS if not g.get(k)]
        if name in ids or name in component_ids:
            found.append(f"component {name}: duplicate id")
        component_ids.add(name)
        for card in g.get("cards", []):
            if card not in ids:
                found.append(f"component {name}: no card {card}")
            if card in grouped:
                found.append(f"component {name}: {card} is already in another component")
            grouped.add(card)
            component_of[card] = name
    found += [f"no component holds card {i}" for i in sorted(ids - grouped)]
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
            found += open_whys(f"arrow {name} {field}", e.get(field) or "")
        if not CODE_LINK.search(e.get("flow", "")):
            found.append(f"arrow {name}: flow has no code link")
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
    found += [f"solution links to unknown card {i}" for i in sorted(linked - ids - component_ids)]
    found += [f"solution has no link to core card {c['id']}" for c in data.get("cards", [])
              if c.get("kind") == "core" and not linked & {c.get("id"), component_of.get(c.get("id"))}]
    return found


class NoStoreHandler(SimpleHTTPRequestHandler):
    """Keeps browsers from pairing a cached viewer with a newly published map."""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def plain(text):
    return ANY_LINK.sub(r"\1", text or "")


def card_text(map_id, card_id):
    """Prints one card as a cold reader sees it, with link targets removed so only the words count."""
    data = json.loads((WORK / f"{map_id}.input.json").read_text())
    if card_id == "story":
        print("\n\n".join(plain(data.get(k)) for k in ("background", "problem", "solution")))
        return
    cards = {c["id"]: c for c in data["cards"]}
    if card_id not in cards:
        sys.exit(f"no card {card_id}: choose from story, {', '.join(cards)}")
    c = cards[card_id]
    print(f"# {', '.join(c['paths'])}")
    for field in ("summary", "problem"):
        if c.get(field):
            print(f"\n{field}: {plain(c[field])}")
    for term in c.get("terms", []):
        print(f"\nterm {term['term']}: {plain(term['meaning'])}")
    for number, change in enumerate(c["changes"], 1):
        print(f"\nchange {number}: {change['title']}")
        for field in CHANGE_TEXT:
            if change.get(field):
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
    problems = problems_in(data, stats, read, rows, searches, together)
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
    broad_reasons = {e["term"]: e["reason"] for e in data.get("broad_searches", [])}
    output = {
        "pr": {
            "number": pr["number"], "title": pr["title"], "state": pr["state"].lower(), "files": len(stats),
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
        "components": data["components"],
        "searches": [
            {"term": s["term"], "mode": s["mode"], "files": len(s["files"]), "broad": broad_reasons.get(s["term"])}
            for s in searches
        ],
    }
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f"{map_id}.json").write_text(json.dumps(output, indent=2))
    shutil.copy(VIEWER, HOME / "index.html")
    serve()
    print(f"{len(data['cards'])} cards, {len(data['components'])} components, {len(data['edges'])} arrows")
    print(f"http://127.0.0.1:{PORT}/?map={map_id}")


def main():
    command, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if command == "fetch" and len(args) <= 1:
        fetch(args)
    elif command == "search" and len(args) in (2, 3) and args[1:-1] in ([], ["--regex"], ["--paths"]):
        search(args[0], args[-1], args[1].removeprefix("--") if len(args) == 3 else "text")
    elif command == "publish" and len(args) == 1:
        publish(args[0])
    elif command == "card" and len(args) == 2:
        card_text(*args)
    elif command == "serve" and not args:
        run_server()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
