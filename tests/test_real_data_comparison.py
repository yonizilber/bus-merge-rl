"""The simulation's numbers quoted in docs/REAL_DATA_COMPARISON.md are the ones in the stored comparison.

The field numbers in that document are quoted by hand from named sources; the simulation's own numbers come from
scripts/compare_with_real_data.py and are stored in results/experiments/stop_design_v1/real_data_comparison.json.
"""
import json

import pytest

from busmerge.paths import REPO_ROOT

DOC = (REPO_ROOT / "docs" / "REAL_DATA_COMPARISON.md").read_text(encoding="utf-8")
DATA = json.loads((REPO_ROOT / "results" / "experiments" / "stop_design_v1" / "real_data_comparison.json").read_text())


def test_merge_time_numbers():
    m = DATA["merge_time"]["all_bay_runs"]
    assert m["n"] == 7500
    for text in (f"mean {m['mean']} s", f"median {m['median']} s", f"under {m['p90']} s", f"under {m['p99']} s",
                 f"{m['max']} s", f"{m['share_over_20s']:.1%} above 20 s"):
        assert text in DOC, text
    assert m["share_over_30s"] == 0.0 and "none above 30 s" in DOC


def test_entry_flow_numbers():
    e = DATA["entry_flow"]
    assert f"{e['flow_cars_per_s']:.2f} cars/s" in DOC and f"{e['flow_veh_per_h']:,} per hour" in DOC
    assert f"{e['headway_median_s']} s apart (mean {e['headway_mean_s']:.1f} s)" in DOC


@pytest.mark.parametrize("key,row", [
    ("car 1.2, bus 50", "| 1.2 | 50 (default) |"), ("car 1.7, bus 50", "| 1.7 | 50 |"),
    ("car 1.2, bus 20", "| 1.2 | 20 |"), ("car 1.7, bus 20", "| 1.7 | 20 |"),
    ("car 1.2, bus 10.7", "| 1.2 | 10.7 |"), ("car 1.7, bus 10.7", "| 1.7 | 10.7 |")])
def test_verdict_counts_by_occupancy(key, row):
    v = DATA["verdict_by_occupancy"][key]
    assert f"{row} {v['bay']} | {v['lane']} | {v['tie']} |" in DOC


def test_queue_and_per_car_tables():
    q = DATA["lane_queue"]["mean_max_queue_cars"]
    for dwell, rates in ((10, ("0.1", "0.3", "0.5")), (15, ("0.1", "0.3", "0.5")), (20, ("0.1", "0.3", "0.5")),
                         (45, ("0.1", "0.3", "0.5"))):
        assert "| %d | %s |" % (dwell, " | ".join(str(q[str(dwell)][r]) for r in rates)) in DOC
    c = DATA["lane_minus_bay_s_per_car"]
    for dwell in (10, 15, 20, 30, 45):
        cells = " | ".join(str(c[str(dwell)][r]).replace("-", "−") for r in ("0.1", "0.3", "0.5"))
        assert f"| {dwell} | {cells} |" in DOC
