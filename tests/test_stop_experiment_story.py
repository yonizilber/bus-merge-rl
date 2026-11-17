"""The results tabs say what the stored measurements say: Measurements and research (docs/current/*/EXPLORER.md, the
explorer and the chapters below it) and Conclusions (docs/current/*/RESULTS.md).

Every number on the page is a ``{{stop:key}}`` token filled from results/experiments/stop_design/combined.json and the
field comparison (busmerge/stop_results.py), so a number cannot drift. What can drift is a sentence that states a
pattern in words ("the lane wins at any load up to 6 s", "the bay makes the cars slower only at short stops"). Each test
below names the sentence it guards, and recomputes the pattern from the data.
"""
import json
import re

import pytest

from busmerge import stop_results as sr
from busmerge.paths import REPO_ROOT

CURRENT = REPO_ROOT / "docs" / "current"
CONCLUSIONS = {lang: (CURRENT / lang / "RESULTS.md").read_text(encoding="utf-8") for lang in ("en", "he")}
MEASUREMENTS = {lang: (CURRENT / lang / "EXPLORER.md").read_text(encoding="utf-8") for lang in ("en", "he")}
PAGES = {lang: MEASUREMENTS[lang] + "\n" + CONCLUSIONS[lang] for lang in ("en", "he")}   # the two tabs together
D = sr.data()
RATES, DWELLS = D["rates"], D["dwells"]


def eq(rate, dwell):
    return sr.pair(rate, dwell, dwell)


@pytest.mark.parametrize("lang", ["en", "he"])
def test_every_token_on_the_page_is_known_and_filled(lang):
    used = set(re.findall(r"\{\{stop:([a-z0-9_.]+)\}\}", PAGES[lang]))
    assert used, "the page uses no generated numbers"
    filled = sr.fill(PAGES[lang], lang)                       # raises on an unknown token
    assert "{{stop:" not in filled
    for table in ("table_bus", "table_cars", "table_tipping", "table_pairs", "table_examples"):
        assert table in used, (lang, table)


@pytest.mark.parametrize("lang", ["en", "he"])
def test_the_page_assumes_no_bus_load(lang):
    """'nothing on this page assumes a bus load': no fixed 50 (or any) passengers as the default."""
    default_load = re.compile(r"(default|ברירת מחדל|ברירת המחדל)[^|\n]{0,12}\b(20|50)\b")
    for name in ("RESULTS.md", "RESEARCH.md", "README.md", "WORLD.md", "FIELD_DATA.md", "EXPLORER.md"):
        text = (REPO_ROOT / "docs" / "current" / lang / name).read_text(encoding="utf-8")
        for bad in ("50 passengers", "50 on the bus", "50 נוסעים", "50 באוטובוס", "The bus carries", "האוטובוס נושא 50"):
            assert bad not in text, (lang, name, bad)
        for line in text.splitlines():                         # "(default 50)" in a table of what is varied
            if re.search(r"bus|אוטובוס", line, re.I) and not re.search(r"app|אפליקציה", line, re.I):
                assert not default_load.search(line), (lang, name, line)


UNSOURCED = ("2 to 6 s", "2 עד 6 שניות", "about 2 to 6", "כ-2 עד 6", "30 to 50 s", "30 עד 50 שניות",
             "upper end of the measure", "בקצה העליון של המדידות", "Matches only for short stops", "תואם רק בעצירות קצרות")


def test_no_unsourced_field_ranges():
    """The bay's cost to the bus has no measured range under our conditions, and the San Francisco queue is not a
    match (four lanes, drivers pass): the pages give each source with its conditions instead."""
    pages = [REPO_ROOT / "docs" / "current" / lang / name for lang in ("en", "he")
             for name in ("FIELD_DATA.md", "RESULTS.md", "EXPLORER.md")]
    pages += [REPO_ROOT / "scripts" / "explorer" / f"{lang}.html" for lang in ("en", "he")]
    pages += [REPO_ROOT / "scripts" / "real_data_report_template.html", REPO_ROOT / "docs" / "reference" / "REAL_DATA_COMPARISON.md"]
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for bad in UNSOURCED:
            assert bad not in text, (page.name, bad)


