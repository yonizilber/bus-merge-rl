#!/usr/bin/env python3
"""How the bus's arrival at the stop differs between a bay (B) and the lane (A), measured in the simulation.

    python scripts/measure_stop_geometry.py [--seeds 40] [--workers 2]

For the same seed both designs give the bus the same entry speed and the same stop point, so the differences are
paired. Per run it records: the time from the start of braking until the bus stands (arrival), where it stands along
the road compared with the stop pole (300 m) and how far its side is from the pavement edge (the kerb in the lane,
the bay's back wall in the bay). The result is stored in results/experiments/stop_design_v2/stop_geometry.json and
feeds the "penalty for the bay" defaults of the explorer.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "experiments" / "stop_design_v2" / "stop_geometry.json"
STOP_POLE_X = 300.0
RATE, DWELL = 0.3, 6.0


def one(task: tuple) -> dict:
    import torch
    torch.set_num_threads(1)
    from busmerge.config import SimConfig
    from busmerge.evaluation import APP_DEFAULTS, run_episode
    from busmerge.geometry import BAY_WALL_Y, KERB_Y
    from busmerge.paths import DEFAULT_BRAIN
    scenario, seed = task
    cfg = SimConfig(**{**APP_DEFAULTS, "traffic_rate": RATE, "bus_dwell_time": DWELL, "arrival_seed": seed,
                       "arrival_window_s": 150.0})
    sim = run_episode(scenario, cfg, str(DEFAULT_BRAIN), governor_disabled=True, seed=seed, max_sim_time=400.0)
    bus = sim.get_results()
    bus = bus[bus["type"] == "Bus"].sort_values("time")
    state = bus["state"].astype(str)
    t_brake = float(bus.loc[state == "DECELERATING", "time"].min())
    stood = bus[state.isin(["IN_BAY", "STOPPED_IN_LANE"])]
    first = stood.iloc[0]
    edge = KERB_Y if scenario == "A" else BAY_WALL_Y
    return {"scenario": scenario, "seed": seed, "t_brake": t_brake, "t_stand": float(first["time"]),
            "stand_x": float(first["x"]), "gap_to_edge_m": float((first["lateral_offset"] - first["width"] / 2) - edge),
            "lateral_offset": float(first["lateral_offset"])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    tasks = [(s, 4000 + i) for i in range(args.seeds) for s in ("A", "B")]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(one, tasks))
    by = {(r["scenario"], r["seed"]): r for r in rows}
    seeds = sorted({r["seed"] for r in rows})
    arrive = {s: np.array([by[(s, k)]["t_stand"] - by[(s, k)]["t_brake"] for k in seeds]) for s in "AB"}
    pole = {s: np.array([abs(by[(s, k)]["stand_x"] - STOP_POLE_X) for k in seeds]) for s in "AB"}
    gap = {s: np.array([by[(s, k)]["gap_to_edge_m"] for k in seeds]) for s in "AB"}
    diff = arrive["B"] - arrive["A"]
    result = {
        "seeds": len(seeds), "rate": RATE, "dwell_s": DWELL,
        "arrival_time_from_braking_s": {"lane_mean": round(float(arrive["A"].mean()), 2), "bay_mean": round(float(arrive["B"].mean()), 2),
                                        "bay_minus_lane_mean": round(float(diff.mean()), 2), "bay_minus_lane_sd": round(float(diff.std(ddof=1)), 2),
                                        "bay_minus_lane_min": round(float(diff.min()), 2), "bay_minus_lane_max": round(float(diff.max()), 2)},
        "distance_from_stop_pole_m": {"lane_mean": round(float(pole["A"].mean()), 2), "bay_mean": round(float(pole["B"].mean()), 2)},
        "gap_between_bus_side_and_pavement_edge_m": {"lane_mean": round(float(gap["A"].mean()), 2), "bay_mean": round(float(gap["B"].mean()), 2),
                                                     "lane_sd": round(float(gap["A"].std(ddof=1)), 2), "bay_sd": round(float(gap["B"].std(ddof=1)), 2)},
        "note": "paired by seed: the same entry speed and stop point in both designs",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
