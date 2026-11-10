#!/usr/bin/env python3
"""Build the next documentation version: one self-contained HTML site per language.

    python scripts/build_next_docs.py              # docs/archive/v2-next/site/en and .../he
    python scripts/build_next_docs.py --lang he    # one language

The sources are Markdown in docs/archive/v2-next/en and docs/archive/v2-next/he (the second version) or docs/current (the third). The two sets are written separately and never link to
each other: every page of a site is in one language, and the navigation, the table of contents, the
notes and the test report are too.

Terms. A source writes ``[[idm]]`` or ``[[idm|the IDM model]]`` where a term first needs explaining.
The entry comes from that language's GLOSSARY.md (``## Title {#idm}``, then a one-line ``> tooltip``,
then the explanation). On the page the term shows its tooltip on hover or focus, and a click jumps to a
note at the bottom of the same page; the note has a back link to the exact place in the text.

Placeholders. ``{{features_table}}`` (the 11 inputs of the agent, with the ranges the code uses; a
test checks them against ``encode_features``) and ``{{test_totals}}`` (from the last recorded test run).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
from pathlib import Path

import latex2mathml.converter
import markdown
from markdown.extensions.toc import slugify_unicode

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_docs_html  # noqa: E402
import build_test_report  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
NEXT = REPO / "docs" / "archive" / "v2-next"
MEDIA = REPO / "docs" / "media"

# Output page -> source file (in <root>/<lang>/). The test report is generated, not written.
PAGES = {
    "index.html": "README.md",
    "HOW_IT_WORKS.html": "HOW_IT_WORKS.md",
    "CASE_STUDY.html": "CASE_STUDY.md",
    "HISTORY.html": "HISTORY.md",
    "TESTING.html": "TESTING.md",
    "LIMITATIONS.html": "LIMITATIONS.md",
    "GLOSSARY.html": "GLOSSARY.md",
}

LANGS = {
    "en": {
        "nav": [("index.html", "Overview"), ("HOW_IT_WORKS.html", "How it works"), ("CASE_STUDY.html", "Case study"),
                ("HISTORY.html", "History of problems"), ("TESTING.html", "Testing"),
                ("LIMITATIONS.html", "Limitations"), ("TEST_REPORT.html", "Test report"),
                ("GLOSSARY.html", "Glossary")],
        "notes": "Notes", "more": "in the glossary", "back": "back to the text", "expand": "Expand",
        "collapse": "Collapse", "note": "Note ↓", "details": "In detail",
        "toc": "On this page", "footer": "Generated from <code>next/en/{src}</code> by "
                                         "<code>scripts/build_next_docs.py</code>. The Markdown file is the source.",
        "totals": "The last full run recorded {n} test cases: {passed} passed, {xfailed} expected failures "
                  "(strict xfail), {skipped} skipped, {failed} failed.",
        "no_totals": "Run <code>python scripts/build_test_report.py</code> to record a full test run.",
    },
    "he": {
        "nav": [("index.html", "סקירה"), ("HOW_IT_WORKS.html", "איך זה עובד"), ("CASE_STUDY.html", "חקר מקרה"),
                ("HISTORY.html", "היסטוריית בעיות"), ("TESTING.html", "בדיקות"), ("LIMITATIONS.html", "מגבלות"),
                ("TEST_REPORT.html", "דוח בדיקות"), ("GLOSSARY.html", "מילון מונחים")],
        "notes": "הערות", "more": "במילון המונחים", "back": "חזרה לטקסט", "expand": "הרחב",
        "collapse": "צמצם", "note": "להערה ↓", "details": "בפירוט",
        "toc": "בעמוד זה", "footer": "נוצר מתוך <code>next/he/{src}</code> על ידי "
                                      "<code>scripts/build_next_docs.py</code>. קובץ ה-Markdown הוא המקור.",
        "totals": "ההרצה המלאה האחרונה כללה {n} מקרי בדיקה: {passed} עברו, {xfailed} כישלונות צפויים "
                  "(xfail קשיח), {skipped} דולגו, {failed} נכשלו.",
        "no_totals": "הריצו <code>python scripts/build_test_report.py</code> כדי לרשום הרצה מלאה של הבדיקות.",
    },
}

# The agent's 11 inputs, in order. (offset, scale): the network sees (value - offset) / scale, after the
# value is clipped to (lo, hi). tests/test_next_docs.py checks all of this against encode_features.
FEATURES = [
    # key, lo, hi, offset, scale, noise key
    ("progress", 0.0, 1.0, 0.0, 1.0, "none"),
    ("bus_heading", -0.54, 0.54, 0.0, 0.54, "none"),
    ("gap", -10.0, 60.0, -10.0, 70.0, "linear"),
    ("lateral_clearance", -2.0, 4.0, -2.0, 6.0, "linear"),
    ("car_speed", 0.0, 20.0, 0.0, 20.0, "quadratic"),
    ("car_acceleration", -9.0, 3.0, 0.0, 9.0, "heavy"),
    ("car_width", 1.70, 2.05, 1.85, 0.20, "tiny"),
    ("car_length", 3.5, 5.5, 4.5, 1.0, "tiny"),
    ("relative_speed", -15.0, 15.0, 0.0, 15.0, "quadratic"),
    ("relative_acceleration", -15.0, 15.0, 0.0, 15.0, "heavy"),
    ("car_heading", -0.15, 0.15, 0.0, 0.15, "linear"),
]

FEATURE_TEXT = {
    "en": {
        "head": ["Input", "Place in the vector", "What it is", "Range (clipped to)", "Scaled for the network as",
                 "Perception noise (when switched on)"],
        "rows": {
            "progress": ("Progress", "How far out of the bay the bus is: 0 in the bay (lateral position -3.5 m), "
                         "1 centred in the lane (0 m)", "0 to 1", "none: the bus knows its own position"),
            "bus_heading": ("Bus heading", "The bus's angle to the road, positive when it points toward the lane",
                            "-0.54 to 0.54 rad (about ±31°)", "none: the bus knows its own heading"),
            "gap": ("Gap", "Distance from the bus's rear bumper to the nearest car's front bumper. Positive: the car "
                    "is behind the bus. Negative: the car's front is already beside or ahead of the bus's rear. "
                    "With no car in the scan window (50 m ahead, 20 m behind the bus front) it is set to 60 m",
                    "-10 to 60 m", "grows in proportion to the gap"),
            "lateral_clearance": ("Lateral clearance", "Lane width left beside the bus after the car's width and "
                                  "its sideways drift: 3.5 m − (bus lateral position + 1.25 m) − (car width − "
                                  "car sideways offset). Negative: the two overlap sideways",
                                  "-2 to 4 m", "grows in proportion to the gap"),
            "car_speed": ("Car speed", "Speed of the nearest car", "0 to 20 m/s", "grows with the square of the gap"),
            "car_acceleration": ("Car acceleration", "Acceleration of the nearest car (negative: braking)",
                                 "-9 to 3 m/s²", "strong, plus a low-pass filter"),
            "car_width": ("Car width", "Width of the nearest car", "1.70 to 2.05 m", "tiny"),
            "car_length": ("Car length", "Length of the nearest car (4.5 m when there is none)", "3.5 to 5.5 m", "tiny"),
            "relative_speed": ("Relative speed", "Bus speed minus car speed (0 when there is no car)",
                               "-15 to 15 m/s", "grows with the square of the gap"),
            "relative_acceleration": ("Relative acceleration", "Bus acceleration minus car acceleration, the bus "
                                      "acceleration taken from its speed change over the last step",
                                      "-15 to 15 m/s²", "strong, plus a low-pass filter"),
            "car_heading": ("Car heading", "The nearest car's angle to the road (it drifts in its lane and moves "
                            "over for the bus)", "-0.15 to 0.15 rad (about ±8.6°)", "grows in proportion to the gap"),
        },
    },
    "he": {
        "head": ["קלט", "מקום בווקטור", "מה זה", "טווח (חיתוך מעבר לו)", "קנה מידה לרשת", "רעש תפיסה (כשהוא מופעל)"],
        "rows": {
            "progress": ("התקדמות", "כמה האוטובוס יצא מהמפרץ: 0 במפרץ (מיקום רוחבי ‎-3.5 מ'), "
                         "1 במרכז הנתיב (0 מ')", "0 עד 1", "אין: האוטובוס יודע את מיקומו"),
            "bus_heading": ("כיוון האוטובוס", "הזווית של האוטובוס ביחס לכביש, חיובית כשהוא מצביע לכיוון הנתיב",
                            "‎-0.54 עד 0.54 רדיאן (בערך ±31°)", "אין: האוטובוס יודע את כיוונו"),
            "gap": ("מרווח", "המרחק מפגוש האוטובוס האחורי לפגוש הקדמי של המכונית הקרובה ביותר. חיובי: המכונית "
                    "מאחורי האוטובוס. שלילי: חזית המכונית כבר לצד האחורי של האוטובוס או לפניו. כשאין מכונית בחלון "
                    "הסריקה (50 מ' לפני חזית האוטובוס, 20 מ' מאחוריה) הערך הוא 60 מ'",
                    "‎-10 עד 60 מ'", "גדל ביחס למרווח"),
            "lateral_clearance": ("מרווח רוחבי", "רוחב הנתיב שנשאר לצד האוטובוס אחרי רוחב המכונית והסחיפה הצדדית "
                                  "שלה: 3.5 מ' − (המיקום הרוחבי של האוטובוס + 1.25 מ') − (רוחב המכונית − הסטייה "
                                  "הצדדית שלה). שלילי: השניים חופפים לרוחב",
                                  "‎-2 עד 4 מ'", "גדל ביחס למרווח"),
            "car_speed": ("מהירות המכונית", "מהירות המכונית הקרובה ביותר", "0 עד 20 מ'/שנ'", "גדל עם ריבוע המרווח"),
            "car_acceleration": ("תאוצת המכונית", "תאוצת המכונית הקרובה ביותר (שלילית: בלימה)",
                                 "‎-9 עד 3 מ'/שנ'²", "חזק, ועוד מסנן מעביר-נמוכים"),
            "car_width": ("רוחב המכונית", "רוחב המכונית הקרובה ביותר", "1.70 עד 2.05 מ'", "זעיר"),
            "car_length": ("אורך המכונית", "אורך המכונית הקרובה ביותר (4.5 מ' כשאין מכונית)", "3.5 עד 5.5 מ'", "זעיר"),
            "relative_speed": ("מהירות יחסית", "מהירות האוטובוס פחות מהירות המכונית (0 כשאין מכונית)",
                               "‎-15 עד 15 מ'/שנ'", "גדל עם ריבוע המרווח"),
            "relative_acceleration": ("תאוצה יחסית", "תאוצת האוטובוס פחות תאוצת המכונית; תאוצת האוטובוס נלקחת "
                                      "משינוי המהירות שלו בצעד האחרון", "‎-15 עד 15 מ'/שנ'²",
                                      "חזק, ועוד מסנן מעביר-נמוכים"),
            "car_heading": ("כיוון המכונית", "הזווית של המכונית הקרובה ביותר ביחס לכביש (היא סוחפת בנתיב ונצמדת "
                            "הצידה בשביל האוטובוס)", "‎-0.15 עד 0.15 רדיאן (בערך ±8.6°)", "גדל ביחס למרווח"),
        },
    },
}


def site_config(root: Path) -> dict:
    """Pages, navigation and labels of the site whose sources are in ``root`` (``next`` uses the defaults).

    A root may hold a ``site.json`` with ``pages`` (output page -> source file), ``nav`` (per language, a list
    of [page, label]) and ``feature_head`` (per language, the column labels of the inputs table).
    """
    cfg = {"pages": dict(PAGES), "langs": {k: dict(v) for k, v in LANGS.items()}, "root": root,
           "feature_head": {lang: FEATURE_TEXT[lang]["head"] for lang in FEATURE_TEXT}}
    extra = root / "site.json"
    if extra.exists():
        data = json.loads(extra.read_text(encoding="utf-8"))
        cfg["pages"] = data.get("pages", cfg["pages"])
        for lang, nav in data.get("nav", {}).items():
            cfg["langs"][lang]["nav"] = [tuple(item) for item in nav]
        cfg["feature_head"].update(data.get("feature_head", {}))
    for lang, lc in cfg["langs"].items():
        lc["footer"] = lc["footer"].replace("next/", f"{root.resolve().relative_to(REPO).as_posix()}/")
    return cfg


def _scale_text(offset: float, scale: float) -> str:
    x = "x"
    if offset:
        x = f"(x {'+' if offset < 0 else '−'} {abs(offset):g})"
    return x if scale == 1.0 else f"{x} / {scale:g}"


def features_table(lang: str, head: list[str] | None = None) -> str:
    text = FEATURE_TEXT[lang]
    head = head or text["head"]
    lines = ["<!-- cards: | input -->", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for i, (key, _lo, _hi, offset, scale, _noise) in enumerate(FEATURES):
        name, meaning, rng, noise = text["rows"][key]
        lines.append(f"| {name} | {i} | {meaning} | {rng} | `{_scale_text(offset, scale)}` | {noise} |")
    return "\n".join(lines)


def test_totals(lang: str, counts: dict | None = None) -> str:
    cfg = LANGS[lang]
    counts = counts or test_counts()
    if not counts["total"]:
        return cfg["no_totals"]
    return cfg["totals"].format(n=counts["total"], **{k: counts[k] for k in ("passed", "xfailed", "skipped", "failed")})


# ---------------------------------------------------------------------------------------------- glossary

_ENTRY = re.compile(r"^## (.+?) \{#([a-z0-9_-]+)\}\s*$", re.M)
DETAILS_MARK = "<!-- details -->"
_MATH = re.compile(r"\$\$(.+?)\$\$|\$([^$\n]+?)\$", re.S)


def _extract_math(text: str) -> tuple[str, list[tuple[bool, str]]]:
    """Take ``$..$`` and ``$$..$$`` out before Markdown sees them (it would mangle ``_`` and ``*``)."""
    items: list[tuple[bool, str]] = []

    def take(m: re.Match) -> str:
        items.append((m.group(1) is not None, (m.group(1) or m.group(2)).strip()))
        return f"@@M{len(items) - 1}@@"
    return _MATH.sub(take, text), items


def _restore_math(fragment: str, items: list[tuple[bool, str]]) -> str:
    for i, (display, tex) in enumerate(items):
        ml = latex2mathml.converter.convert(tex, display="block" if display else "inline")
        ml = ml.replace("<math ", '<math dir="ltr" ', 1)
        # A one-letter identifier is italic. Left to itself the browser swaps in the "mathematical italic"
        # code points, which many systems have no font for (empty boxes); plain italic letters always draw.
        ml = re.sub(r"<mi>(&#x[0-9A-Fa-f]+;|[A-Za-z])</mi>", r'<mi class="v">\1</mi>', ml)
        fragment = fragment.replace(f"@@M{i}@@", f'<div class="math-block">{ml}</div>' if display else ml)
    return fragment


def render_fragment(md_text: str, *, inline: bool = False) -> str:
    """Markdown with math to HTML (MathML, built here: nothing to load when the page opens).

    ``[[key|shown]]`` becomes an ordinary link to the glossary entry: inside popups and notes there is no popup.
    """
    text, items = _extract_math(build_docs_html._blank_line_before_lists(_plain_links(md_text, "GLOSSARY.html")))
    out = markdown.markdown(text, extensions=["tables", "sane_lists", "fenced_code"])
    out = _restore_math(out, items)
    out = re.sub(r"<p>(<div class=\"math-block\">.*?</div>)</p>", r"\1", out, flags=re.S)
    return re.sub(r"^<p>(.*)</p>$", r"\1", out, flags=re.S) if inline else out


def parse_glossary(path: Path) -> dict[str, dict]:
    """key -> title, tip (one line), note (first paragraph), details (optional, Markdown with math)."""
    text = path.read_text(encoding="utf-8")
    matches = list(_ENTRY.finditer(text))
    entries = {}
    for i, m in enumerate(matches):
        body = text[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()
        tip, _, rest = body.partition("\n")
        if not tip.startswith(">"):
            raise ValueError(f"{path.name}: entry '{m.group(2)}' must start with a '> one-line tooltip'")
        main, _, details = rest.partition(DETAILS_MARK)
        paragraphs = [p.strip() for p in main.strip().split("\n\n") if p.strip()]
        if not paragraphs:
            raise ValueError(f"{path.name}: entry '{m.group(2)}' has no explanation")
        entries[m.group(2)] = {"title": m.group(1), "tip": tip.lstrip("> ").strip(), "note": paragraphs[0],
                               "details": details.strip() or None}
    return entries


_TERM = re.compile(r"\[\[([a-z0-9_-]+)(?:\|([^\]]+))?\]\]")


def _plain_links(text: str, prefix: str) -> str:
    """[[key|shown]] as an ordinary link (inside the glossary, popups and notes, where there is no popup)."""
    return _TERM.sub(lambda m: f"[{m.group(2) or m.group(1)}]({prefix}#{m.group(1)})", text)


def link_terms(text: str, glossary: dict[str, dict], used: dict[str, int], page: str) -> str:
    """Replace [[key|shown]] with a term link; count how often each term is linked on this page.

    Only the first use of a term in each ``##`` section is a link; a repeat in the same section is plain
    text, so a paragraph is not full of underlines. Every linked use has its own anchor, and the note at
    the bottom links back to each of them. A term may span a line break; fenced code is left alone.
    """
    def convert(section: str) -> str:
        seen: set[str] = set()

        def repl(m: re.Match) -> str:
            key, shown = m.group(1), m.group(2)
            if key not in glossary:
                raise KeyError(f"{page}: term [[{key}]] is not in the glossary")
            entry = glossary[key]
            label = html.escape(" ".join((shown or entry["title"]).split()))
            if key in seen:
                return label
            seen.add(key)
            used[key] = used.get(key, 0) + 1
            return (f'<a class="term" data-key="{key}" id="ref-{key}-{used[key]}" href="#note-{key}">{label}</a>')

        parts = re.split(r"(```.*?```)", section, flags=re.S)
        return "".join(part if part.startswith("```") else _TERM.sub(repl, part) for part in parts)

    return "".join(convert(section) for section in re.split(r"(?m)^(?=## )", text))


def notes_html(used: dict[str, int], glossary: dict[str, dict], cfg: dict) -> str:
    """The notes at the bottom of a page, and the (inert) templates the popups are filled from."""
    if not used:
        return ""
    items, templates = [], []
    for key, n in used.items():
        entry = glossary[key]
        details = render_fragment(entry["details"]) if entry["details"] else ""
        backs = " ".join(f'<a class="back" href="#ref-{key}-{i}" title="{cfg["back"]}">↩{"" if n == 1 else i}</a>'
                         for i in range(1, n + 1))
        more = (f'<details class="note-more"><summary>{cfg["expand"]}</summary>{details}</details>'
                if details else "")
        items.append(f'<li id="note-{key}"><strong><a class="note-title" href="#ref-{key}-1" '
                     f'title="{cfg["back"]}">{html.escape(entry["title"])}</a>.</strong> '
                     f'{render_fragment(entry["tip"] + " " + entry["note"], inline=True)} {backs} · '
                     f'<a href="GLOSSARY.html#{key}">{cfg["more"]}</a>{more}</li>')
        templates.append(f'<template id="tpl-{key}"><div class="tip-short">'
                         f'{render_fragment(entry["tip"], inline=True)}</div>'
                         + (f'<div class="tip-more">{details}</div>' if details else "") + "</template>")
    return (f'<section class="notes"><h2 id="notes">{cfg["notes"]}</h2><ol>{"".join(items)}</ol></section>'
            + "".join(templates))


EXTRA_CSS = """
a.term { color: inherit; text-decoration: none; border-bottom: 1.5px dotted var(--accent); cursor: help; }
a.term:hover, a.term:focus, a.term.open { background: var(--accent-soft); outline: none; border-radius: 3px; }
#pop { position: fixed; z-index: 60; width: min(27rem, calc(100vw - 16px)); max-height: calc(100vh - 16px);
  overflow: auto; padding: 12px 14px; border-radius: 12px; background: var(--surface); border: 1px solid var(--border);
  box-shadow: 0 8px 28px rgba(0, 0, 0, .22); font-size: 14.5px; line-height: 1.55; }