@pytest.mark.parametrize("lang", ["en", "he"])
def test_the_conclusion_states_its_short_stop_assumption(lang):
    """'The conclusion rests on one main assumption: stops up to about 12 s' and its tipping loads come from the data."""
    text = CONCLUSIONS[lang]
    for token in ("{{stop:short_stop}}", "{{stop:tip_short_min}}", "{{stop:tip_short_max}}"):
        assert token in text, (lang, token)
    tips = [sr.tipping_bus_load(sr.interpolated_pair(r, sr.SHORT_STOP_S)) for r in RATES]
    assert all(isinstance(x, float) and 0 < x < 20 for x in tips), tips     # "the bay wins only with a nearly empty bus"
    assert sr.interpolated_pair(0.3, 10) == eq(0.3, 10)                      # a measured level is returned unchanged


@pytest.mark.parametrize("lang", ["en", "he"])
def test_the_results_are_three_tabs_measurements_conclusions_and_field_data(lang):
    """Measurements and research (the explorer, with the chapters below it) comes before Conclusions, which holds only
    the conclusion; Field data follows. Each tab links the other two."""
    site = json.loads((CURRENT / "site.json").read_text(encoding="utf-8"))
    assert site["pages"]["EXPLORER.html"] == "EXPLORER.md" and site["pages"]["RESULTS.html"] == "RESULTS.md"
    nav = [page for page, _ in site["nav"][lang]]
    i = nav.index("EXPLORER.html")
    assert nav[i: i + 3] == ["EXPLORER.html", "RESULTS.html", "FIELD_DATA.html"], nav
    measurements, conclusions = MEASUREMENTS[lang], CONCLUSIONS[lang]
    assert "<!-- embed: explorer -->" in measurements and "<!-- embed: explorer -->" not in conclusions
    assert "(RESULTS.md)" in measurements and "(FIELD_DATA.md)" in measurements
    assert "(EXPLORER.md)" in conclusions and "(FIELD_DATA.md)" in conclusions
    for table in ("table_bus", "table_cars", "table_tipping", "table_pairs", "table_examples"):   # the chapters moved
        assert "{{stop:" + table + "}}" in measurements and "{{stop:" + table + "}}" not in conclusions, table
    assert conclusions.count("\n## ") <= 3, "the Conclusions tab holds only the conclusion and what comes next"
    figure = f"media/stop_design_break_even_bus.{lang}.png"
    assert figure in conclusions and figure not in measurements, "one figure, in one tab; the other tab links to it"
    for name in ("stop_design_break_even_bus", "field_merge_time", "field_queue", "field_verdicts"):
        assert (REPO_ROOT / "docs" / "media" / f"{name}.{lang}.png").exists(), name
    assert (REPO_ROOT / "docs" / "tools" / f"stop_design_explorer.{lang}.html").exists()


TABLE_CAPTION = {"he": "**בטבלה:**", "en": "**In the table:**"}


@pytest.mark.parametrize("lang", ["en", "he"])
def test_every_table_of_numbers_says_what_its_numbers_are(lang):
    """'When numbers are used, write what they represent': each generated table is introduced by a caption paragraph
    that names the rows, the columns and the unit of the numbers, and the cells say 'over 100', not '>100'."""
    field_page = (CURRENT / lang / "FIELD_DATA.md").read_text(encoding="utf-8")
    for text in (MEASUREMENTS[lang], field_page):
        for token in re.findall(r"\{\{stop:(table_\w+)\}\}", text):
            before = text.split("{{stop:" + token + "}}")[0].rstrip().split("\n\n")[-1]
            assert before.startswith(TABLE_CAPTION[lang]), (lang, token, before[:80])
        filled = sr.fill(text, lang)
        assert ">100" not in filled and "| >" not in filled
    for table in (sr.table_examples(lang), sr.table_occupancy(lang)):        # counts of cells, said in the header
        assert sr.TEXT[lang]["n_tie"] in table.splitlines()[0]
    case = (CURRENT / lang / "CASE_STUDY.md").read_text(encoding="utf-8")
    assert ("מקרה אחד" if lang == "he" else "One case") in case.split("\n## ")[0]


