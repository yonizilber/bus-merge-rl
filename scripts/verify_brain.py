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

from busmerge.verification import run_seed

BRAIN_FAILURES = ("collision", "stuck_waiting", "never_waited")


def _save_result(args, rows: list[dict]) -> None:
    """Store the run in results/ with where it came from (busmerge.results)."""
    import datetime
    import subprocess
    from busmerge.results import save
    from busmerge.rl.merge_success import PRODUCTION_MERGE_LATERAL_THRESHOLD
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True).stdout.strip()
    path = save(args.save, rows, {
        "label": args.label or args.save, "brain": Path(args.brain).name,
        "seeds": [args.seed_start, args.seed_start + len(rows) - 1], "traffic_rate": args.traffic_rate,
        "cars": args.cars, "merge_threshold_m": PRODUCTION_MERGE_LATERAL_THRESHOLD,
        "commit": commit + ("+uncommitted" if dirty else ""), "date": datetime.date.today().isoformat(),
    })
    print(f"saved {path}")


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
    ap.add_argument("--save", metavar="NAME", help="also store the run in results/NAME (published numbers)")
    ap.add_argument("--label", help="label of the run in published tables (with --save)")
    args = ap.parse_args()

    seeds = range(args.seed_start, args.seed_start + args.seeds)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(run_seed, [(args.brain, s, args.traffic_rate, args.cars) for s in seeds], chunksize=4))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=1))
    if args.save:
        _save_result(args, rows)

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
