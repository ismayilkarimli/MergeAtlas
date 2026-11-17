"""Builds the lean MergeAtlas skill bundle for teams that vendor the skill into their own repository.

    python3 tools/build_dist.py [--out dist]

It writes dist/mergeatlas/, the skill folder to copy as it is, and dist/mergeatlas-<version>.zip with a .sha256 beside
it. The bundle holds only what a run needs: SKILL.md, the script, the viewer and the license. Tests, evals, the site,
design notes and logos stay in this repository. The zip is reproducible: the same sources give the same bytes, so a
reviewer can rebuild it and compare checksums.
"""
import argparse
import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "mergeatlas"

# Published path in the bundle -> source in this repository. Anything not named here stays out.
FILES = {
    "SKILL.md": SKILL / "SKILL.md",
    "LICENSE": ROOT / "LICENSE",
    "scripts/mergeatlas.py": SKILL / "scripts" / "mergeatlas.py",
    "assets/viewer.html": SKILL / "assets" / "viewer.html",
}

# The earliest date a zip entry can carry, so the zip does not change with the files' modification times.
STAMP = (1980, 1, 1, 0, 0, 0)


def version():
    found = re.search(r'^VERSION = "([^"]+)"', FILES["scripts/mergeatlas.py"].read_text(encoding="utf-8"), re.M)
    if not found:
        sys.exit("no VERSION in scripts/mergeatlas.py")
    return found[1]


def build(out):
    out = Path(out)
    folder = out / "mergeatlas"
    if folder.exists():
        shutil.rmtree(folder)
    for published, source in FILES.items():
        target = folder / published
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    archive = out / f"mergeatlas-{version()}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for published in sorted(FILES):
            entry = zipfile.ZipInfo(f"mergeatlas/{published}", date_time=STAMP)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (0o644 & 0xFFFF) << 16
            zipped.writestr(entry, (folder / published).read_bytes())

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / f"{archive.name}.sha256").write_text(f"{digest}  {archive.name}\n")
    return folder, archive, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "dist"), help="where to write the bundle (default: dist/)")
    folder, archive, digest = build(parser.parse_args().out)
    print(f"skill folder  {folder}")
    print(f"zip           {archive}")
    print(f"sha256        {digest}")


if __name__ == "__main__":
    main()
