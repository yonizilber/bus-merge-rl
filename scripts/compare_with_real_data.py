#!/usr/bin/env python3
"""The simulation's side of the comparison with published field data (docs/REAL_DATA_COMPARISON.md).

    python scripts/compare_with_real_data.py            # reads outputs/experiments/stop_design_v1, prints and writes
                                                         # results/experiments/stop_design_v1/real_data_comparison.json

Every number the comparison quotes from *this* simulation comes from here, computed from the stored runs of the
stop-design experiment (the same data as RESULTS): how long the bus takes to merge back, how long a queue builds behind
a bus stopped in the lane, how many cars the entry lets in, and how the verdict changes with the occupancies. The field
numbers are quoted by hand in the document, each with its source.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import analyze_stop_experiment as an  # noqa: E402

DATA_DIRS = [REPO / "outputs" / "experiments" / n for n in ("stop_design_v1", "stop_design_v2")]
OUT = REPO / "results" / "experiments" / "stop_design_v1" / "real_data_comparison.json"
RATES = (0.1, 0.2, 0.3, 0.4, 0.5)
DWELLS: tuple = ()          # the dwell times of the stored runs, set in main()
# (cars, bus): the Israeli range for cars (1.2 in the news, 1.44-1.52 in the surveys; the page's default is the middle,
# 1.35) with a rough 20 passengers on a city bus, then the US averages (FHWA/NHTS 2017: 1.7 per car; FHWA/NTD 2016: 10.7
# per bus) and the first experiment's own default (1.2 and 50).
OCCUPANCIES = ((1.2, 20.0), (1.35, 20.0), (1.5, 20.0), (1.7, 10.7), (1.2, 50.0))


def merge_time(runs: pd.DataFrame) -> dict:
    """End of boarding to fully merged (busmerge.evaluation.merge_timeline), over the bay runs that completed it."""
    b = runs[runs.scenario == "B"]
    t = b["merge_time_s"].dropna()

    def stats(s: pd.Series) -> dict:
        return {"n": int(len(s)), "mean": round(float(s.mean()), 1), "median": round(float(s.median()), 1),
                "p90": round(float(s.quantile(0.9)), 1), "p99": round(float(s.quantile(0.99)), 1),
                "max": round(float(s.max()), 1), "share_over_20s": round(float((s > 20).mean()), 4),
                "share_over_30s": round(float((s > 30).mean()), 4)}
    return {"all_bay_runs": stats(t),
            "by_rate": {str(r): stats(b[b.traffic_rate == r]["merge_time_s"].dropna()) for r in RATES},
            "outcomes": {k: int(v) for k, v in b["outcome"].value_counts().items()},
            "no_timeline": int(b["merge_time_s"].isna().sum())}


def bay_cost(runs: pd.DataFrame) -> dict:
    """What the bay costs the bus (bay minus lane trip time, s), over the cells with the same dwell time in both designs."""
    d = an.cell_table(runs, 1.35, 20.0)["delta_bus_time_s"]
    return {"min": round(float(d.min()), 1), "max": round(float(d.max()), 1), "mean": round(float(d.mean()), 1), "cells": int(len(d))}


def lane_queue(runs: pd.DataFrame) -> dict:
    """Largest number of stopped cars behind the bus while it stands in the lane (scenario A)."""
    a = runs[runs.scenario == "A"]
    grid = a.pivot_table(index="dwell_s", columns="traffic_rate", values="queue_max_cars", aggfunc="mean")
    return {"mean_max_queue_cars": {str(d): {str(r): round(float(grid.loc[d, r]), 1) for r in RATES} for d in DWELLS},
            "share_of_runs_with_a_queue": {str(r): round(float((a[a.traffic_rate == r].queue_max_cars >= 1).mean()), 3)
                                           for r in RATES}}


def entry_flow(trips: pd.DataFrame) -> dict:
    """How fast the entry lets cars in once a queue stands at it (scenario A, 0.5 cars/s, 45 s: the entry is blocked)."""
    cars = trips[trips["type"] == "Car"]
    key = cars["run"].str.split("|", expand=True)
    cars = cars[(key[0] == "A") & (key[1].astype(float) == 0.5) & (key[2].astype(float) == 45)]
    gaps = []
    for _, d in cars.groupby("run"):
        d = d.sort_values("entered_t")
        gaps += list(np.diff(d.entered_t.values)[d.entry_wait_s.values[1:] > 1.0])
    gaps = np.array(gaps)
    return {"entries_measured": int(len(gaps)), "headway_median_s": round(float(np.median(gaps)), 2),
            "headway_mean_s": round(float(gaps.mean()), 2), "flow_cars_per_s": round(float(1 / gaps.mean()), 3),
            "flow_veh_per_h": int(round(3600 / gaps.mean()))}


def verdict_by_occupancy(runs: pd.DataFrame) -> dict:
    out = {}
    for pax_car, pax_bus in OCCUPANCIES:
        t = an.cell_table(runs, pax_car, pax_bus)
        t["verdict"] = np.where(t.delta_pt_ci_high < 0, "bay", np.where(t.delta_pt_ci_low > 0, "lane", "tie"))
        counts = t.verdict.value_counts().to_dict()
        grid = t.pivot(index="dwell_s", columns="traffic_rate", values="verdict")
        out[f"car {pax_car:g}, bus {pax_bus:g}"] = {
            "bay": int(counts.get("bay", 0)), "lane": int(counts.get("lane", 0)), "tie": int(counts.get("tie", 0)),
            "grid": {str(d): {str(r): grid.loc[d, r] for r in RATES} for d in DWELLS}}
    return out


def delay_per_car(runs: pd.DataFrame) -> dict:
    """Extra travel time per car in the lane design compared with the bay, seconds per car (the same cars)."""
    cells = an.cell_table(runs, 1.2, 50.0)
    cells["lane_minus_bay_s_per_car"] = -cells.delta_cars_time_s / cells.cars_per_run
    grid = cells.pivot(index="dwell_s", columns="traffic_rate", values="lane_minus_bay_s_per_car")
    return {str(d): {str(r): round(float(grid.loc[d, r]), 1) for r in RATES} for d in DWELLS}


def main() -> None:
    loaded = [an.load(d) for d in DATA_DIRS]
    runs = pd.concat([r for r, _ in loaded], ignore_index=True)
    trips = pd.concat([t for _, t in loaded], ignore_index=True)
    global DWELLS
    DWELLS = tuple(sorted(int(d) for d in runs["dwell_s"].unique()))
    result = {"source": f"outputs/experiments/stop_design_v1 and stop_design_v2 ({len(runs):,} runs; commits in their provenance.json)", "dwells_s": list(DWELLS),
              "bay_cost_s": bay_cost(runs), "merge_time": merge_time(runs), "lane_queue": lane_queue(runs), "entry_flow": entry_flow(trips),
              "verdict_by_occupancy": verdict_by_occupancy(runs), "lane_minus_bay_s_per_car": delay_per_car(runs)}
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    m = result["merge_time"]["all_bay_runs"]
    print(f"merge time, all {m['n']} bay runs with a timeline: mean {m['mean']} median {m['median']} p90 {m['p90']} "
          f"p99 {m['p99']} max {m['max']}; share over 20 s {m['share_over_20s']:.1%}, over 30 s {m['share_over_30s']:.1%}")
    print("entry flow when queued:", result["entry_flow"])
    for k, v in result["verdict_by_occupancy"].items():
        print(f"{k}: bay {v['bay']}, lane {v['lane']}, tie {v['tie']}")
    print(f"written {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