#pop[hidden] { display: none; }
#pop.expanded { width: min(46rem, calc(100vw - 16px)); }
#pop .tip-more { display: none; border-top: 1px solid var(--border); margin-top: 10px; padding-top: 6px; }
#pop.expanded .tip-more { display: block; }
#pop .acts { display: flex; gap: 14px; align-items: center; margin-top: 10px; font-size: 13.5px; position: sticky;
  bottom: -12px; background: var(--surface); padding: 8px 0 2px; }
#pop button { font: inherit; cursor: pointer; border: 1px solid var(--border); background: var(--accent-soft);
  color: var(--accent); border-radius: 8px; padding: 3px 12px; font-weight: 600; }
#pop a { color: var(--accent); }
#pop h3, #pop h4 { font-size: 15px; margin: .9em 0 .3em; }
.math-block { overflow-x: auto; text-align: center; margin: .6em 0; direction: ltr; }
math { font-size: 1.1em; font-family: "Cambria Math", "STIX Two Math", "Latin Modern Math", "Noto Serif", "DejaVu Serif", serif; }
math mi.v { text-transform: none; font-style: italic; }
.note-more { margin-top: 6px; }
.note-more summary { cursor: pointer; color: var(--accent); font-weight: 600; }
.note-more[open] { border-inline-start: 3px solid var(--border); padding-inline-start: 12px; margin-inline-start: 4px; }
.cards { display: grid; gap: 14px; margin: 1.2em 0; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 18px;
  box-shadow: var(--shadow); }
