"""Every number in the text of the results page (docs/current/*/RESULTS.md) is what the stored measurement says.

The tables on that page are generated from results/experiments/stop_design_v1/summary.json. The sentences around them
state numbers too (how many cells the bay wins, the range of the bus's delay, the queue length), and a sentence that
drifts from the data is a bug, like a stale table. Each test below names the sentence it guards.
"""
import statistics

import pytest

from busmerge.results import stop_summary


@pytest.fixture(scope="module")
def summary():
    return stop_summary()


@pytest.fixture(scope="module")
def cells(summary):
    return {(c["traffic_rate"], c["dwell_s"]): c for c in summary["cells"]}


def _winner(c):
    return "bay" if c["delta_pt_ci_high"] < 0 else "lane" if c["delta_pt_ci_low"] > 0 else "tie"


def test_the_design_is_25_cells_of_300_pairs_each_and_nothing_was_cut_off(summary, cells):
    assert len(cells) == 25 and {c["pairs"] for c in cells.values()} == {300}      # "15,000 runs ... 300 seeds"
    assert sum(c["censored_runs"] for c in cells.values()) == 0                    # "nothing was cut off"
    assert summary["provenance"]["commit"] == "fa5ee4c"                           # "measured at commit fa5ee4c"


def test_what_the_bay_costs_the_bus(cells):
    delays = [c["delta_bus_time_s"] for c in cells.values()]
    assert 5.2 < min(delays) < 5.4 and 10.4 < max(delays) < 10.6                  # "5 to 10.5 s longer, in every cell"
    assert 6.9 < statistics.mean(delays) < 7.2                                    # "about 7 s times 50 ... six person-minutes"
    assert 11.0 <= min(c["bay_merge_time_s"] for c in cells.values()) and max(c["bay_merge_time_s"] for c in cells.values()) <= 13.5
    assert 5.5 < 7.0 * 50 / 60 < 6.0                                              # "some six person-minutes"


def test_what_the_bay_buys_the_cars(cells):
    queues = [c["lane_queue_max_cars"] for c in cells.values()]
    assert min(queues) < 1.5 and max(queues) > 20                                 # "a single car ... more than twenty cars"
    assert max(c["lane_entry_wait_max_s"] for c in cells.values()) > 60           # "averages more than a minute in the worst cell"
    assert -46 < cells[(0.5, 45)]["delta_cars_time_s"] / 60 < -45                 # "about 45 vehicle-minutes"
    slower = sorted(k for k, c in cells.items() if c["delta_cars_time_s"] > 0)
    assert slower == [(0.3, 10), (0.4, 10), (0.5, 10)]                            # "short stop and 0.3 cars/s or more: the bay makes the cars slower"


def test_who_wins_where(cells):
    wins = {w: sorted(k for k, c in cells.items() if _winner(c) == w) for w in ("bay", "lane", "tie")}
    assert (len(wins["bay"]), len(wins["lane"]), len(wins["tie"])) == (10, 13, 2)  # "the bay wins in 10, the lane in 13, 2 undecided"
    assert wins["tie"] == [(0.1, 45), (0.5, 15)]
    assert all(_winner(cells[(r, 10)]) == "lane" for r in (0.1, 0.2, 0.3, 0.4, 0.5))   # "at 10 s the lane wins at every inflow"
    assert all(_winner(cells[(r, d)]) == "bay" for d in (30, 45) for r in (0.2, 0.3, 0.4, 0.5))   # "30 and 45 s: the bay from 0.2"
    assert [_winner(cells[(r, 20)]) for r in (0.1, 0.2, 0.3, 0.4, 0.5)] == ["lane", "lane", "lane", "bay", "bay"]
    assert [_winner(cells[(r, 15)]) for r in (0.1, 0.2, 0.3, 0.4, 0.5)] == ["lane", "lane", "lane", "lane", "tie"]
    assert 45 < -cells[(0.5, 45)]["delta_pt_mean"] / 60 < 46                       # "about 46 person-minutes in every run"


def test_a_quicker_lane_stop(summary):
    pairs = {(p["traffic_rate"], p["dwell_lane_s"], p["dwell_bay_s"]): p for p in summary["dwell_pairs"]}
    rates = (0.1, 0.2, 0.3, 0.4, 0.5)
    for lane, bay in ((10, 15), (15, 20), (20, 30)):                              # "wins at every inflow ... (10, 15, 20 s in the lane)"
        assert all(_winner(pairs[(r, lane, bay)]) == "lane" for r in rates), (lane, bay)
    assert [_winner(pairs[(r, 30, 45)]) for r in rates] == ["lane", "lane", "lane", "bay", "bay"]   # "only from 0.4 cars/s"


def test_who_is_in_the_car(cells):
    for rate in (0.3, 0.4, 0.5):
        assert cells[(rate, 45)]["break_even_pax_car"] < 1 / 3                     # "under a third of a person per car"
    assert [round(cells[(r, 45)]["break_even_pax_car"], 2) for r in (0.3, 0.4, 0.5)] == [0.30, 0.23, 0.19]
    assert all(cells[(r, 10)]["break_even_pax_car"] != cells[(r, 10)]["break_even_pax_car"] for r in (0.3, 0.4, 0.5))   # "lane always"
    assert cells[(0.1, 10)]["break_even_pax_car"] > 3 and cells[(0.1, 15)]["break_even_pax_car"] > 3   # "above 3 people per car"


def test_how_sure_we_are(summary, cells):
    assert max((c["delta_pt_ci_high"] - c["delta_pt_ci_low"]) / 2 for c in cells.values()) < 57.5   # "at most about ±57 person-seconds"
    assert summary["contact_sensitivity_max_person_s"] < 12.5                      # "no more than 12 person-seconds"
    assert 0.53 < cells[(0.2, 30)]["bay_better_share"] < 0.55                      # "ahead in only 54% of the seeds"
    assert cells[(0.4, 45)]["bay_better_share"] == cells[(0.5, 45)]["bay_better_share"] == 1.0   # "ahead in all 300"
    assert 1.5 < statistics.mean(c["bay_contact_pct"] for c in cells.values()) < 1.7           # "1.6% of the pull-outs"
    assert 7.5 < statistics.mean(c["bay_off_road_pct"] for c in cells.values()) < 8.5          # "about 8%"


def test_the_story_pages_exist_in_both_languages_and_use_the_generated_blocks():
    from busmerge.paths import REPO_ROOT
    for lang in ("en", "he"):
        text = (REPO_ROOT / "docs/current" / lang / "RESULTS.md").read_text(encoding="utf-8")
        suffix = "_he" if lang == "he" else ""
        for name in ("stop_delta_grid", "stop_bus_delay", "stop_cars_time", "stop_pairs", "stop_break_even"):
            assert f"<!-- results:{name}{suffix} " in text, (lang, name)
        assert f"media/stop_design_v1_delta_pt_vs_rate.{lang}.png" in text
        assert (REPO_ROOT / "docs" / "media" / f"stop_design_v1_delta_pt_vs_rate.{lang}.png").exists()
