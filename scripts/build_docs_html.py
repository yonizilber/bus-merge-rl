#!/usr/bin/env python3
"""Build a readable HTML version of the project's Markdown documents.

The Markdown files stay the source; this renders them into one small static site with a shared
navigation bar, a table of contents per page, styled tables and code, light and dark themes, and
right-to-left layout for the Hebrew sections. Links between documents point to the HTML pages;
links to code, results and media point back into the repository.

    python scripts/build_docs_html.py              # writes docs/reference/html/ (ignored by git)
    python scripts/build_docs_html.py --out site/

Needs the `markdown` package (in the dev extras).
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys
from pathlib import Path

import markdown
from pygments.formatters import HtmlFormatter

sys.path.insert(0, str(Path(__file__).resolve().parent))   # sibling script build_test_report

REPO = Path(__file__).resolve().parent.parent
# (source, output page, title in the navigation)
PAGES = [
    ("README.md", "index.html", "Overview"),
    ("README.he.md", "README.he.html", "סקירה בעברית"),
    ("docs/reference/CASE_STUDY_REWARD_HACKING.md", "CASE_STUDY_REWARD_HACKING.html", "Case study"),
    ("docs/reference/QA_TEST_SUMMARY.md", "QA_TEST_SUMMARY.html", "QA summary"),
    ("docs/reference/SPECS.md", "SPECS.html", "Specification"),
    ("docs/reference/TRAINING.md", "TRAINING.html", "Training"),
    ("docs/reference/BUGS.md", "BUGS.html", "Bugs"),
    ("docs/reference/TEST_STRATEGY.md", "TEST_STRATEGY.html", "Test strategy"),
    ("docs/reference/JOURNAL.md", "JOURNAL.html", "Journal"),
    ("docs/reference/ROADMAP.md", "ROADMAP.html", "Roadmap"),
    ("docs/reference/EXPERIMENT_STOP_DESIGN.md", "EXPERIMENT_STOP_DESIGN.html", "Experiment"),
    ("docs/reference/REAL_DATA_COMPARISON.md", "REAL_DATA_COMPARISON.html", "Real data"),
]
PAGE_OF = {(REPO / src).resolve(): out for src, out, _ in PAGES}
NAV = [(out, title) for _, out, title in PAGES] + [("TEST_REPORT.html", "Test report")]

CSS = """
:root {
  --bg: #fbfbfa; --surface: #ffffff; --text: #1f2328; --muted: #5d6670; --border: #e3e5e8;
  --accent: #2563eb; --accent-soft: #e8efff; --code-bg: #f4f5f7; --row-alt: #f8f9fb;
  --header-bg: #ffffffd9; --shadow: 0 1px 2px rgba(16, 24, 40, .06);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1115; --surface: #161a20; --text: #e6e8eb; --muted: #9aa3ad; --border: #2a3039;
    --accent: #7aa2ff; --accent-soft: #1d2a45; --code-bg: #1b2028; --row-alt: #191e25;
    --header-bg: #0f1115d9; --shadow: none;
  }
}
* { box-sizing: border-box; }
html { scroll-padding-top: 76px; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans", "Noto Sans Hebrew",
        "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Header and navigation */
header.site {
  position: sticky; top: 0; z-index: 10; backdrop-filter: blur(8px); background: var(--header-bg);
  border-bottom: 1px solid var(--border);
}
header.site .bar { max-width: 1240px; margin: 0 auto; padding: 10px 16px; display: flex; gap: 18px;
  align-items: center; flex-wrap: wrap; }
header.site .brand { font-weight: 700; color: var(--text); letter-spacing: .2px; }
nav.pages { display: flex; gap: 4px; flex-wrap: wrap; }
nav.pages a { color: var(--muted); padding: 4px 10px; border-radius: 999px; font-size: 14px; }
nav.pages a:hover { color: var(--text); background: var(--accent-soft); text-decoration: none; }
nav.pages a.current { color: var(--accent); background: var(--accent-soft); font-weight: 600; }

/* Layout: content and table of contents */
.layout { max-width: 1240px; margin: 0 auto; padding: 28px 16px 64px; display: grid;
  grid-template-columns: minmax(0, 1fr); gap: 40px; }
@media (min-width: 1100px) { .layout.with-toc { grid-template-columns: minmax(0, 1fr) 210px; gap: 32px; } }
main { min-width: 0; max-width: 1080px; }
main > p, main > ul, main > ol, main > blockquote, main > pre, main > h1, main > h2, main > h3, main > h4,
main > div[dir="rtl"], main > hr { max-width: 860px; }
aside.toc { display: none; }
@media (min-width: 1100px) {
  aside.toc { display: block; position: sticky; top: 76px; align-self: start; max-height: calc(100vh - 96px);
    overflow: auto; font-size: 13.5px; border-left: 1px solid var(--border); padding-left: 16px; }
}
aside.toc .label { text-transform: uppercase; letter-spacing: .08em; font-size: 11.5px; color: var(--muted);
  margin-bottom: 6px; }
aside.toc ul { list-style: none; margin: 0; padding-left: 12px; }
aside.toc > ul { padding-left: 0; }
aside.toc li { margin: 4px 0; }
aside.toc a { color: var(--muted); }
aside.toc a:hover { color: var(--accent); }

/* Typography */
h1, h2, h3, h4 { line-height: 1.25; margin: 1.8em 0 .6em; scroll-margin-top: 76px; }
h1 { font-size: 2rem; margin-top: .2em; letter-spacing: -.01em; }
h2 { font-size: 1.45rem; padding-bottom: .3em; border-bottom: 1px solid var(--border); }
h3 { font-size: 1.15rem; }
h1 a.headerlink, h2 a.headerlink, h3 a.headerlink, h4 a.headerlink {
  opacity: 0; margin-left: .35em; font-weight: 400; color: var(--muted); }
h1:hover a.headerlink, h2:hover a.headerlink, h3:hover a.headerlink, h4:hover a.headerlink { opacity: 1; }
p, ul, ol { margin: .7em 0; }
li { margin: .25em 0; }
hr { border: 0; border-top: 1px solid var(--border); margin: 2.2em 0; }
blockquote { margin: 1.2em 0; padding: .8em 1.1em; background: var(--accent-soft);
  border-left: 4px solid var(--accent); border-radius: 0 10px 10px 0; }
blockquote p { margin: .3em 0; }
img { max-width: 100%; height: auto; border-radius: 10px; }
sub { color: var(--muted); }

/* Code */
code { font: 0.88em/1.5 ui-monospace, SFMono-Regular, "JetBrains Mono", Menlo, Consolas, monospace;
  background: var(--code-bg); padding: .08em .28em; border-radius: 5px; }
pre { background: var(--code-bg); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px;
  overflow: auto; line-height: 1.5; }
pre code { background: none; padding: 0; font-size: 13.5px; }
.codehilite { background: none !important; }

/* Tables */
.table-wrap { overflow-x: auto; margin: 1.2em 0; border: 1px solid var(--border); border-radius: 10px;
  background: var(--surface); box-shadow: var(--shadow); }
table { border-collapse: collapse; width: 100%; font-size: 14.5px; }
th, td { padding: 9px 12px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--border);
  min-width: 8.5rem; }
