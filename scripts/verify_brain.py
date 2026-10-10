#!/usr/bin/env python3
"""Large-scale verification of one brain under the app's default settings.

Every run is checked by busmerge.invariants with no positions or angles clamped. For each seed the
script records, independently:
  * the merge outcome (merged / collision / stuck / never waited), judged without the road edges;
  * the road-edge anomalies of the bus (off the road = below the kerb or bay wall; over the centre
    line) and the stage of the run in which each first happened;
  * every other physics violation.
A run is a strict success only if it merged with none of the above.

    python scripts/verify_brain.py --brain models/ppo_bus_brain_v13.pth --seeds 1000 --seed-start 2000
Every seed can be replayed in the app: tick "Fixed random seed", enter the seed, and set the same
sidebar "Inflow (cars/sec)" and "Total Cars to Sim" (defaults 0.4 and 50).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

BRAIN_FAILURES = ("collision", "stuck_waiting", "never_waited")


def _run(args: tuple[str, int, float, int]) -> dict:
    brain, seed, traffic_rate, cars = args
    import torch
    torch.set_num_threads(1)
    from busmerge.config import SimConfig
    from busmerge.evaluation import APP_DEFAULTS, classify_outcome, merge_timeline, run_episode
    from busmerge.invariants import bus_contact_times, bus_edge_times, check_invariants, edge_masks

    from busmerge.traffic_metrics import traffic_metrics
    cfg = SimConfig(**{**APP_DEFAULTS, "traffic_rate": traffic_rate, "total_cars_to_spawn": cars})
    df = run_episode("B", cfg, brain, governor_disabled=True, seed=seed).get_results()
    outcome, meta = classify_outcome(df)
    inv = check_invariants(df)
    bus = df[df["type"] == "Bus"].set_index("time")["state"]
    off_road, over_centre = bus_edge_times(df)

    # Merge outcome judged without the road edges: what the brain did with the traffic.
    if bus_contact_times(df) or ("physical_collision" in df and df.loc[df["type"] == "Bus", "physical_collision"].any()):
        merge_outcome = "collision"
    elif outcome in ("off_road", "over_centre_line"):
        tl = merge_timeline(df)
        merge_outcome = "merged" if tl else "stuck_waiting"
    else:
        merge_outcome = outcome
    timeline = merge_timeline(df) if merge_outcome == "merged" else None
    # Report only: when the whole bus body is first inside the lane after boarding ends (whatever the
    # "merged" criterion says), and the highest lateral position it reaches while merging.
    merging = df[(df["type"] == "Bus") & (df["state"] == "WAITING_TO_MERGE")]
    in_lane_s, max_lateral = None, None
    if not merging.empty:
        below, _ = _edge_excess_lane(merging)
        if (below <= 0).any():
            in_lane_s = round(float(merging["time"].to_numpy()[(below <= 0).argmax()] - merging["time"].iloc[0]), 1)
        max_lateral = round(float(merging["lateral_offset"].max()), 3)
    cars = df[df["type"] == "Car"]
    car_below, car_above = edge_masks(cars)
    other = {k: n for k, n in inv.counts.items()
             if n and k not in ("overlap", "off_road", "over_centre_line")}   # bus geometry is reported above
    car_overlap = check_invariants(cars).counts["overlap"]
    if car_overlap:
        other["car_car_overlap"] = car_overlap
    return {
        "seed": seed,
        "strict_outcome": outcome,
        "merge_outcome": merge_outcome,
        "merge_total_s": timeline["total_s"] if timeline else None,
        "off_road_stage": _where(df, off_road[0]) if off_road else "",
        "over_centre_stage": str(bus.get(over_centre[0], "")) if over_centre else "",
        "first_off_road_s": off_road[0] if off_road else None,
        "first_over_centre_s": over_centre[0] if over_centre else None,
        "car_off_road": int(car_below.any() or car_above.any()),
        "car_edge": ("kerb" if car_below.any() else "") + ("+" if car_below.any() and car_above.any() else "")
                    + ("centre line" if car_above.any() else ""),
        "car_max_over_centre_m": _max_over_centre(cars) if car_above.any() else 0.0,
        "other_violations": other,
        "first_contact_s": meta.get("first_contact_s"),
        "body_in_lane_s": in_lane_s,
        "traffic": traffic_metrics(df),
        "max_lateral_merging_m": max_lateral,
    }


def _edge_excess_lane(rows):
    """How far each row's body reaches below the lane's kerb (the bay does not count as lane)."""
    import numpy as np
    from busmerge.geometry import KERB_Y, body_corners_xy
    _, ys = body_corners_xy(rows["x"].to_numpy(dtype=float), rows["total_lat"].to_numpy(dtype=float),
                            rows["length"].to_numpy(dtype=float), rows["width"].to_numpy(dtype=float),
                            np.radians(rows["heading_deg"].to_numpy(dtype=float)))
    return KERB_Y - ys.min(axis=1), None


def _where(df, t: float) -> str:
    """Stage of the run at the first off-road frame, with entering/leaving the bay told apart."""
    from busmerge.rl.merge_constants import BAY_FLAT_END_X, BAY_FLAT_START_X
    b = df[(df["type"] == "Bus") & (df["time"] == t)].iloc[0]
    if b["state"] == "DECELERATING" and b["x"] - b["length"] < BAY_FLAT_START_X and b["x"] < BAY_FLAT_START_X + 5:
        return "pulling in: kerb before the bay"
    if b["state"] in ("DECELERATING", "IN_BAY") and b["x"] > BAY_FLAT_END_X:
        return "stopped past the end of the bay"
    return str(b["state"])


def _max_over_centre(cars) -> float:
    from busmerge.invariants import _edge_excess
    return round(float(_edge_excess(cars)[1].max()), 2)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brain", required=True)
    ap.add_argument("--seeds", type=int, default=1000)
    ap.add_argument("--seed-start", type=int, default=2000)
    ap.add_argument("--traffic-rate", type=float, default=0.4, help="car arrivals per second (app default 0.4)")
    ap.add_argument("--cars", type=int, default=50, help="cars per run (app default 50)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--out", type=Path, default=Path("outputs/verify_brain.json"))
    args = ap.parse_args()

    seeds = range(args.seed_start, args.seed_start + args.seeds)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(_run, [(args.brain, s, args.traffic_rate, args.cars) for s in seeds], chunksize=4))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=1))

    n = len(rows)
    def rate(k: int) -> str:
        lo, hi = wilson(k, n)
        return f"{k:4d} / {n}  = {100 * k / n:5.1f}%   (95% CI {100 * lo:.1f}-{100 * hi:.1f}%)"

    strict_success = sum(r["strict_outcome"] == "merged" and not r["other_violations"] for r in rows)
    print(f"\n{Path(args.brain).name}  seeds {args.seed_start}..{args.seed_start + n - 1}  "
          f"traffic {args.traffic_rate} cars/s, {args.cars} cars (app defaults otherwise)\n")
    near = [r["traffic"]["cars_near_bus_at_merge_start"] for r in rows if r["traffic"]["cars_near_bus_at_merge_start"] == r["traffic"]["cars_near_bus_at_merge_start"]]
    flow = [r["traffic"]["flow_veh_per_min"] for r in rows if r["traffic"]["flow_veh_per_min"] == r["traffic"]["flow_veh_per_min"]]
    if near and flow:
        print(f"Traffic actually present: {statistics.mean(near):.2f} cars within 60 m of the bus when boarding ends; "
              f"flow past the stop {statistics.mean(flow):.1f} cars/min\n")
    print("Strict (merged, no contact, never off the road or over the centre line, no other violation):")
    print("  success          ", rate(strict_success))
    print("\nMerge outcome judged on the traffic only (road edges ignored):")
    for k in ("merged", "collision", "stuck_waiting", "never_waited"):
        print(f"  {k:16} ", rate(sum(r['merge_outcome'] == k for r in rows)))
    print("\nRoad-edge anomalies of the bus (first occurrence, by stage):")
    for key, label in (("off_road_stage", "off the road (kerb / bay wall)"), ("over_centre_stage", "over the centre line")):
        stages: dict[str, int] = {}
        for r in rows:
            if r[key]:
                stages[r[key]] = stages.get(r[key], 0) + 1
        print(f"  {label:32} {rate(sum(1 for r in rows if r[key]))}   by stage: {stages}")
    other: dict[str, int] = {}
    for r in rows:
        for k in r["other_violations"]:
            other[k] = other.get(k, 0) + 1
    print(f"\nOther physics violations (runs): {other or 'none'}")
    car_runs = [r for r in rows if r["car_off_road"]]
    edges: dict[str, int] = {}
    for r in car_runs:
        edges[r["car_edge"]] = edges.get(r["car_edge"], 0) + 1
    print(f"Runs where a car crossed a road edge: {rate(len(car_runs))}   by edge: {edges}"
          + (f"   worst over the centre line: {max(r['car_max_over_centre_m'] for r in car_runs):.2f} m" if car_runs else ""))

    in_lane = [r["body_in_lane_s"] for r in rows if r["body_in_lane_s"] is not None]
    print(f"\nReport only (not a pass criterion): whole bus inside the lane after boarding in {rate(len(in_lane))}"
          + (f"; time to it median {statistics.median(in_lane):.1f} s, p95 {sorted(in_lane)[int(0.95 * (len(in_lane) - 1))]:.1f} s" if in_lane else ""))
    lat = [r["max_lateral_merging_m"] for r in rows if r["max_lateral_merging_m"] is not None]
    if lat:
        from busmerge.rl.merge_success import PRODUCTION_MERGE_LATERAL_THRESHOLD
        print(f"Highest lateral position while merging: median {statistics.median(lat):.2f} m "
              f"(merged needs >= {PRODUCTION_MERGE_LATERAL_THRESHOLD:.2f} m)")
    times = [r["merge_total_s"] for r in rows if r["merge_total_s"] is not None]
    if times:
        print(f"Time from end of boarding to merged: mean {statistics.mean(times):.2f} s, p95 {sorted(times)[int(0.95 * (len(times) - 1))]:.2f} s")
    print("\nSeeds to watch in the app (Fixed random seed = seed, defaults otherwise):")
    shown = 0
    for kind in BRAIN_FAILURES:
        for r in rows:
            if r["merge_outcome"] == kind and shown < 10:
                print(f"  seed {r['seed']}: {kind}" + (f", first contact at t={r['first_contact_s']:.1f}s" if r["first_contact_s"] else ""))
                shown += 1


if __name__ == "__main__":
    main()
