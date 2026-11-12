#!/usr/bin/env python3
"""Measure a change to the MergeAtlas skill against a fixed set of pull requests.

  run.py prepare <label> <key> [--skill <dir>]   Set up one pull request for a mapping run and print the agent's prompt.
  run.py collect <label> <key>                   Write down how the run went and stop its viewer server.
  run.py map <label> <key>... [--skill <dir>]    prepare, run the mapping agent with claude -p, collect.
  run.py score <label> [<key>...]                Check a label's maps: their links against the code, and the fixed questions.
  run.py compare <label> <label>                 Print both labels side by side as a Markdown table.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path.home() / ".cache" / "mergeatlas-evals"
REPO = Path(__file__).resolve().parent.parent
PORT = 8799
MAPPER = ("claude-sonnet-5-5", "high")
JUDGE = ("claude-sonnet-5-5", "medium")

# What every mapping run is given beyond its prompt, folder and budget. Read from claude --help (2.1.312).
MAPPER_FLAGS = [
    "--model", MAPPER[0], "--effort", MAPPER[1], "--output-format", "json",
    "--allowedTools", "Bash(python3:*)", "Bash(git:*)", "Bash(gh:*)", "Read", "Write", "Edit", "Glob", "Grep", "Agent", "Task",
]
MAPPER_KEPT = ["--disable-slash-commands", "--strict-mcp-config", "--setting-sources", "project", "--no-session-persistence"]
JUDGE_FLAGS = ["--model", JUDGE[0], "--effort", JUDGE[1], "--output-format", "json", "--allowedTools", "Read"]

STUB = '''#!/usr/bin/env python3
"""Runs the skill's script against this label's own cache and port."""
import importlib.util
from pathlib import Path

HOME = Path({home})
spec = importlib.util.spec_from_file_location("mergeatlas", {script})
real = importlib.util.module_from_spec(spec)
spec.loader.exec_module(real)
real.HOME, real.WORK, real.DATA, real.PORT = HOME, HOME / "work", HOME / "data", {port}
real.__file__ = __file__
real.main()
'''

PROMPT = """Read the file {folder}/skill/SKILL.md and follow it to map this pull request: https://github.com/{repo}/pull/{number}
Wherever it says <skill-dir>, use {folder}/skill. Do not use any installed mergeatlas skill. Use Sonnet 5.5 at medium effort for the cold readers. You have no browser, so skip opening the page in step 9. Ask no questions, because nobody can answer. When the map is finished, reply with the one word "done"."""

QUIZ = """Below are questions about a pull request, then a description of it. Answer each question in at most three sentences, from the description alone. When the description does not say, answer "not stated". Reply with one line per question: its number, a colon, your answer."""

JUDGING = """Below are questions about a pull request, each with a reference answer and an answer to judge. Reply with one line per question: its number, then yes when the answer states what the reference states, partly when it states part of it and nothing against it, no otherwise."""

VERDICT = re.compile(r"^\W*(\d+)\W+(wrong|elsewhere)\b", re.IGNORECASE | re.MULTILINE)
GRADE = re.compile(r"^\W*(\d+)\W+(yes|partly|no)\b", re.IGNORECASE | re.MULTILINE)
ANSWER = re.compile(r"^\W*(\d+)\W+(.*)$", re.MULTILINE)
CREDIT = {"yes": 1, "partly": 0.5, "no": 0}


def pulls():
    """The pull requests of the fixed set, in order."""
    return json.loads((Path(__file__).resolve().parent / "set.json").read_text())["pulls"]


def pull_of(key):
    for pull in pulls():
        if pull["key"] == key:
            return pull
    sys.exit(f"no pull {key} in the set: choose from {', '.join(p['key'] for p in pulls())}")


def map_id_of(pull):
    return f"{pull['repo'].replace('/', '-')}-{pull['number']}"


def folder_of(label):
    return ROOT / "runs" / label


def clone_of(pull):
    return ROOT / "repos" / pull["repo"].replace("/", "-")


def questions_of(key):
    path = Path(__file__).resolve().parent / "questions" / f"{key}.json"
    return json.loads(path.read_text()) if path.exists() else None


def stub_text(folder, script):
    """The script that runs a release of the skill against a label's own cache and port."""
    return STUB.format(home=json.dumps(f"{folder}/home"), script=json.dumps(str(script)), port=PORT)


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def ensure_clone(pull):
    """Puts the pull request's pinned head in a checkout of its repository and returns the folder; stops when the head moved."""
    clone = clone_of(pull)
    if not clone.exists():
        clone.parent.mkdir(parents=True, exist_ok=True)
        cloned = subprocess.run(["git", "clone", f"https://github.com/{pull['repo']}.git", str(clone)])
        if cloned.returncode:
            sys.exit(f"{pull['key']}: cannot clone {pull['repo']}")
    if git("fetch", "origin", f"pull/{pull['number']}/head", cwd=clone).returncode:
        sys.exit(f"{pull['key']}: cannot fetch pull request {pull['number']}")
    if git("rev-parse", "FETCH_HEAD", cwd=clone).stdout.strip() != pull["head"]:
        sys.exit(f"{pull['key']}: the pull request's head is no longer {pull['head']}")
    if git("checkout", "--detach", pull["head"], cwd=clone).returncode:
        sys.exit(f"{pull['key']}: cannot check out {pull['head']}")
    return clone


