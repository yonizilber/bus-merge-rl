#!/usr/bin/env python3
"""Build the interactive explorer: which stop design is better under the conditions a visitor picks.

    python scripts/build_stop_design_explorer.py

Reads the stored runs of the stop-design experiment (outputs/experiments/stop_design_v1) and writes
docs/tools/stop_design_explorer.he.html. For every traffic rate and every pairing of a lane dwell time with a bay dwell
time (5 x 5 x 5 = 125 pairings, the same seed gives the same cars in both designs) the page carries what is needed to
rebuild the paired person-time difference for ANY occupancies in the browser:

    ΔPT = pax_bus · a + pax_car · b,   a = ΔT_bus (bay − lane, s),   b = ΔT_cars (bay − lane, s, summed over cars)

with the means of a and b and their variances and covariance over the 300 seeds (so the 95% interval is exact for the
mean, by the normal approximation, for any occupancy). Between the experiment's grid points the page interpolates
linearly; it never extrapolates. The field reference values are written in the template by hand, with their sources.
"""
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import analyze_stop_experiment as an  # noqa: E402
from busmerge.experiments.stop_design import paired_difference  # noqa: E402

DATA = REPO / "outputs" / "experiments" / "stop_design_v1"
TEMPLATE = REPO / "scripts" / "stop_design_explorer_template.html"
OUT = REPO / "docs" / "tools" / "stop_design_explorer.he.html"
HEAD = ('<!doctype html>\n<html lang="he" dir="rtl">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n')
RATES = (0.1, 0.2, 0.3, 0.4, 0.5)
DWELLS = (10, 15, 20, 30, 45)


def pairing_table(runs) -> dict:
    """{rate: {dwell_lane: {dwell_bay: [n, mean a, mean b, var a, var b, cov ab]}}} over the seeds."""
    table: dict = {}
    for lane in DWELLS:
        for bay in DWELLS:
            m = paired_difference(runs, 1.0, 1.0, dwell_lane=lane, dwell_bay=bay)
            m = m.assign(a=m["bus_travel_time_s_b"] - m["bus_travel_time_s_a"],
                         b=m["cars_travel_time_s_b"] - m["cars_travel_time_s_a"])
            for rate, g in m.groupby("traffic_rate"):
                cov = np.cov(g["a"], g["b"], ddof=1)
                table.setdefault(f"{rate:g}", {}).setdefault(str(lane), {})[str(bay)] = [
                    int(len(g)), round(float(g["a"].mean()), 4), round(float(g["b"].mean()), 4),
                    round(float(cov[0, 0]), 4), round(float(cov[1, 1]), 4), round(float(cov[0, 1]), 4)]
    return table


def side_tables(runs) -> dict:
    """What happens in each design on its own: the queue behind a bus stopped in the lane, the bay's merge time."""
    a = runs[runs.scenario == "A"].groupby(["traffic_rate", "dwell_s"])
    b = runs[runs.scenario == "B"].groupby(["traffic_rate", "dwell_s"])
    queue = a["queue_max_cars"].mean()
    merge = b["merge_time_s"].mean()
    return {"lane_queue_cars": {f"{r:g}": {str(d): round(float(queue[(r, d)]), 1) for d in DWELLS} for r in RATES},
            "bay_merge_s": {f"{r:g}": {str(d): round(float(merge[(r, d)]), 1) for d in DWELLS} for r in RATES}}


def main() -> None:
    runs, _ = an.load(DATA)
    payload = {"rates": list(RATES), "dwells": list(DWELLS), "pairs": pairing_table(runs), **side_tables(runs),
               "provenance": json.loads((DATA / "provenance.json").read_text(encoding="utf-8"))}
    payload["provenance"] = {k: payload["provenance"][k] for k in ("experiment", "commit", "brain_version", "date",
                                                                  "runs_stored")}
    page = TEMPLATE.read_text(encoding="utf-8")
    assert "/*DATA*/null" in page
    page = page.replace("/*DATA*/null", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HEAD + page.replace("<main>", "</head>\n<body>\n<main>", 1) + "\n</body>\n</html>\n", encoding="utf-8")
    print(f"written {OUT.relative_to(REPO)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
