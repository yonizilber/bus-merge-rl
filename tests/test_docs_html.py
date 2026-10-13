"""The HTML version of the docs builds, covers every document, and has no broken links."""
import importlib.util
import re
from pathlib import Path

from busmerge.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("build_docs_html", REPO_ROOT / "scripts" / "build_docs_html.py")
build_docs_html = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_docs_html)


def test_every_markdown_document_has_a_page():
    sources = {src for src, _, _ in build_docs_html.PAGES}
    documents = {"README.md", *(p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "docs").glob("*.md"))}
    assert documents <= sources, f"not in the HTML docs: {sorted(documents - sources)}"


def test_html_docs_build_with_no_broken_links(tmp_path):
    pages = build_docs_html.build(tmp_path)
    assert len(pages) == len(build_docs_html.PAGES)
    broken = []
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert "<main>" in text and "</main>" in text
        for url in re.findall(r'\b(?:href|src)="([^"]+)"', text):
            if re.match(r"^(https?:|mailto:|#|data:)", url):
                continue
            target = (page.parent / url.split("#")[0]).resolve()
            if not target.exists():
                broken.append((page.name, url))
    assert not broken, broken


def test_hebrew_sections_are_rendered_right_to_left(tmp_path):
    qa = Path(build_docs_html.build(tmp_path)[2]).read_text(encoding="utf-8")
    blocks = re.findall(r'<div dir="rtl">(.*?)</div>', qa, flags=re.S)
    assert blocks and any("<table>" in b or "<strong>" in b for b in blocks)   # Markdown inside was converted