@pytest.mark.parametrize("lang", ["en", "he"])
def test_the_field_data_page_uses_generated_numbers_and_its_figures(lang):
    text = (REPO_ROOT / "docs" / "current" / lang / "FIELD_DATA.md").read_text(encoding="utf-8")
    assert "{{stop:" not in sr.fill(text, lang)
    for token in ("table_per_car", "table_occupancy", "mt_mean", "mt_max", "flow_h", "a_min", "a_max"):
        assert "{{stop:" + token + "}}" in text, token
    for name in ("field_merge_time", "field_queue", "field_verdicts"):
        assert f"media/{name}.{lang}.png" in text, name


def test_the_combined_summary_holds_both_experiments():
    """'two experiments, {{runs}} runs ... 150 to 300 seeds'"""
    prov = {p["experiment"]: p for p in D["provenance"]}
    assert D["runs"] == prov["stop_design_v1"]["runs_stored"] + prov["stop_design_v2"]["runs_stored"] == 19_500
    assert DWELLS == [0, 3, 6, 10, 15, 20, 30, 45] and RATES == [0.1, 0.2, 0.3, 0.4, 0.5]
    assert {eq(r, d)[0] for r in RATES for d in DWELLS} == {150, 300}
    for name in ("stop_design_v1", "stop_design_v2"):                       # "run again from the clean commit"
        assert "+uncommitted" not in prov[name]["commit"], prov[name]


def test_the_combined_summary_reproduces_the_first_experiments_published_cells():
    summary = json.loads((REPO_ROOT / "results" / "experiments" / "stop_design_v1" / "summary.json").read_text())
    for cell in summary["cells"]:
        n, a, b, *_ = eq(cell["traffic_rate"], cell["dwell_s"])
        assert n == cell["pairs"] and a == pytest.approx(cell["delta_bus_time_s"], abs=0.01)
        assert b == pytest.approx(cell["delta_cars_time_s"], abs=0.051)


def test_the_bay_always_costs_the_bus():
    """'the bus's trip is ... longer in every one of the cells, even with no stop at all'"""
    assert all(eq(r, d)[1] > 0 for r in RATES for d in DWELLS)


def test_the_bay_slows_the_cars_only_at_short_stops():
    """'The bay makes the cars slower for stops of 6 s or shorter at every inflow, and at 10 s from 0.3 cars/s'"""
    slower = sorted((d, r) for r in RATES for d in DWELLS if eq(r, d)[2] > 0)
    assert slower == sorted([(d, r) for d in (0, 3, 6) for r in RATES] + [(10, 0.3), (10, 0.4), (10, 0.5)])
    assert sr.facts("en")["slower_cars"] == "for stops of 6 s or shorter at every inflow, and at 10 s from 0.3 cars/s"


def test_short_stops_go_to_the_lane_at_any_load():
    """'At stops of 6 s or less the lane wins at every inflow, at any bus load and any car occupancy'"""
    assert sr.lane_always_dwells() == [0, 3, 6]
    for d in (0, 3, 6):
        for r in RATES:
            for pc in (1.0, 1.2, 1.35, 1.5, 2.0):
                assert all(sr.verdict(pc, pb, eq(r, d)) != "bay" for pb in range(0, 101, 5)), (d, r, pc)
    assert [sr.tipping_bus_load(eq(r, 10)) == "lane_always" for r in RATES] == [False, False, True, True, True]
    assert all(sr.tipping_bus_load(eq(r, 10)) < 3.5 for r in (0.1, 0.2))      # "practically an empty bus"


