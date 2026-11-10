"""The results page (docs/current/*/RESULTS.md) says what the stored measurements say.

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

PAGES = {lang: (REPO_ROOT / "docs" / "current" / lang / "RESULTS.md").read_text(encoding="utf-8") for lang in ("en", "he")}
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
    for name in ("RESULTS.md", "RESEARCH.md", "README.md"):
        text = (REPO_ROOT / "docs" / "current" / lang / name).read_text(encoding="utf-8")
        for bad in ("50 passengers", "50 on the bus", "50 נוסעים", "50 באוטובוס", "The bus carries", "האוטובוס נושא 50"):
            assert bad not in text, (lang, name, bad)


@pytest.mark.parametrize("lang", ["en", "he"])
def test_the_page_embeds_the_explorer_and_links_the_field_report_and_the_figure(lang):
    text = PAGES[lang]
    assert "<!-- embed: explorer -->" in text and "(FIELD_REPORT.he.html)" in text
    assert f"media/stop_design_break_even_bus.{lang}.png" in text
    assert (REPO_ROOT / "docs" / "media" / f"stop_design_break_even_bus.{lang}.png").exists()
    assert (REPO_ROOT / "docs" / "tools" / f"stop_design_explorer.{lang}.html").exists()


def test_the_combined_summary_holds_both_experiments():
    """'two experiments, {{runs}} runs ... 150 to 300 seeds'"""
    prov = {p["experiment"]: p for p in D["provenance"]}
    assert D["runs"] == prov["stop_design_v1"]["runs_stored"] + prov["stop_design_v2"]["runs_stored"] == 19_500
    assert DWELLS == [0, 3, 6, 10, 15, 20, 30, 45] and RATES == [0.1, 0.2, 0.3, 0.4, 0.5]
    assert {eq(r, d)[0] for r in RATES for d in DWELLS} == {150, 300}
    assert prov["stop_design_v2"]["commit"].endswith("+uncommitted")       # "with uncommitted changes ... as its provenance says"


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