def snapshot(folder, skill):
    """Gives a label its own copy of the skill, which runs against the label's cache, unless it holds one already."""
    target = folder / "skill"
    if target.exists():
        return
    shutil.copytree(skill, target, ignore=shutil.ignore_patterns("__pycache__"))
    script = target / "scripts" / "mergeatlas.py"
    script.rename(target / "scripts" / "mergeatlas_real.py")
    script.write_text(stub_text(folder, target / "scripts" / "mergeatlas_real.py"))


def clear(path):
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def prepare(label, key, skill=None):
    """Sets up one pull request for a mapping run, leaving nothing of an earlier run of it, and prints the agent's prompt."""
    pull = pull_of(key)
    clone = ensure_clone(pull)
    folder, map_id = folder_of(label), map_id_of(pull)
    folder.mkdir(parents=True, exist_ok=True)
    snapshot(folder, Path(skill) if skill else REPO / "skills" / "mergeatlas")
    for left in [*(folder / "home" / "work").glob(f"{map_id}.*"), folder / "home" / "data" / f"{map_id}.json", *folder.glob(f"{key}.*")]:
        clear(left)
    prompt = PROMPT.format(folder=folder, repo=pull["repo"], number=pull["number"])
    (folder / f"{key}.prompt.txt").write_text(prompt)
    print(clone)
    print(prompt)
    return prompt


def runs_of(steps, name):
    """Counts the runs of consecutive steps of one kind."""
    return sum(1 for before, step in zip([None, *steps], steps) if step["step"] == name and (before or {}).get("step") != name)


def result_of(steps, published, claude):
    """How a run went, from its run record, its published map and the output of the agent that made it."""
    of = lambda name: [s for s in steps if s["step"] == name]
    accepted = [s for s in of("publish") if s["accepted"]]
    start = steps[0]["at"] if steps else None
    done = of("finish")
    result = {
        "finished": bool(published.get("pr")) and not published["pr"].get("draft"),
        "minutes_to_first_map": round((accepted[0]["at"] - start) / 60, 1) if accepted else None,
        "minutes_to_finish": round((done[-1]["at"] - start) / 60, 1) if done else None,
        "publishes": len(of("publish")),
        "rejected": sum(not s["accepted"] for s in of("publish")),
        "reader_files": len(of("card")),
        "reader_rounds": runs_of(steps, "card"),
        "links_checked": sum(s["links"] for s in of("claims")),
        "links_sent_back": sum(s["sent_back"] for s in of("checked")),
    }
    last = accepted[-1] if accepted else {}
    result.update({name: last.get(name) for name in ("cards", "intents", "arrows", "words")})
    duration = claude.get("duration_ms")
    result.update({"cost_usd": claude.get("total_cost_usd"), "turns": claude.get("num_turns"),
                   "agent_minutes": round(duration / 60000, 1) if duration is not None else None})
    return result


def read_json(path, empty):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return empty


