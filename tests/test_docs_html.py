"""The HTML version of the docs builds, covers every document, and has no broken links."""
import importlib.util
import re

from busmerge.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("build_docs_html", REPO_ROOT / "scripts" / "build_docs_html.py")
build_docs_html = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_docs_html)


def test_every_markdown_document_has_a_page():
    sources = {src for src, _, _ in build_docs_html.PAGES}
    documents = {"README.md", *(p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "docs" / "reference").glob("*.md"))}
    assert documents <= sources, f"not in the HTML docs: {sorted(documents - sources)}"


def test_html_docs_build_with_no_broken_links(tmp_path):
    pages = build_docs_html.build(tmp_path)
    assert len(pages) == len(build_docs_html.PAGES) + 1   # plus the test report page
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
    pages = {p.name: p for p in build_docs_html.build(tmp_path)}
    qa = pages["QA_TEST_SUMMARY.html"].read_text(encoding="utf-8")
    blocks = re.findall(r'<div dir="rtl">(.*?)</div>', qa, flags=re.S)
    assert blocks and any("<table>" in b or "<strong>" in b for b in blocks)   # Markdown inside was converted
    he = pages["README.he.html"].read_text(encoding="utf-8")
    assert '<html lang="he" dir="rtl">' in he and "<h2" in he and "<table>" in he


_spec2 = importlib.util.spec_from_file_location("build_test_report", REPO_ROOT / "scripts" / "build_test_report.py")
build_test_report = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(build_test_report)


def test_every_test_file_is_described_in_both_languages():
    files = {p.name for p in (REPO_ROOT / "tests").glob("test_*.py")}
    missing = sorted(files - set(build_test_report.FILES))
    assert not missing, f"add a description to scripts/build_test_report.py FILES: {missing}"
    for name, (category, en, he) in build_test_report.FILES.items():
        assert category in build_test_report.CATEGORIES and en and he, name


def test_test_report_reads_every_status_from_a_run(tmp_path, monkeypatch):
    junit = tmp_path / "results.xml"
    junit.write_text(
        '<testsuites><testsuite name="pytest">'
        '<testcase classname="tests.test_safe_speed" name="test_a" time="0.1"/>'
        '<testcase classname="tests.test_physics_limits" name="test_b" time="0.2">'
        '<skipped type="pytest.xfail" message="BUGS O17: no mass"/></testcase>'
        '<testcase classname="tests.test_nightly" name="test_c" time="0"><skipped type="pytest.skip" message="x"/></testcase>'
        '<testcase classname="tests.test_invariants" name="test_d" time="0.3"><failure message="boom"/></testcase>'
        "</testsuite></testsuites>")
    monkeypatch.setattr(build_test_report, "JUNIT", junit)
    monkeypatch.setattr(build_test_report, "RUN_META", tmp_path / "none.json")
    monkeypatch.setattr(build_test_report, "NIGHTLY_DIR", tmp_path / "none")
    statuses = {c["name"]: c["status"] for c in build_test_report._cases()}
    assert statuses == {"test_a": "passed", "test_b": "xfailed", "test_c": "skipped", "test_d": "failed"}
    page = build_test_report.write(tmp_path).read_text(encoding="utf-8")
    assert "1 test(s) failed" in page and "O17" in page
