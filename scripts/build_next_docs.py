#!/usr/bin/env python3
"""Build the next documentation version: one self-contained HTML site per language.

    python scripts/build_next_docs.py              # next/site/en and next/site/he
    python scripts/build_next_docs.py --lang he    # one language

The sources are Markdown in next/en and next/he. The two sets are written separately and never link to
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
import re
import shutil
import sys
from pathlib import Path

import markdown

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_docs_html  # noqa: E402
import build_test_report  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
NEXT = REPO / "next"
MEDIA = REPO / "docs" / "media"

# Output page -> source file (in next/<lang>/). The test report is generated, not written.
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
        "notes": "Notes", "more": "in the glossary", "back": "back to the text",
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
        "notes": "הערות", "more": "במילון המונחים", "back": "חזרה לטקסט",
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


def _scale_text(offset: float, scale: float) -> str:
    x = "x"
    if offset:
        x = f"(x {'+' if offset < 0 else '−'} {abs(offset):g})"
    return x if scale == 1.0 else f"{x} / {scale:g}"


def features_table(lang: str) -> str:
    text = FEATURE_TEXT[lang]
    lines = ["<!-- cards: | input -->", "", "| " + " | ".join(text["head"]) + " |", "|" + "---|" * len(text["head"])]
    for i, (key, _lo, _hi, offset, scale, _noise) in enumerate(FEATURES):
        name, meaning, rng, noise = text["rows"][key]
        lines.append(f"| {name} | {i} | {meaning} | {rng} | `{_scale_text(offset, scale)}` | {noise} |")
    return "\n".join(lines)


def test_totals(lang: str) -> str:
    cfg = LANGS[lang]
    if not build_test_report.JUNIT.exists():
        return cfg["no_totals"]
    counts = {"passed": 0, "xfailed": 0, "skipped": 0, "failed": 0}
    for c in build_test_report._cases():
        counts[c["status"]] += 1
    return cfg["totals"].format(n=sum(counts.values()), **counts)


# ---------------------------------------------------------------------------------------------- glossary

_ENTRY = re.compile(r"^## (.+?) \{#([a-z0-9_-]+)\}\s*$", re.M)


def parse_glossary(path: Path) -> dict[str, dict]:
    """key -> title, tooltip (one line), note (the first paragraph of the entry)."""
    text = path.read_text(encoding="utf-8")
    matches = list(_ENTRY.finditer(text))
    entries = {}
    for i, m in enumerate(matches):
        body = text[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()
        tip, _, rest = body.partition("\n")
        if not tip.startswith(">"):
            raise ValueError(f"{path.name}: entry '{m.group(2)}' must start with a '> one-line tooltip'")
        paragraphs = [p.strip() for p in rest.strip().split("\n\n") if p.strip()]
        if not paragraphs:
            raise ValueError(f"{path.name}: entry '{m.group(2)}' has no explanation")
        entries[m.group(2)] = {"title": m.group(1), "tip": tip.lstrip("> ").strip(), "note": paragraphs[0]}
    return entries


_TERM = re.compile(r"\[\[([a-z0-9_-]+)(?:\|([^\]]+))?\]\]")


def _plain_links(text: str, prefix: str) -> str:
    """[[key|shown]] as an ordinary link (inside the glossary and inside notes, where there is no popup)."""
    return _TERM.sub(lambda m: f"[{m.group(2) or m.group(1)}]({prefix}#{m.group(1)})", text)


def _inline(md_text: str) -> str:
    out = markdown.markdown(_plain_links(md_text, "GLOSSARY.html"))
    return re.sub(r"^<p>(.*)</p>$", r"\1", out, flags=re.S)


def link_terms(text: str, glossary: dict[str, dict], used: dict[str, int], page: str) -> str:
    """Replace [[key|shown]] with a term link; count how often each term is used on this page.

    A term may span a line break. Fenced code blocks are left alone.
    """
    def repl(m: re.Match) -> str:
        key, shown = m.group(1), m.group(2)
        if key not in glossary:
            raise KeyError(f"{page}: term [[{key}]] is not in the glossary")
        used[key] = used.get(key, 0) + 1
        entry = glossary[key]
        return (f'<a class="term" id="ref-{key}-{used[key]}" href="#note-{key}" '
                f'data-tip="{html.escape(entry["tip"], quote=True)}">'
                f'{html.escape(" ".join((shown or entry["title"]).split()))}</a>')

    parts = re.split(r"(```.*?```)", text, flags=re.S)
    return "".join(part if part.startswith("```") else _TERM.sub(repl, part) for part in parts)


def notes_html(used: dict[str, int], glossary: dict[str, dict], cfg: dict) -> str:
    if not used:
        return ""
    items = []
    for key, n in used.items():
        entry = glossary[key]
        backs = " ".join(f'<a class="back" href="#ref-{key}-{i}" title="{cfg["back"]}">↩{"" if n == 1 else i}</a>'
                         for i in range(1, n + 1))
        items.append(f'<li id="note-{key}"><strong>{html.escape(entry["title"])}.</strong> '
                     f'{_inline(entry["tip"] + " " + entry["note"])} {backs} · <a href="GLOSSARY.html#{key}">{cfg["more"]}</a></li>')
    return f'<section class="notes"><h2 id="notes">{cfg["notes"]}</h2><ol>{"".join(items)}</ol></section>'


EXTRA_CSS = """
a.term { color: inherit; text-decoration: none; border-bottom: 1.5px dotted var(--accent); cursor: help; }
a.term:hover, a.term:focus { background: var(--accent-soft); outline: none; border-radius: 3px; }
#tip { position: fixed; z-index: 50; max-width: min(24rem, calc(100vw - 16px)); padding: 9px 12px;
  border-radius: 10px; background: var(--surface); border: 1px solid var(--border); font-size: 14px;
  line-height: 1.5; box-shadow: 0 6px 24px rgba(0, 0, 0, .18); pointer-events: none; }