.card h4 { margin: 0 0 .6em; font-size: 15px; }
.card h4 a { color: var(--accent); text-decoration: none; }
.card dl { margin: 0; display: grid; grid-template-columns: 10rem 1fr; gap: 8px 18px; }
.card .pair { display: contents; }
.card dt { color: var(--muted); font-size: 13px; font-weight: 600; padding-top: 2px; }
.card dd { margin: 0; }
@media (max-width: 680px) { .card dl { grid-template-columns: 1fr; gap: 2px; } .card dt { margin-top: 8px; } }
.notes { margin-top: 3rem; border-top: 1px solid var(--border); padding-top: .5rem; font-size: 14.5px; }
.notes ol { padding-inline-start: 1.5rem; }
.notes li { margin: .5em 0; padding: 2px 6px; }
.notes li:target { background: var(--accent-soft); border-radius: 6px; }
.notes a.back { text-decoration: none; font-weight: 600; margin-inline-start: .15rem; }
.notes a.note-title { color: inherit; text-decoration: none; border-bottom: 1px solid var(--border); }
"""

POP_JS = """<div id="pop" role="dialog" aria-live="polite" hidden>
  <div class="body"></div>
  <div class="acts"><button type="button" class="expand"></button><a class="tonote" href="#"></a></div>