def stop_server():
    """Stops the viewer server this label's run started, if one is still listening."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/index.html", timeout=3) as reply:
            pid = reply.headers.get("X-MergeAtlas-Pid")
    except OSError:
        return
    if pid and pid.isdigit():
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass


def collect(label, key):
    """Writes down how a run went, in <key>.result.json, and stops its viewer server."""
    pull = pull_of(key)
    folder, map_id = folder_of(label), map_id_of(pull)
    record = folder / "home" / "work" / f"{map_id}.run.jsonl"
    steps = [json.loads(line) for line in record.read_text().splitlines() if line.strip()] if record.exists() else []
    published = read_json(folder / "home" / "data" / f"{map_id}.json", {})
    folder.mkdir(parents=True, exist_ok=True)
    result = result_of(steps, published, read_json(folder / f"{key}.claude.json", {}))
    (folder / f"{key}.result.json").write_text(json.dumps(result, indent=2))
    stop_server()
    return result


def clean_env():
    """The environment without the variables of the session that runs this, so claude starts as a fresh one."""
    return {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}


def run_claude(args, cwd, timeout):
    """Runs claude -p with its input closed; returns its completed process, which raises on a timeout."""
    return subprocess.run(["claude", *args], cwd=cwd, env=clean_env(), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)


def map_pull(label, key, skill=None):
    """Prepares a pull request, has an agent map it with claude -p, and collects how that went."""
    pull = pull_of(key)
    prompt = prepare(label, key, skill)
    folder, clone = folder_of(label), clone_of(pull)
    args = ["-p", prompt, *MAPPER_FLAGS, "--add-dir", str(folder), *MAPPER_KEPT, "--max-budget-usd", str(pull["budget_usd"])]
    try:
        done = run_claude(args, clone, pull["timeout_min"] * 60)
        (folder / f"{key}.claude.json").write_text(done.stdout)
        if done.returncode:
            print(f"{key}: claude exited with {done.returncode}: {done.stderr.strip()[:300]}")
    except subprocess.TimeoutExpired:
        print(f"{key}: the mapping run did not finish in {pull['timeout_min']} minutes")
    return collect(label, key)


def label_of_file(file):
    """The folder of the label a file belongs to."""
    return next(p for p in Path(file).resolve().parents if p.parent == (ROOT / "runs").resolve())


def ask(file):
    """Has a fresh model read a file and do what it says; returns its reply."""
    args = ["-p", f"Read the file {file} and do what it says. Read no other file and run no command.", *JUDGE_FLAGS,
            "--add-dir", str(label_of_file(file)), "--disable-slash-commands", "--strict-mcp-config", "--setting-sources", "project",
            "--no-session-persistence"]
    done = run_claude(args, None, 600)
    if done.returncode:
        sys.exit(f"claude could not read {file}: {done.stderr.strip()[:300]}")
    return json.loads(done.stdout)["result"]


def verdicts(reply):
    """Counts the links a checker rejected, by what it found wrong with them."""
    return Counter(kind.lower() for _, kind in VERDICT.findall(reply))


def answered(reply):
    """Adds up a judge's grades: a whole point for yes, half for partly."""
    return sum(CREDIT[grade.lower()] for _, grade in GRADE.findall(reply))


def run_stub(stub, clone, *args):
    """Runs a stub script from the clone, so the commands it runs read the pull request's code."""
    done = subprocess.run([sys.executable, str(stub), *args], cwd=clone, capture_output=True, text=True)
    if done.returncode:
        sys.exit(f"{' '.join(args)}: {(done.stderr or done.stdout).strip()[:300]}")
    return done.stdout


