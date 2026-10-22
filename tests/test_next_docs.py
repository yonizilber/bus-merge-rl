"""The next documentation version: two self-contained sites, English and Hebrew, that never mix.

- Both sites build, have the same pages and the same glossary entries, and no broken link.
- English pages contain no Hebrew; Hebrew pages are right-to-left; neither links to the other.
- Every term link has a tooltip, a note at the bottom of its page and a link back to the exact place.
- The table of the agent's 11 inputs is checked against ``encode_features``: the ranges and the scaling
  in the documentation are the ones the code applies.
"""
import importlib.util
import re

import numpy as np
import pytest

from busmerge.paths import REPO_ROOT
from busmerge.rl.feature_encoding import FEATURE_NAMES, encode_features

_spec = importlib.util.spec_from_file_location("build_next_docs", REPO_ROOT / "scripts" / "build_next_docs.py")
build_next_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_next_docs)

HEBREW = re.compile(r"[֐-׿]")


@pytest.fixture(scope="module")
def sites(tmp_path_factory):
    root = tmp_path_factory.mktemp("next_site")
    return root, build_next_docs.build(root)


def _text(path):
    return path.read_text(encoding="utf-8")


def test_both_languages_have_the_same_pages_and_glossary_entries(sites):
    _, built = sites
    assert {p.name for p in built["en"]} == {p.name for p in built["he"]}
    en = build_next_docs.parse_glossary(REPO_ROOT / "next" / "en" / "GLOSSARY.md")
    he = build_next_docs.parse_glossary(REPO_ROOT / "next" / "he" / "GLOSSARY.md")
    assert set(en) == set(he), f"only in en: {sorted(set(en) - set(he))}, only in he: {sorted(set(he) - set(en))}"
    for lang in ("en", "he"):
        sources = {p.name for p in (REPO_ROOT / "next" / lang).glob("*.md")}
        assert sources == set(build_next_docs.PAGES.values()), lang


def test_no_broken_links_and_no_link_leaves_the_site(sites):
    root, built = sites
    for lang, pages in built.items():
        for page in pages:
            for url in re.findall(r'\b(?:href|src)="([^"]+)"', _text(page)):
                if re.match(r"^(https?:|mailto:|#|data:)", url):
                    continue
                target = (page.parent / url.split("#")[0]).resolve()
                assert target.exists(), (lang, page.name, url)
                assert (root / lang).resolve() in target.parents or target == (root / lang).resolve(), \
                    f"{lang}/{page.name} links outside its site: {url}"


def test_english_pages_contain_no_hebrew(sites):
    _, built = sites
    for page in built["en"]:
        assert not HEBREW.search(_text(page)), f"Hebrew text in {page.name}"


def test_hebrew_pages_are_right_to_left_and_in_hebrew(sites):
    _, built = sites
    for page in built["he"]:
        text = _text(page)
        assert '<html lang="he" dir="rtl">' in text, page.name
        nav = re.search(r'<nav class="pages">(.*?)</nav>', text, flags=re.S).group(1)
        assert HEBREW.search(nav) and not re.search(r"Overview|Glossary|Testing", nav), page.name
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", text, flags=re.S).group(1)
        assert HEBREW.search(h1) or page.name == "index.html", page.name   # the README's title is the project name


def test_neither_site_links_to_the_other(sites):
    _, built = sites
    for lang, other in (("en", "he"), ("he", "en")):
        for page in built[lang]:
            for url in re.findall(r'\bhref="([^"#][^"]*)"', _text(page)):
                assert f"/{other}/" not in url and not url.startswith(f"{other}/"), (lang, page.name, url)


def test_every_term_has_a_tooltip_a_note_and_a_link_back(sites):
    _, built = sites
    for lang, pages in built.items():
        for page in pages:
            text = _text(page)
            refs = re.findall(r'<a class="term" id="(ref-[^"]+)" href="#(note-[^"]+)" data-tip="([^"]+)"', text)
            for ref_id, note_id, tip in refs:
                assert tip.strip(), (lang, page.name, ref_id)
                assert f'<li id="{note_id}">' in text, (lang, page.name, note_id)
                assert f'href="#{ref_id}"' in text, f"{lang}/{page.name}: no link back to {ref_id}"
            assert "[[" not in text and "{{" not in text, f"unresolved markup in {lang}/{page.name}"


def test_the_pages_with_terms_actually_use_them(sites):
    _, built = sites
    for lang in ("en", "he"):
        counts = {p.name: len(re.findall(r'class="term"', _text(p))) for p in built[lang]}
        assert counts["index.html"] >= 10 and counts["HOW_IT_WORKS.html"] >= 20, (lang, counts)
        assert counts["GLOSSARY.html"] == 0 and counts["TEST_REPORT.html"] == 0


def test_the_input_table_has_eleven_rows_in_both_languages(sites):
    _, built = sites
    for lang in ("en", "he"):
        text = _text(next(p for p in built[lang] if p.name == "HOW_IT_WORKS.html"))
        assert len(re.findall(r'<article class="card" id="input-', text)) == len(build_next_docs.FEATURES) == 11


# --- the documented inputs are the ones the code applies --------------------------------------------------

NEUTRAL = [0.5, 0.0, 20.0, 1.0, 10.0, 0.0, 1.85, 4.5, 0.0, 0.0, 0.0]


@pytest.mark.parametrize("index", range(11))
def test_the_documented_range_and_scaling_of_each_input_are_what_the_code_applies(index):
    _key, lo, hi, offset, scale, _noise = build_next_docs.FEATURES[index]

    def encoded(value):
        raw = list(NEUTRAL)
        raw[index] = value
        return float(encode_features(11, *raw)[index])

    span = hi - lo
    assert encoded(lo) == pytest.approx((lo - offset) / scale, abs=1e-6)
    assert encoded(hi) == pytest.approx((hi - offset) / scale, abs=1e-6)
    assert encoded(hi + 10 * span) == pytest.approx(encoded(hi), abs=1e-6)     # clipped above the range
    assert encoded(lo - 10 * span) == pytest.approx(encoded(lo), abs=1e-6)     # and below it
    assert encoded(lo + span / 2) == pytest.approx((lo + span / 2 - offset) / scale, abs=1e-6)   # linear between


def test_the_documented_inputs_are_the_codes_inputs_in_the_same_order():
    code = [name.replace(" ", "_") for name in FEATURE_NAMES[11]]
    docs = [key for key, *_ in build_next_docs.FEATURES]
    assert [n.replace("lateral_clearance", "lat").split("_")[0] for n in code] == \
           [n.replace("lateral_clearance", "lat").split("_")[0] for n in docs]
    assert len(np.asarray(encode_features(11, *NEUTRAL))) == 11


def test_the_checks_can_fail():
    # A wrong range in the documentation must be caught by the comparison above.
    key, lo, hi, offset, scale, noise = build_next_docs.FEATURES[2]
    raw = list(NEUTRAL)
    raw[2] = hi
    assert float(encode_features(11, *raw)[2]) != pytest.approx((hi + 5 - offset) / scale, abs=1e-6)
