#!/usr/bin/env python3
"""Mechanical half of the mergeatlas skill.

  mergeatlas.py fetch [number]   Fetch a PR into the work directory.
  mergeatlas.py publish <map-id> Validate <map-id>.input.json, write the map, serve it.
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
CARD_FIELDS = ("id", "kind", "title", "paths", "summary", "bullets", "change")
EDGE_FIELDS = ("from", "to", "kind", "label", "connection", "connection_code", "connection_at", "flow")
CARD_TEXT = ("summary", "bullets", "problem", "change", "fix")
EDGE_TEXT = ("connection", "flow", "effect")
CARD_LINK = re.compile(r"\[[^\]]+\]\(([\w-]+)\)")
LOCATION = r"([^)#\s]+)#L(\d+)(?:-L(\d+))?"
CODE_LINK = re.compile(r"\[[^\]]+\]\(" + LOCATION + r"\)")
FILE_HEADER = re.compile(r"diff --git a/.* b/(.*)$")
HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@ ?(.*)$")
DECLARATION = re.compile(
    r"\b(?:class|mixin|enum|extension|typedef|interface|struct|type|def|func|function|trait|protocol|object)"
    r"\s+([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*(?:<[^>]*>)?\("
)
COMMENT_STARTS = ("//", "/*", "#")
REACH_KINDS = {"core", "cleanup"}
SURROUNDING_LINES = 4
TEST_PATH = re.compile(r"(^|/)(tests?|spec|__tests__)/|[._](test|spec)\.")
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


def declared_name(line):
    """Returns the name a top-level line declares, None for anything else."""
    if not line[:1].strip() or line.startswith(COMMENT_STARTS):
        return None
    found = DECLARATION.search(line)
    return found and (found.group(1) or found.group(2))


def changed_names(diff):
    """Maps each file to the names it changes: hunk headers name the enclosing declaration."""
    names, path, in_hunk = {}, None, False
    for line in diff.splitlines():
        header, hunk = FILE_HEADER.match(line), HUNK_HEADER.match(line)
        if header:
            path, in_hunk = header.group(1), False
            continue
        if TEST_PATH.search(path or ""):
            continue
        if hunk:
            in_hunk = True
            declaration = hunk.group(3)
        elif in_hunk and line[:1] in ("+", "-"):
            declaration = line[1:]
        else:
            continue
        name = declared_name(declaration)
        if name:
            names.setdefault(path, set()).add(name)
    return names


def public_names(path, names, commit):
    """Changes inside a private declaration reach users through the file's public names."""
    public = {name for name in names if not name.startswith("_")}
    if len(public) == len(names):
        return public
    source = subprocess.run(["git", "show", f"{commit}:{path}"], capture_output=True, text=True, errors="replace")
    declared = {declared_name(line) for line in source.stdout.splitlines()}
    return public | {name for name in declared if name and not name.startswith("_")}


def users_of(names, commit, changed):
    """Maps each changed file to the unchanged files of its language that use its names."""
    users = {}
    for path, file_names in names.items():
        for name in sorted(public_names(path, file_names, commit)):
            search = ["git", "grep", "-n", "-w", "-F", "-e", name, commit, "--", f"*{Path(path).suffix}"]
            for match in subprocess.run(search, capture_output=True, text=True, errors="replace").stdout.splitlines():
                _, user, line, text = match.split(":", 3)
                if user not in changed:
                    hits = users.setdefault(path, {}).setdefault(user, [])
                    hits.append({"name": name, "line": int(line), "text": text.strip()[:160]})
    return users


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
    users = users_of(changed_names(diff_path.read_text()), pr["headRefOid"], changed)
    reach_path = WORK / f"{map_id}.reach.json"
    reach_path.write_text(json.dumps(users, indent=2))
    (WORK / f"{map_id}.pr.json").write_text(json.dumps(pr))
    print(f"map id:      {map_id}")
    print(f"work dir:    {WORK}")
    print(f"head commit: {pr['headRefOid']}")
    print(f"diff:        {diff_path} ({len(diff_path.read_text().splitlines())} lines, binary files omitted)")
    print(f"reach:       {reach_path} ({len({u for file in users.values() for u in file})} unchanged files use changed names)")
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


