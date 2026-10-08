#!/usr/bin/env python3
"""Acceptance test for a candidate brain against the measured v9 baseline.

Thresholds were fixed on 2026-10-06, before any engine-trained brain existed, from the
100-seed measurements of v9_best and v10_best (outputs/baseline_noise_*.json):

    v9_best   sigma 0: 100/100, mean 5.57 s, p95 6.4 s   sigma 0.15: 98/100, mean 5.43 s, p95 5.9 s
    v10_best  sigma 0: 100/100, mean 5.29 s, p95 5.8 s   sigma 0.15: 100/100, mean 5.28 s, p95 5.8 s

Time is measured from the end of boarding to fully merged, in the app engine, with the app's
default settings (scenario B, 0.4 cars/s, 50 cars, governor off).

Every run is also checked by busmerge.invariants; any physically impossible moment (braking beyond
9 m/s^2, backward motion, a position that does not follow from the speed, vehicle overlap) fails the
gate. A brain cannot pass while the simulation it runs in is cheating.

    python scripts/acceptance.py --brain models/ppo_bus_brain_exp7satv9_best.pth
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from busmerge.evaluation import evaluate_brain

SEEDS = 100
# noise sigma -> minimum merged episodes out of SEEDS
MIN_MERGED = {0.0: 100, 0.15: 98}
MAX_COLLISIONS = 0
MAX_MEAN_S = 6.0
MAX_P95_S = 7.0


def check(result: dict) -> list[tuple[str, bool, str]]:
    total = result["after_boarding"]["total_s"]
    sigma = result["noise_sigma"]
    physics = [
        (f"no {kind.replace('_', ' ')}", runs == 0,
         f"{runs}/{result['seeds']} runs" + (f", e.g. {result['physics_violation_examples'][kind]}" if runs else ""))
        for kind, runs in result["physics_violation_runs"].items()
    ]
    return physics + [
        (f"merged >= {MIN_MERGED[sigma]}/{SEEDS}", result["merged"] >= MIN_MERGED[sigma], f"{result['merged']}/{result['seeds']}"),
        (f"collisions <= {MAX_COLLISIONS}", result["collision"] <= MAX_COLLISIONS, str(result["collision"])),
        (f"mean total <= {MAX_MEAN_S} s", total["mean"] is not None and total["mean"] <= MAX_MEAN_S, str(total["mean"])),
        (f"p95 total <= {MAX_P95_S} s", total["p95"] is not None and total["p95"] <= MAX_P95_S, str(total["p95"])),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brain", required=True, type=Path)
    ap.add_argument("--seed-start", type=int, default=0,
                    help="first seed; use a range not used while developing/selecting the brain (e.g. 1000)")
    ap.add_argument("--strict-physics", action="store_true",
                    help="EXPERIMENTAL: evaluate with SimConfig.strict_physics (busmerge/safe_speed.py)")
    ap.add_argument("--out", type=Path, default=None, help="write the raw results as JSON")
    args = ap.parse_args()

    results, passed = [], True
    for sigma in MIN_MERGED:
        r = evaluate_brain(args.brain, SEEDS, sigma, traffic_rate=0.4, cars=50, seed_start=args.seed_start,
                           strict_physics=args.strict_physics)
        results.append(r)
        print(f"\n{args.brain.name}  noise sigma={sigma}  seeds {args.seed_start}..{args.seed_start + SEEDS - 1}")
        print(f"  traffic (report only): {r['traffic']}")
        for name, ok, value in check(r):
            print(f"  [{'PASS' if ok else 'FAIL'}] {name:26} measured {value}")
            passed &= ok
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=1))
    print("\nACCEPTANCE", "PASSED" if passed else "FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
