"""Writes the fonts the viewer and the site use into them, so neither page asks another machine for a font.

The viewer carries its fonts inside the page as data URLs, so a map served on this machine, a map exported as one file
and the site's sample map all show the same type with no request at all. The site serves its fonts as files of its
own. Each font is cut down to Latin and Latin Extended, as Google Fonts serves them, and to the weights and widths the
pages use; text in other scripts falls back to the system's fonts.

The fonts come from google/fonts at a fixed commit, under the SIL Open Font License, whose text goes beside them.
fontTools is a tool for this script alone, not something MergeAtlas needs, so run it as:

    uv run --with fonttools --with brotli tools/embed_fonts.py
"""

import base64
import re
import sys
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import quote

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "plugin" / "skills" / "mergeatlas" / "assets" / "viewer.html"
VIEWER_LICENSE = ROOT / "plugin" / "skills" / "mergeatlas" / "assets" / "fonts-OFL.txt"
SITE = ROOT / "site" / "index.html"
SITE_FONTS = ROOT / "site" / "assets" / "fonts"

COMMIT = "cc5661d43cd4f9aad5567033a8e15ca28dc35c86"
UPSTREAM = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl"

# The ranges Google Fonts names latin and latin-ext.
LATIN = ("U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,"
         "U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD")
LATIN_EXT = ("U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,"
             "U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF")

# family, folder in google/fonts, file, the axis ranges the pages use, the CSS ranges they come out as, and the page
FONTS = [
    ("Atkinson Hyperlegible Next", "atkinsonhyperlegiblenext", "AtkinsonHyperlegibleNext[wght].ttf",
     {"wght": (400, 700)}, {"font-weight": "400 700"}, "both"),
    ("Atkinson Hyperlegible Mono", "atkinsonhyperlegiblemono", "AtkinsonHyperlegibleMono[wght].ttf",
     {"wght": (400, 600)}, {"font-weight": "400 600"}, "both"),
    ("Archivo", "archivo", "Archivo[wdth,wght].ttf",
     {"wdth": (100, 125), "wght": (400, 900)}, {"font-weight": "400 900", "font-stretch": "100% 125%"}, "site"),
]

START, END = "<!-- fonts: written by tools/embed_fonts.py -->", "<!-- /fonts -->"


def download(url, to):
    with urllib.request.urlopen(url, timeout=60) as res:
        to.write_bytes(res.read())
    return to


def cut(source, axes):
    """The font at source, limited to the axis ranges and the Latin ranges, as WOFF2 bytes. Every name record stays,
    so each copy keeps its copyright and license notice as the license asks."""
    limited = source.with_suffix(".limited.ttf")
    limited_font = instancer.instantiateVariableFont(TTFont(source), {tag: instancer.AxisTriple(lo, None, hi) for tag, (lo, hi) in axes.items()})
    # the font keeps its own modified date, so the same sources always give the same bytes
    limited_font.recalcTimestamp = False
    limited_font.save(limited)
    # read back from disk, since the subsetter cannot cut the glyph variations an instanced font still holds lazily
    font = TTFont(limited, recalcTimestamp=False)
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.notdef_outline = True
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=subset.parse_unicodes(f"{LATIN},{LATIN_EXT}"))
    subsetter.subset(font)
    out = source.with_suffix(".woff2")
    font.flavor = "woff2"
    font.save(out)
    return out.read_bytes()


def face(family, ranges, src):
    rules = "".join(f"{k}:{v};" for k, v in ranges.items())
    return f"@font-face{{font-family:\"{family}\";font-style:normal;{rules}font-display:swap;src:url({src}) format(\"woff2\")}}"


def put(page, block):
    text = page.read_text(encoding="utf-8")
    found = re.compile(re.escape(START) + ".*?" + re.escape(END), re.S)
    if not found.search(text):
        sys.exit(f"{page} has no {START} ... {END} block to write the fonts into")
    page.write_text(found.sub(lambda _: f"{START}\n{block}\n{END}", text, count=1), encoding="utf-8")


def main():
    viewer, site, licenses = [], [], {}
    SITE_FONTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for family, folder, file, axes, ranges, page in FONTS:
            print(f"{family}: downloading and cutting")
            woff2 = cut(download(f"{UPSTREAM}/{folder}/{quote(file)}", Path(tmp) / file.replace("[", "-").replace("]", "")), axes)
            licenses[family] = urllib.request.urlopen(f"{UPSTREAM}/{folder}/OFL.txt", timeout=60).read().decode("utf-8")
            name = family.replace(" ", "") + ".woff2"
            (SITE_FONTS / name).write_bytes(woff2)
            site.append(face(family, ranges, f"assets/fonts/{name}"))
            if page == "both":
                viewer.append(face(family, ranges, "data:font/woff2;base64," + base64.b64encode(woff2).decode()))
            print(f"  {len(woff2) / 1024:.1f} KB")
    both = [f for f, *_, page in FONTS if page == "both"]
    note = "/* {} under the SIL Open Font License 1.1, cut to Latin; {} has the license. */"
    put(VIEWER, "<style>" + note.format(" and ".join(both), "fonts-OFL.txt") + "\n" + "\n".join(viewer) + "</style>")
    put(SITE, "<style>" + note.format(", ".join(licenses), "assets/fonts/OFL.txt") + "\n" + "\n".join(site) + "</style>")
    VIEWER_LICENSE.write_text("\n\n".join(f"{f}\n\n{licenses[f]}" for f in both), encoding="utf-8")
    (SITE_FONTS / "OFL.txt").write_text("\n\n".join(f"{f}\n\n{t}" for f, t in licenses.items()), encoding="utf-8")


if __name__ == "__main__":
    main()