def candidates_of(card, users):
    return {user for path in card["paths"] for user in users.get(path, {})}


def problems_in(data, stats, read, rows, users):
    found, seen, ids = [], set(), set()
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
        for number, snippet in enumerate(c.get("snippets", []), 1):
            check_links(f"card {name} snippet {number}", snippet, ("why",))
            if not snippet.get("why"):
                found.append(f"card {name}: snippet {number} has no why")
            if not key_lines(c, snippet.get("code", ""), rows):
                found.append(f"card {name}: snippet {number} is not in the diff of one of its files, in order")
        if c.get("kind") == "core" and not c.get("problem"):
            found.append(f"card {name}: missing problem")
        check_links(f"card {name}", c, CARD_TEXT)
        reaches, unaffected = c.get("reaches", []), c.get("unaffected", [])
        for entry in reaches:
            check_links(f"card {name}", entry, ("effect",))
            if not CODE_LINK.search(entry.get("effect", "")):
                found.append(f"card {name}: a reaches entry has no code link in its effect")
        found += [f"card {name}: an unaffected entry has no reason" for entry in unaffected if not entry.get("reason")]
        accounted = {p for entry in reaches + unaffected for p in entry.get("paths", [])}
        found += [f"card {name}: no such file {p}" for p in sorted(accounted) if read(p) is None]
        if c.get("kind") in REACH_KINDS:
            found += [f"card {name}: not accounted for: {p}" for p in sorted(candidates_of(c, users) - accounted)]
        if not CODE_LINK.search(c.get("change", "")):
            found.append(f"card {name}: change has no code link")
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
    for e in data.get("edges", []):
        name = f"{e.get('from')} -> {e.get('to')}"
        found += [f"arrow {name}: missing {k}" for k in EDGE_FIELDS if not e.get(k)]
        if e.get("kind") not in EDGE_KINDS:
            found.append(f"arrow {name}: unknown kind {e.get('kind')}")
        if e.get("from") == e.get("to"):
            found.append(f"arrow {name}: points at itself")
        found += [f"arrow {name}: no card {e[k]}" for k in ("from", "to") if e.get(k) not in ids]
        check_links(f"arrow {name}", e, EDGE_TEXT)
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
    found += [f"solution links to unknown card {i}" for i in sorted(linked - ids)]
    found += [f"solution has no link to core card {c['id']}" for c in data.get("cards", [])
              if c.get("kind") == "core" and c.get("id") not in linked]
    return found


class NoStoreHandler(SimpleHTTPRequestHandler):
    """Keeps browsers from pairing a cached viewer with a newly published map."""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


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
    users = json.loads((WORK / f"{map_id}.reach.json").read_text())
    problems = problems_in(data, stats, read, rows, users)
    if problems:
        sys.exit("Map rejected:\n" + "\n".join(f"  {p}" for p in problems))
    for c in data["cards"]:
        c["add"] = sum(stats[p][0] for p in c["paths"])
        c["del"] = sum(stats[p][1] for p in c["paths"])
        c["fingerprint"] = fingerprint(c, rows)
        for snippet in c.get("snippets", []):
            snippet["lines"] = key_lines(c, snippet.pop("code"), rows)
        if c.get("kind") in REACH_KINDS:
            c["checked"] = len(candidates_of(c, users))
    for i, e in enumerate(data["edges"]):
        e["id"] = f"e{i + 1}"
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
    }
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f"{map_id}.json").write_text(json.dumps(output, indent=2))
    shutil.copy(VIEWER, HOME / "index.html")
    serve()
    print(f"{len(data['cards'])} cards, {len(data['edges'])} arrows")
    print(f"http://127.0.0.1:{PORT}/?map={map_id}")


def main():
    command, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if command == "fetch" and len(args) <= 1:
        fetch(args)
    elif command == "publish" and len(args) == 1:
        publish(args[0])
    elif command == "serve" and not args:
        run_server()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