def test_long_stops_in_dense_traffic_go_to_the_bay_even_for_a_full_bus():
    """'At 30 s and 45 s, from 0.3 cars/s, the tipping point is above 100 passengers'"""
    for d in (30, 45):
        for r in (0.3, 0.4, 0.5):
            assert sr.tipping_bus_load(eq(r, d)) > 100, (d, r)


def test_an_emptier_bus_only_moves_the_verdict_toward_the_bay():
    """'every passenger fewer on the bus moves the verdict toward the bay' (the slope in the bus load is a > 0)"""
    order = {"bay": 0, "tie": 1, "lane": 2}
    for r in RATES:
        for d in DWELLS:
            verdicts = [order[sr.verdict(sr.PC, pb, eq(r, d))] for pb in range(0, 101, 5)]
            assert verdicts == sorted(verdicts), (r, d)


def test_where_the_bay_starts_to_win():
    """'the bay starts to win at stops of 15 to 30 s, depending on the traffic and the load' (conclusion, TCRP bullet)"""
    for pb in (10, 20, 40):
        for r in RATES:
            first = next((d for d in DWELLS if sr.verdict(sr.PC, pb, eq(r, d)) == "bay"), None)
            assert first is None or first >= 15, (pb, r, first)
    firsts = {next(d for d in DWELLS if sr.verdict(sr.PC, 20, eq(r, d)) == "bay") for r in RATES}
    assert min(firsts) == 15 and max(firsts) == 30


def test_a_longer_bay_stop_moves_the_tipping_point_down():
    """'15 s in the lane against 20 s in the bay ties at fewer passengers than 15 s in both; 6 s beats 10 s at any load'"""
    assert sr.tipping_bus_load(sr.pair(0.3, 15, 20)) < sr.tipping_bus_load(eq(0.3, 15))
    assert all(sr.tipping_bus_load(sr.pair(r, 6, 10)) == "lane_always" for r in RATES)


def test_how_sure_we_are():
    """'Leaving out every seed whose bay run ended in contact changes the bus's delay by at most ... ; nothing was cut off'"""
    f = sr.facts("en")
    assert float(f["da_max"]) < 1.0 and float(f["db_max"]) < 10
    assert f["censored"] == "0"
    assert 1.5 < float(f["contact_pct"]) < 3.0 and 5 < float(f["offroad_pct"]) < 12


def test_the_field_check_numbers():
    """'a plausible mean, but no long tail' and 'about a third low'"""
    mt = sr.field()["merge_time"]["all_bay_runs"]
    assert 10 < mt["mean"] < 15 and mt["max"] < 52 and mt["n_over_30s"] <= 2
    assert 0.6 < sr.field()["entry_flow"]["flow_veh_per_h"] / 1900 < 0.7


OLD_SOURCE_MARKS = ("*נקרא*", "*סיכום בלבד*", "*מיד שנייה*", "*read*", "*Read*", "*summary only*", "*second-hand*",
                    ">נקרא<", ">נקרא בכתבה<", ">סיכום בלבד<", ">מיד שנייה<", ">read<", ">summary only<", ">second-hand<")


def test_sources_are_marked_only_where_they_were_not_checked_in_the_source():
    """Sources are not tagged by what we read: unmarked means checked in the source itself, and only the exceptions
    ('not checked against the source', 'cited by another source') carry a mark, explained once on the page."""
    pages = [CURRENT / lang / name for lang in ("en", "he") for name in ("FIELD_DATA.md", "RESULTS.md", "EXPLORER.md")]
    pages += [REPO_ROOT / "scripts" / "explorer" / f"{lang}.html" for lang in ("en", "he")]
    pages += [REPO_ROOT / "scripts" / "real_data_report_template.html"]
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for bad in OLD_SOURCE_MARKS:
            assert bad not in text, (page.name, bad)
    assert "לא אומת מול המקור" in (CURRENT / "he" / "FIELD_DATA.md").read_text(encoding="utf-8")
    assert "not checked against the source" in (CURRENT / "en" / "FIELD_DATA.md").read_text(encoding="utf-8").lower()
