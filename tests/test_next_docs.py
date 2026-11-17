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


# The documentation versions built by scripts/build_next_docs.py: the second (docs/archive/v2-next/) and the third (docs/current/).
ROOTS = ["docs/archive/v2-next", "docs/current"]
INPUTS_PAGE = {"docs/archive/v2-next": "HOW_IT_WORKS.html", "docs/current": "AGENT.html"}


@pytest.fixture(scope="module", params=ROOTS)
def sites(request, tmp_path_factory):
    out = tmp_path_factory.mktemp("site_" + request.param.replace("/", "_"))
    src = REPO_ROOT / request.param
    return out, build_next_docs.build(out, root=src), src


def _text(path):
    return path.read_text(encoding="utf-8")


def test_both_languages_have_the_same_pages_and_glossary_entries(sites):
    _, built, src = sites
    assert {p.name for p in built["en"]} == {p.name for p in built["he"]}
    en = build_next_docs.parse_glossary(src / "en" / "GLOSSARY.md")
    he = build_next_docs.parse_glossary(src / "he" / "GLOSSARY.md")
    assert set(en) == set(he), f"only in en: {sorted(set(en) - set(he))}, only in he: {sorted(set(he) - set(en))}"
    for lang in ("en", "he"):
        sources = {p.name for p in (src / lang).glob("*.md")}
        assert sources == set(build_next_docs.site_config(src)["pages"].values()), lang


def test_no_broken_links_and_no_link_leaves_the_site(sites):
    root, built, src = sites
    for lang, pages in built.items():
        for page in pages:
            for url in re.findall(r'\b(?:href|src)="([^"]+)"', _text(page)):
                if re.match(r"^(https?:|mailto:|#|data:)", url):
                    continue
                target = (page.parent / url.split("#")[0].split("?")[0]).resolve()   # "EXPLORER.html?embed=1"
                assert target.exists(), (lang, page.name, url)
                assert (root / lang).resolve() in target.parents or target == (root / lang).resolve(), \
                    f"{lang}/{page.name} links outside its site: {url}"


def test_every_anchor_link_points_to_an_existing_id(sites):
    # "#section" links (the case study's story, the table of contents) and "PAGE.html#id" links between pages.
    _, built, src = sites
    for lang, pages in built.items():
        ids = {p.name: set(re.findall(r'\bid="([^"]+)"', _text(p))) for p in pages}
        for page in pages:
            for target, anchor in re.findall(r'\bhref="([A-Za-z_]*\.html)?#([^"]+)"', _text(page)):
                assert anchor in ids[target or page.name], (lang, page.name, f"{target}#{anchor}")


def test_english_pages_contain_no_hebrew(sites):
    _, built, src = sites
    for page in built["en"]:
        assert not HEBREW.search(_text(page)), f"Hebrew text in {page.name}"


def test_hebrew_pages_are_right_to_left_and_in_hebrew(sites):
    _, built, src = sites
    for page in built["he"]:
        text = _text(page)
        assert '<html lang="he" dir="rtl">' in text, page.name
        nav = re.search(r'<nav class="pages">(.*?)</nav>', text, flags=re.S).group(1)
        assert HEBREW.search(nav) and not re.search(r"Overview|Glossary|Testing", nav), page.name
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", text, flags=re.S).group(1)
        assert HEBREW.search(h1) or page.name == "index.html", page.name   # the README's title is the project name


def test_neither_site_links_to_the_other(sites):
    _, built, src = sites
    for lang, other in (("en", "he"), ("he", "en")):
        for page in built[lang]:
            for url in re.findall(r'\bhref="([^"#][^"]*)"', _text(page)):
                if url.startswith(("http://", "https://")):
                    continue
                assert f"/{other}/" not in url and not url.startswith(f"{other}/"), (lang, page.name, url)


def test_every_term_has_a_popup_a_note_and_a_link_back(sites):
    _, built, src = sites
    for lang, pages in built.items():
        for page in pages:
            text = _text(page)
            refs = re.findall(r'<a class="term" data-key="([a-z0-9_-]+)" id="(ref-[^"]+)" href="#(note-[^"]+)"', text)
            for key, ref_id, note_id in refs:
                assert f'<template id="tpl-{key}">' in text, (lang, page.name, key)
                assert f'<li id="{note_id}">' in text, (lang, page.name, note_id)
                assert f'class="back" href="#{ref_id}"' in text, f"{lang}/{page.name}: no link back to {ref_id}"
            if refs:
                assert 'id="pop"' in text and 'id="pop-labels"' in text, (lang, page.name)
                # the title of every note leads back to the text too
                assert len(re.findall(r'class="note-title" href="#ref-', text)) == len({k for k, *_ in refs})
            assert "[[" not in text and "{{" not in text and "@@M" not in text, f"unresolved markup in {lang}/{page.name}"


def test_ids_are_unique_on_every_page(sites):
    _, built, src = sites
    for lang, pages in built.items():
        for page in pages:
            ids = re.findall(r'\bid="([^"]+)"', _text(page))
            assert len(ids) == len(set(ids)), (lang, page.name, sorted({i for i in ids if ids.count(i) > 1}))