#tip[hidden] { display: none; }
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
"""

TIP_JS = """<div id="tip" role="tooltip" hidden></div>
<script>
(function () {
  var tip = document.getElementById('tip');
  function place(a) {
    var r = a.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
    var x = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - 8));
    var y = r.top - h - 8; if (y < 8) { y = r.bottom + 8; }
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  }
  function show(e) { var a = e.currentTarget; tip.textContent = a.getAttribute('data-tip'); tip.hidden = false; place(a); }
  function hide() { tip.hidden = true; }
  document.querySelectorAll('a.term').forEach(function (a) {
    a.addEventListener('mouseenter', show); a.addEventListener('focus', show);
    a.addEventListener('mouseleave', hide); a.addEventListener('blur', hide);
  });
  window.addEventListener('scroll', hide, { passive: true });
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


def render_page(lang: str, out_name: str, src_name: str, glossary: dict[str, dict]) -> str:
    cfg = LANGS[lang]
    source = NEXT / lang / src_name
    text = source.read_text(encoding="utf-8")
    text = text.replace("{{features_table}}", features_table(lang)).replace("{{test_totals}}", test_totals(lang))
    used: dict[str, int] = {}
    if src_name == "GLOSSARY.md":
        text = _plain_links(text, "")
    else:
        text = link_terms(text, glossary, used, source.name)
    text = build_docs_html._blank_line_before_lists(text)
    md = markdown.Markdown(extensions=["tables", "fenced_code", "codehilite", "sane_lists", "md_in_html",
                                       "attr_list", "toc"],
                           extension_configs={"codehilite": {"guess_lang": False},
                                              "toc": {"permalink": "#", "toc_depth": "2-3"}})
    body = md.convert(text)
    body = cards(body)
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    body += notes_html(used, glossary, cfg)
    body = _links_to_pages(body)
    body = re.sub(r"<img ([^>]*?badge\.svg[^>]*?)\s*/?>",
                  lambda m: f'<img {m.group(1)} onerror="this.style.display=&quot;none&quot;">', body)
    toc = md.toc if md.toc_tokens and sum(1 + len(t["children"]) for t in md.toc_tokens) >= 3 else ""
    title = next((label for out, label in cfg["nav"] if out == out_name), out_name)
    return build_docs_html.shell(title, out_name, body, toc, cfg["footer"].format(src=src_name), EXTRA_CSS,
                                 lang=lang, nav=cfg["nav"], toc_label=cfg["toc"], extra_body=TIP_JS)


def build_language(lang: str, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    glossary = parse_glossary(NEXT / lang / "GLOSSARY.md")
    written = []
    for out_name, src_name in PAGES.items():
        target = out_dir / out_name
        target.write_text(render_page(lang, out_name, src_name, glossary), encoding="utf-8")
        written.append(target)
    media_out = out_dir / "media"
    media_out.mkdir(exist_ok=True)
    for f in MEDIA.glob("*"):
        shutil.copy2(f, media_out / f.name)
    cfg = LANGS[lang]
    written.append(build_test_report.write(out_dir, lang, nav=cfg["nav"], toc_label=cfg["toc"]))
    return written


def build(out_root: Path, langs=("en", "he")) -> dict[str, list[Path]]:
    return {lang: build_language(lang, Path(out_root) / lang) for lang in langs}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", choices=sorted(LANGS), help="one language only")
    ap.add_argument("--out", type=Path, default=NEXT / "site")
    args = ap.parse_args()
    for lang, paths in build(args.out, (args.lang,) if args.lang else ("en", "he")).items():
        print(lang, args.out / lang / "index.html", f"({len(paths)} pages)")