def score_pull(label, key):
    """Checks a label's map of one pull request: its links against the code, and the fixed questions against its cards."""
    pull = pull_of(key)
    folder, map_id, clone = folder_of(label), map_id_of(pull), clone_of(pull)
    stub = folder / "score.py"
    stub.write_text(stub_text(folder, REPO / "skills" / "mergeatlas" / "scripts" / "mergeatlas.py"))
    files = [Path(line.split("\t")[1]) for line in run_stub(stub, clone, "claims", map_id, "--all").splitlines() if "\t" in line]
    links, found = 0, Counter()
    for file in files:
        links += len(json.loads(file.with_suffix(".json").read_text()))
        found.update(verdicts(ask(file)))
    score = {"links": links, "wrong": found["wrong"], "elsewhere": found["elsewhere"], "questions": None, "answered": None}
    asked = questions_of(key)
    if asked:
        data = json.loads((folder / "home" / "work" / f"{map_id}.input.json").read_text())
        cards = [run_stub(stub, clone, "card", map_id, name) for name in ["story", *(c["id"] for c in data["cards"])]]
        numbered = "\n".join(f"{n}. {item['q']}" for n, item in enumerate(asked, 1))
        quiz = folder / f"{key}.quiz.txt"
        quiz.write_text(f"{QUIZ}\n\n{numbered}\n=====\n" + "\n=====\n".join(cards))
        replies = {int(n): text.strip() for n, text in ANSWER.findall(ask(quiz))}
        blocks = [f"{n}. {item['q']}\nreference: {item['a']}\nanswer: {replies.get(n, 'not stated')}" for n, item in enumerate(asked, 1)]
        judge = folder / f"{key}.judge.txt"
        judge.write_text(f"{JUDGING}\n\n" + "\n\n".join(blocks))
        score.update({"questions": len(asked), "answered": answered(ask(judge))})
    (folder / f"{key}.score.json").write_text(json.dumps(score, indent=2))
    return score


def score(label, keys=()):
    """Scores the pull requests a label holds a result for, or the keys given."""
    folder = folder_of(label)
    keys = list(keys) or [p["key"] for p in pulls() if (folder / f"{p['key']}.result.json").exists()]
    if not keys:
        sys.exit(f"no results under {label}: run map first")
    for key in keys:
        print(f"{key}: {score_pull(label, key)}")


def share(first, second):
    return f"{first} of {second}" if first is not None and second is not None else None


# Each row of the comparison: its name, and what it shows from a pull request's result and score (None for a dash).
ROWS = (
    ("finished", lambda r, s: {True: "yes", False: "no"}.get(r.get("finished"))),
    ("minutes to the first map", lambda r, s: r.get("minutes_to_first_map")),
    ("minutes to the finished map", lambda r, s: r.get("minutes_to_finish")),
    ("cost (USD)", lambda r, s: r.get("cost_usd")),
    ("agent turns", lambda r, s: r.get("turns")),
    ("publishes rejected", lambda r, s: r.get("rejected")),
    ("cold-read rounds", lambda r, s: r.get("reader_rounds")),
    ("cards handed to readers", lambda r, s: r.get("reader_files")),
    ("links checked while mapping", lambda r, s: r.get("links_checked")),
    ("links sent back while mapping", lambda r, s: r.get("links_sent_back")),
    ("map: cards / words", lambda r, s: f"{r['cards']} / {r['words']}" if r.get("cards") is not None else None),
    ("links a checker rejects", lambda r, s: share(s["wrong"] + s["elsewhere"], s["links"]) if s else None),
    ("questions answered", lambda r, s: share(s["answered"], s["questions"]) if s else None),
)


def cell(row, result, scored):
    value = row[1](result, scored)
    return "-" if value is None else str(value)


def compare(first, second):
    """Prints two labels side by side, one table for each pull request both hold a result for."""
    tables = []
    for pull in pulls():
        both = []
        for label in (first, second):
            folder = folder_of(label)
            both.append((read_json(folder / f"{pull['key']}.result.json", None), read_json(folder / f"{pull['key']}.score.json", None)))
        if any(result is None for result, _ in both):
            continue
        lines = [f"| {pull['key']} #{pull['number']} | {first} | {second} |", "|---|---|---|"]
        lines += [f"| {row[0]} | " + " | ".join(cell(row, result, scored) for result, scored in both) + " |" for row in ROWS]
        tables.append("\n".join(lines))
    if not tables:
        sys.exit(f"no pull request has a result under both {first} and {second}")
    print("\n\n".join(tables))


def skill_option(args):
    """Splits a trailing --skill <dir> from the other arguments."""
    if len(args) >= 2 and args[-2] == "--skill":
        return args[:-2], args[-1]
    return args, None


def main():
    command, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    rest, skill = skill_option(args)
    if command == "prepare" and len(rest) == 2:
        prepare(*rest, skill)
    elif command == "collect" and len(args) == 2:
        collect(*args)
    elif command == "map" and len(rest) >= 2:
        for key in rest[1:]:
            map_pull(rest[0], key, skill)
    elif command == "score" and len(args) >= 1:
        score(args[0], args[1:])
    elif command == "compare" and len(args) == 2:
        compare(*args)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