def test_a_term_is_linked_once_per_section_but_every_link_has_its_own_anchor():
    glossary = {"idm": {"title": "IDM", "tip": "t", "note": "n", "details": None}}
    used: dict = {}
    text = "intro [[idm]]\n\n## One\n[[idm]] and [[idm|again]]\n\n## Two\n[[idm|later]]\n"
    out = build_next_docs.link_terms(text, glossary, used, "x")
    assert used == {"idm": 3}                                    # intro, section One (once), section Two
    assert out.count('class="term"') == 3 and "again" in out and 'id="ref-idm-3"' in out
    assert 'data-key="idm" id="ref-idm-2"' in out and "<a class=\"term\" data-key=\"idm\" id=\"ref-idm-2\" href=\"#note-idm\">IDM</a> and again" in out


def test_unknown_terms_fail_the_build():
    with pytest.raises(KeyError):
        build_next_docs.link_terms("[[nope]]", {}, {}, "x")


def test_the_technical_terms_have_expandable_details_with_equations_in_both_languages(sites):
    _, built, src = sites
    entries = {lang: build_next_docs.parse_glossary(src / lang / "GLOSSARY.md") for lang in ("en", "he")}
    with_details = {lang: {k for k, v in e.items() if v["details"]} for lang, e in entries.items()}
    assert with_details["en"] == with_details["he"]
    assert {"idm", "safe_speed", "bicycle", "pure_pursuit", "ou", "noise", "ppo", "actor_critic"} <= with_details["en"]
    for lang in ("en", "he"):
        glossary = _text(next(p for p in built[lang] if p.name == "GLOSSARY.html"))
        assert glossary.count("<math") >= 25 and 'class="math-block"' in glossary
        assert "$" not in re.sub(r"<math.*?</math>", "", glossary, flags=re.S)   # no formula was left as source text
        pages = "".join(_text(p) for p in built[lang])
        for key in ("idm", "bicycle", "ou", "ppo"):
            template = re.search(rf'<template id="tpl-{key}">(.*?)</template>', pages, flags=re.S)
            assert template and 'class="tip-more"' in template.group(1) and "<math" in template.group(1), (lang, key)
            assert re.search(rf'<li id="note-{key}">.*?<details class="note-more">', pages, flags=re.S), (lang, key)


@pytest.mark.parametrize("root", ROOTS)
def test_common_terms_are_not_defined(root):
    for lang in ("en", "he"):
        entries = build_next_docs.parse_glossary(REPO_ROOT / root / lang / "GLOSSARY.md")
        assert not {"seed", "reward", "reward_hacking", "fine_tune", "ci", "dt", "bay", "boarding", "gae"} & set(entries)


def test_the_pages_with_terms_actually_use_them(sites):
    _, built, src = sites
    for lang in ("en", "he"):
        counts = {p.name: len(re.findall(r'class="term"', _text(p))) for p in built[lang]}
        assert counts["index.html"] >= 8 and counts[INPUTS_PAGE[src.relative_to(REPO_ROOT).as_posix()]] >= 10, (lang, counts)
        assert counts["GLOSSARY.html"] == 0 and counts["TEST_REPORT.html"] == 0


def test_the_input_table_has_eleven_rows_in_both_languages(sites):
    _, built, src = sites
    for lang in ("en", "he"):
        text = _text(next(p for p in built[lang] if p.name == INPUTS_PAGE[src.relative_to(REPO_ROOT).as_posix()]))
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


def test_the_github_markdown_export_is_up_to_date(tmp_path):
    # docs/current/github/ is committed so that GitHub renders it; it must be what the sources produce.
    src = REPO_ROOT / "docs/current"
    for lang in ("en", "he"):
        out = tmp_path / lang
        written = build_next_docs.export_github(lang, src, out)
        for page in written:
            committed = src / "github" / lang / page.name
            assert committed.exists() and committed.read_text(encoding="utf-8") == page.read_text(encoding="utf-8"), \
                f"run: python scripts/build_next_docs.py --root docs/current --github ({lang}/{page.name})"
            text = page.read_text(encoding="utf-8")
            assert "[[" not in text and "{{" not in text, (lang, page.name)
            for key in re.findall(r"\[\^([a-z0-9_-]+)\](?!:)", text):
                assert f"[^{key}]:" in text, (lang, page.name, key)       # every footnote has its definition


def test_the_working_brain_row_stands_out():
    """The row marked ✔ (the brain that works) gets the green 'ok' class; the replaced brains' rows do not."""
    body = ("<table><tbody><tr><td><strong>0.13.0</strong></td><td>✔ <strong>Working</strong></td></tr>"
            "<tr><td>0.11.0</td><td>✘ Replaced</td></tr></tbody></table>")
    out = build_next_docs.mark_working_rows(body)
    assert out.count('<tr class="ok">') == 1 and "<tr><td>0.11.0" in out