th:first-child, td:first-child { min-width: 3rem; overflow-wrap: normal; }
td { overflow-wrap: anywhere; }
td code { white-space: normal; overflow-wrap: anywhere; }
th { background: var(--row-alt); font-weight: 600; white-space: nowrap; }
tbody tr:nth-child(even) td { background: var(--row-alt); }
tbody tr:last-child td { border-bottom: 0; }

/* Right-to-left sections (Hebrew) */
[dir="rtl"] { text-align: right; }
div[dir="rtl"] { border-right: 3px solid var(--accent); padding-right: 16px; margin: 1.2em 0; }
[dir="rtl"] th, [dir="rtl"] td { text-align: right; }
[dir="rtl"] code, [dir="rtl"] pre { direction: ltr; unicode-bidi: isolate; }
html[dir="rtl"] div[dir="rtl"] { border-right: 0; padding-right: 0; margin: 0; }
[dir="rtl"] blockquote { border-left: 0; border-right: 4px solid var(--accent); border-radius: 10px 0 0 10px; }

footer.site { max-width: 1240px; margin: 0 auto; padding: 0 16px 40px; color: var(--muted); font-size: 13px; }
"""


def _pygments_css() -> str:
    light = HtmlFormatter(style="default").get_style_defs(".codehilite")
    dark = HtmlFormatter(style="monokai").get_style_defs(".codehilite")
    return f"{light}\n@media (prefers-color-scheme: dark) {{\n{dark}\n}}"


def _rewrite_links(body: str, source: Path, out_dir: Path) -> str:
    """Links between documents go to their HTML page; any other relative link points into the repo."""
    def fix(match: re.Match) -> str:
        attr, url = match.group(1), match.group(2)
        if re.match(r"^(https?:|mailto:|#|data:)", url):
            return match.group(0)
        path, _, anchor = url.partition("#")
        target = (source.parent / html.unescape(path)).resolve()
        if target in PAGE_OF:
            new = PAGE_OF[target]
        else:
            new = os.path.relpath(target, out_dir).replace(os.sep, "/") + ("/" if path.endswith("/") else "")
        return f'{attr}="{new}{"#" + anchor if anchor else ""}"'
    return re.sub(r'\b(href|src)="([^"]+)"', fix, body)


def _blank_line_before_lists(text: str) -> str:
    """GitHub starts a list right after a paragraph line; python-markdown needs a blank line first."""
    out, fenced = [], False
    for line in text.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
        prev = out[-1] if out else ""
        if (not fenced and re.match(r"\s*([-*]|\d+\.) ", line) and prev.strip()
                and not re.match(r"\s*([-*]|\d+\.) ", prev) and not prev.startswith((" ", "\t", ">", "|"))):
            out.append("")
        out.append(line)
    return "\n".join(out)


def _page(source: Path, out_name: str, title: str, out_dir: Path) -> str:
    text = _blank_line_before_lists(source.read_text(encoding="utf-8"))
    text = re.sub(r'<div dir="rtl">', '<div dir="rtl" markdown="1">', text)
    md = markdown.Markdown(extensions=["tables", "fenced_code", "codehilite", "sane_lists", "md_in_html",
                                       "attr_list", "toc", "footnotes"],
                           extension_configs={"codehilite": {"guess_lang": False},
                                              "toc": {"permalink": "#", "toc_depth": "2-3"}})
    body = md.convert(text)
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    body = _rewrite_links(body, source, out_dir)
    # Status badges load only once the repository is on GitHub; hide one that fails instead of a broken icon.
    body = re.sub(r"<img ([^>]*?badge\.svg[^>]*?)\s*/?>",
                  lambda m: f'<img {m.group(1)} onerror="this.style.display=&quot;none&quot;">', body)
    toc = md.toc if md.toc_tokens and sum(1 + len(t["children"]) for t in md.toc_tokens) >= 3 else ""
    rel_source = source.relative_to(REPO).as_posix()
    if source.name.endswith(".he.md"):   # a page written entirely in Hebrew
        footer = (f"נוצר מתוך <code>{rel_source}</code> על ידי <code>scripts/build_docs_html.py</code>. "
                  "קובץ ה-Markdown הוא המקור.")
        return shell(title, out_name, body, toc, footer, lang="he")
    footer = (f"Generated from <code>{rel_source}</code> by <code>scripts/build_docs_html.py</code>. "
              "The Markdown file is the source.")
    return shell(title, out_name, body, toc, footer)


def shell(title: str, out_name: str, body: str, toc: str = "", footer: str = "", extra_css: str = "",
          lang: str = "en", nav: list[tuple[str, str]] | None = None, toc_label: str | None = None,
          extra_head: str = "", extra_body: str = "") -> str:
    """A full page in the site's design: navigation bar, content, optional table of contents, footer.

    ``nav`` replaces the default navigation (a separate site, for example one language only).
    """
    current = ' class="current"'
    nav = "".join(f'<a href="{o}"{current if o == out_name else ""}>{t}</a>' for o, t in (nav or NAV))
    label = toc_label or ("בעמוד זה" if lang == "he" else "On this page")
    toc_html = f'<aside class="toc"><div class="label">{label}</div>{toc}</aside>' if toc else ""
    return f"""<!doctype html>
<html lang="{lang}"{' dir="rtl"' if lang == "he" else ""}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · bus-merge-rl</title>
<style>{CSS}
{_pygments_css()}
{extra_css}</style>
{extra_head}
</head>
<body>
<header class="site"><div class="bar"><a class="brand" href="index.html">bus-merge-rl</a>
<nav class="pages">{nav}</nav></div></header>
<div class="layout{' with-toc' if toc else ''}">
<main>
{body}
</main>
{toc_html}
</div>
<footer class="site">{footer}</footer>
{extra_body}
</body>
</html>
"""


def build(out_dir: Path) -> list[Path]:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for src, out, title in PAGES:
        target = out_dir / out
        target.write_text(_page((REPO / src).resolve(), out, title, out_dir), encoding="utf-8")
        written.append(target)
    # The test report is built from the last recorded test run (scripts/build_test_report.py).
    import build_test_report
    written.append(build_test_report.write(out_dir))
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "reference" / "html")
    args = ap.parse_args()
    for path in build(args.out):
        print(path)