</div>
<script>
(function () {
  var pop = document.getElementById('pop'), body = pop.querySelector('.body');
  var btn = pop.querySelector('.expand'), toNote = pop.querySelector('.tonote');
  var L = JSON.parse(document.getElementById('pop-labels').textContent);
  var cur = null, pinned = false, timer = null;
  toNote.textContent = L.note;

  function place() {
    var r = cur.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight, m = 8;
    var x = Math.max(m, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - m));
    var y = r.bottom + 6;
    if (y + h > window.innerHeight - m) { y = r.top - h - 6; }
    y = Math.max(m, Math.min(y, window.innerHeight - h - m));
    pop.style.left = x + 'px'; pop.style.top = y + 'px';
  }
  function setExpanded(on) {
    pop.classList.toggle('expanded', on);
    btn.textContent = on ? L.collapse : L.expand;
    if (cur) { place(); }
  }
  function show(a) {
    clearTimeout(timer);
    if (cur && cur !== a) { cur.classList.remove('open'); }
    cur = a; a.classList.add('open');
    var tpl = document.getElementById('tpl-' + a.dataset.key);
    body.innerHTML = '';
    body.appendChild(tpl.content.cloneNode(true));
    var more = !!body.querySelector('.tip-more');
    btn.style.display = more ? '' : 'none';
    toNote.setAttribute('href', '#note-' + a.dataset.key);
    pop.hidden = false; setExpanded(false);
  }
  function hide() {
    pop.hidden = true; pinned = false;
    if (cur) { cur.classList.remove('open'); cur = null; }
  }
  function later() { clearTimeout(timer); timer = setTimeout(function () { if (!pinned) { hide(); } }, 260); }

  document.querySelectorAll('a.term').forEach(function (a) {
    a.addEventListener('mouseenter', function () { if (!pinned) { show(a); } });
    a.addEventListener('focus', function () { if (!pinned) { show(a); } });
    a.addEventListener('mouseleave', later);
    a.addEventListener('blur', later);
    a.addEventListener('click', function (e) {
      e.preventDefault();
      if (pinned && cur === a) { hide(); } else { show(a); pinned = true; }
    });
  });
  pop.addEventListener('mouseenter', function () { clearTimeout(timer); });
  pop.addEventListener('mouseleave', later);
  btn.addEventListener('click', function () { pinned = true; setExpanded(!pop.classList.contains('expanded')); });
  toNote.addEventListener('click', function () {
    // Remember where the reader came from: the note's title then leads back to this very place.
    var title = document.querySelector('#note-' + cur.dataset.key + ' .note-title');
    if (title) { title.setAttribute('href', '#' + cur.id); }
    hide();
  });
  document.addEventListener('click', function (e) {
    if (!pop.hidden && !pop.contains(e.target) && !e.target.closest('a.term')) { hide(); }
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { hide(); } });
  window.addEventListener('scroll', function () { if (!pinned && !pop.hidden) { hide(); } }, { passive: true });
  window.addEventListener('resize', function () { if (cur) { place(); } });
})();
</script>"""


# ------------------------------------------------------------------------------------------------ pages

def cards(body: str) -> str:
    """A table preceded by ``<!-- cards -->`` (or ``<!-- cards: Case -->``, a heading prefix) becomes one card per row.

    Wide tables with long cells are hard to read; a card shows each cell under its column name, and empty
    cells are left out. The first cell is the card's title and its anchor (``case-1``, ``o2``).
    """
    def convert(m: re.Match) -> str:
        prefix, _, key = (m.group(1) or "").partition("|")      # "Case" or "מקרה | case" (title | anchor prefix)
        prefix, key = prefix.strip(), (key.strip() or prefix.strip())
        table = m.group(2)
        heads = [h.strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", table, flags=re.S)]
        rows = re.findall(r"<tr>(.*?)</tr>", table.split("<tbody>", 1)[1], flags=re.S)
        out = ['<div class="cards">']
        for n, row in enumerate(rows):
            cells = [c.strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
            ident = re.sub(r"<[^>]+>", "", cells[0]).strip()
            anchor = re.sub(r"[^a-z0-9]+", "-", f"{key} {ident}".lower()).strip("-")
            if anchor == re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-"):    # a title with no Latin letters
                anchor = f"{anchor}-{n}"
            title = f"{prefix} {ident}".strip()
            pairs = "".join(f'<div class="pair"><dt>{h}</dt><dd>{c}</dd></div>'
                            for h, c in zip(heads[1:], cells[1:]) if c)
            out.append(f'<article class="card" id="{anchor}"><h4><a href="#{anchor}">{title}</a></h4><dl>{pairs}</dl></article>')
        out.append("</div>")
        return "\n".join(out)
    return re.sub(r"<!-- cards(?::([^>]*?))? -->\s*<table>(.*?)</table>", convert, body, flags=re.S)


def _links_to_pages(body: str) -> str:
    """Links between the Markdown sources become links between the pages of the site."""
    def fix(m: re.Match) -> str:
        name, anchor = m.group(1), m.group(2) or ""
        return f'href="{"index" if name == "README" else name}.html{anchor}"'
    return re.sub(r'href="(?!https?:|mailto:|#)([A-Za-z0-9_]+)\.md(#[^"]*)?"', fix, body)


def _pop(cfg: dict) -> str:
    labels = json.dumps({k: cfg[k] for k in ("expand", "collapse", "note")}, ensure_ascii=False)
    return f'<script type="application/json" id="pop-labels">{labels}</script>\n{POP_JS}'


def render_page(lang: str, out_name: str, src_name: str, glossary: dict[str, dict], site: dict | None = None) -> str:
    site = site or site_config(NEXT)
    cfg = site["langs"][lang]
    source = site["root"] / lang / src_name
    text = _fill_placeholders(source.read_text(encoding="utf-8"), lang, site)
    used: dict[str, int] = {}
    if src_name == "GLOSSARY.md":
        text = _plain_links(text, "").replace(DETAILS_MARK, f"**{cfg['details']}**")
    else:
        text = link_terms(text, glossary, used, source.name)
    text, math_items = _extract_math(text)
    text = build_docs_html._blank_line_before_lists(text)
    md = markdown.Markdown(extensions=["tables", "fenced_code", "codehilite", "sane_lists", "md_in_html",
                                       "attr_list", "toc"],
                           extension_configs={"codehilite": {"guess_lang": False},
                                              "toc": {"permalink": "#", "toc_depth": "2-3",
                                                      "slugify": slugify_unicode}})
    body = _restore_math(md.convert(text), math_items)
    body = cards(body)
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    body += notes_html(used, glossary, cfg)
    body = _links_to_pages(body)
    body = re.sub(r"<img ([^>]*?badge\.svg[^>]*?)\s*/?>",
                  lambda m: f'<img {m.group(1)} onerror="this.style.display=&quot;none&quot;">', body)
    toc = md.toc if md.toc_tokens and sum(1 + len(t["children"]) for t in md.toc_tokens) >= 3 else ""
    title = next((label for out, label in cfg["nav"] if out == out_name), out_name)
    return build_docs_html.shell(title, out_name, body, toc, cfg["footer"].format(src=src_name), EXTRA_CSS,
                                 lang=lang, nav=cfg["nav"], toc_label=cfg["toc"], extra_body=_pop(cfg) if used else "")


def test_counts() -> dict:
    """Counts of the last recorded full run (scripts/build_test_report.py), for {{n_passed}} and the like."""
    counts = {"total": 0, "passed": 0, "xfailed": 0, "skipped": 0, "failed": 0}
    if build_test_report.JUNIT.exists():
        for c in build_test_report._cases():
            counts[c["status"]] += 1
            counts["total"] += 1
    return counts


def _fill_placeholders(text: str, lang: str, site: dict, counts: dict | None = None) -> str:
    """``counts``: test counts to use; by default those of the last local run (outputs/, not committed)."""
    counts = counts or test_counts()
    text = (text.replace("{{features_table}}", features_table(lang, site["feature_head"].get(lang)))
                .replace("{{test_totals}}", test_totals(lang, counts)))
    if "{{n_" in text:
        for key, value in counts.items():
            text = text.replace("{{n_" + key + "}}", f"{value:,}")
    return text


def build_language(lang: str, out_dir: Path, root: Path = NEXT) -> list[Path]:
    site = site_config(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    glossary = parse_glossary(root / lang / "GLOSSARY.md")
    written = []
    for out_name, src_name in site["pages"].items():
        target = out_dir / out_name
        target.write_text(render_page(lang, out_name, src_name, glossary, site), encoding="utf-8")
        written.append(target)
    media_out = out_dir / "media"
    media_out.mkdir(exist_ok=True)
    for f in MEDIA.glob("*"):
        shutil.copy2(f, media_out / f.name)
    cfg = site["langs"][lang]
    written.append(build_test_report.write(out_dir, lang, nav=cfg["nav"], toc_label=cfg["toc"]))
    return written


# ------------------------------------------------------------------------------- GitHub-flavoured Markdown

def github_markdown(text: str, glossary: dict[str, dict], lang: str, page: str) -> str:
    """A source page as GitHub renders it: terms become footnotes (GitHub shows them at the bottom with a link
    back), math stays as $...$ (GitHub renders it), links to the HTML-only test report become plain text."""
    used: dict[str, int] = {}

    def convert(section: str) -> str:
        seen: set[str] = set()

        def repl(m: re.Match) -> str:
            key, shown = m.group(1), m.group(2)
            if key not in glossary:
                raise KeyError(f"{page}: term [[{key}]] is not in the glossary")
            label = " ".join((shown or glossary[key]["title"]).split())
            if key in seen:
                return label
            seen.add(key)
            used[key] = used.get(key, 0) + 1
            return f"{label}[^{key}]"
        parts = re.split(r"(```.*?```)", section, flags=re.S)
        return "".join(part if part.startswith("```") else _TERM.sub(repl, part) for part in parts)

    out = "".join(convert(section) for section in re.split(r"(?m)^(?=## )", text))
    out = re.sub(r"\[([^\]]+)\]\(TEST_REPORT\.html\)", r"\1 (HTML site)" if lang == "en" else r"\1 (באתר ה-HTML)", out)
    if used:
        more = "more" if lang == "en" else "עוד"
        notes = []
        for key in used:
            e = glossary[key]
            body = _plain_links(f"{e['tip']} {e['note']}", "GLOSSARY.md").replace("\n", " ")
            notes.append(f"[^{key}]: **{e['title']}.** {body} [{more}](GLOSSARY.md#{key})")
        out = out.rstrip("\n") + "\n\n" + "\n".join(notes) + "\n"
    return out


def github_glossary(text: str, lang: str) -> str:
    label = LANGS[lang]["details"]
    text = _ENTRY.sub(lambda m: f'<a name="{m.group(2)}"></a>\n\n## {m.group(1)}', text)
    return _plain_links(text, "").replace(DETAILS_MARK, f"**{label}**")


def frozen_test_counts(root: Path, refresh: bool = False) -> dict:
    """The test counts the committed Markdown shows, kept in ``root/test_counts.json`` so that the export is the
    same on every machine (the local run in outputs/ is not committed). ``refresh`` copies the last local run."""
    path = root / "test_counts.json"
    if refresh and build_test_report.JUNIT.exists():
        path.write_text(json.dumps(test_counts(), indent=1) + "\n", encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else test_counts()


def export_github(lang: str, root: Path = NEXT, out_dir: Path | None = None) -> list[Path]:
    """Write the GitHub-flavoured Markdown version of one language to ``root/github/<lang>``."""
    site = site_config(root)
    counts = frozen_test_counts(root)
    out_dir = out_dir or root / "github" / lang
    out_dir.mkdir(parents=True, exist_ok=True)
    glossary = parse_glossary(root / lang / "GLOSSARY.md")
    written = []
    for src_name in site["pages"].values():
        text = _fill_placeholders((root / lang / src_name).read_text(encoding="utf-8"), lang, site, counts)
        text = github_glossary(text, lang) if src_name == "GLOSSARY.md" else github_markdown(text, glossary, lang, src_name)
        # Images point at docs/media/ in the repository, so the GIFs are not copied once per language.
        media_rel = os.path.relpath(MEDIA, root / "github" / lang).replace(os.sep, "/")
        text = text.replace('src="media/', f'src="{media_rel}/')
        target = out_dir / src_name
        target.write_text(text, encoding="utf-8")
        written.append(target)
    return written


def build(out_root: Path, langs=("en", "he"), root: Path = NEXT) -> dict[str, list[Path]]:
    return {lang: build_language(lang, Path(out_root) / lang, root) for lang in langs}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=NEXT, help="the folder with en/ and he/ sources (default: docs/archive/v2-next; the current version is docs/current)")
    ap.add_argument("--lang", choices=sorted(LANGS), help="one language only")
    ap.add_argument("--out", type=Path, help="where the HTML site goes (default: <root>/site)")
    ap.add_argument("--github", action="store_true", help="also write GitHub-flavoured Markdown to <root>/github")
    args = ap.parse_args()
    root = args.root if args.root.is_absolute() else REPO / args.root
    out = args.out or root / "site"
    langs = (args.lang,) if args.lang else ("en", "he")
    for lang, paths in build(out, langs, root).items():
        print(lang, out / lang / "index.html", f"({len(paths)} pages)")
    if args.github:
        frozen_test_counts(root, refresh=True)
        for lang in langs:
            print(lang, root / "github" / lang, f"({len(export_github(lang, root))} Markdown files)")
