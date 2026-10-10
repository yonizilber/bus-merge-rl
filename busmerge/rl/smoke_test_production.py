"""
smoke_test_production.py — Production acceptance harness.

Loads the promoted checkpoint via simulation.py::SimulationEngine and runs
scenario B (bus bay -> merge) under DENSE traffic for N seeds. Reports merge
time, success rate, and maximum wait.

Usage:
    python -m busmerge.rl.smoke_test_production [--ckpt PATH] [--seeds N] [--max-merge-s S]

Acceptance criteria (exit 0 = PASS, exit 1 = FAIL):
    success_rate  >= 90 %
    avg_merge_s   <= 30 s
    max_wait_s    <= 45 s   (longest time from end of boarding to merged)

No brain should be deployed to Streamlit unless this passes.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
import numpy as np

# Allow running from repo root

from busmerge.paths import DEFAULT_BRAIN
from busmerge.evaluation import classify_outcome, run_episode
from busmerge.invariants import check_invariants
from busmerge.config import SimConfig


def smoke_sidecar_path(ckpt_path: str) -> str:
    return ckpt_path.replace(".pth", ".smoke.json")


def write_smoke_sidecar(ckpt_path: str, report: dict) -> None:
    path = smoke_sidecar_path(ckpt_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


def run_smoke_test(ckpt_path: str, n_seeds: int, max_steps: int,
                   min_success_rate: float, max_avg_merge_s: float,
                   max_wait_s: float, scenario: str = "B",
                   write_sidecar: bool = True,
                   governor_disabled: bool = False,
                   traffic_rate: float = 0.4,
                   total_cars: int = 50) -> bool:
    print("=" * 60)
    print("PRODUCTION SMOKE TEST")
    print(f"  Checkpoint : {ckpt_path}")
    print(f"  Seeds      : {n_seeds}")
    print(f"  Scenario   : {scenario}")
    print(f"  Traffic    : {traffic_rate} cars/s, {total_cars} cars max")
    print(f"  Criteria   : success>={min_success_rate*100:.0f}%  "
          f"avg_merge<={max_avg_merge_s}s  max_wait<={max_wait_s}s")
    print(f"  Governor   : {'OFF (shield only)' if governor_disabled else 'ON'}")
    print("=" * 60)

    successes = 0
    timeouts  = 0
    crashes   = 0
    merge_times = []
    wait_times  = []

    physics_bad_runs = 0
    physics_kinds: set[str] = set()
    for seed in range(n_seeds):
        # Defaults equal the Streamlit sidebar defaults (0.4 cars/s, 50 cars).
        cfg = SimConfig(total_cars_to_spawn=total_cars, traffic_rate=traffic_rate)
        try:
            engine = run_episode(
                scenario, cfg, ckpt_path,
                governor_disabled=governor_disabled,
                seed=seed,
                max_sim_time=max_steps * 0.1,  # engine dt is 0.1 s
            )
        except Exception as e:
            print(f"  [seed {seed}] SKIP — engine init failed: {e}")
            continue

        df = engine.get_results()
        outcome, meta = classify_outcome(df)
        inv = check_invariants(df)
        if inv.total:
            physics_bad_runs += 1
            physics_kinds.update(k for k, n in inv.counts.items() if n)
        if outcome == "merged":
            successes += 1
            merge_times.append(meta["merge_s"])
            wait_times.append(meta["merge_s"])  # time from end of boarding to merged
            print(f"  [seed {seed:3d}] SUCCESS  merge={meta['merge_s']:.1f}s  "
                  f"boarding ended at {meta['boarding_ended_at_s']:.1f}s")
        elif outcome == "collision":
            crashes += 1
            print(f"  [seed {seed:3d}] CRASH")
        else:
            timeouts += 1
            print(f"  [seed {seed:3d}] {outcome.upper()}  (>{max_steps} steps)")

    total = successes + timeouts + crashes
    if total == 0:
        print("No episodes completed — check engine/checkpoint.")
        return False

    success_rate  = successes / total
    avg_merge_s   = float(np.mean(merge_times)) if merge_times else float('inf')
    max_wait_s_obs = float(max(wait_times)) if wait_times else float('inf')

    print()
    print("=" * 60)
    print(f"  Successes  : {successes}/{total}  ({success_rate*100:.1f}%)")
    print(f"  Crashes    : {crashes}")
    print(f"  Timeouts   : {timeouts}")
    print(f"  Avg merge  : {avg_merge_s:.1f}s  (target ≤{max_avg_merge_s}s)")
    print(f"  Max wait   : {max_wait_s_obs:.1f}s after boarding  (target ≤{max_wait_s}s)")

    pass_rate  = success_rate  >= min_success_rate
    pass_merge = avg_merge_s   <= max_avg_merge_s
    pass_wait  = max_wait_s_obs <= max_wait_s

    print()
    print(f"  success_rate >= {min_success_rate*100:.0f}%  : {'PASS' if pass_rate  else 'FAIL'}")
    print(f"  avg_merge   <= {max_avg_merge_s}s     : {'PASS' if pass_merge else 'FAIL'}")
    print(f"  max_wait    <= {max_wait_s}s    : {'PASS' if pass_wait  else 'FAIL'}")
    print("=" * 60)

    pass_physics = physics_bad_runs == 0
    print(f"  physics checks (busmerge.invariants): {'PASS' if pass_physics else 'FAIL'}"
          f"  ({physics_bad_runs}/{total} runs with violations: {', '.join(sorted(physics_kinds)) or '-'})")
    all_pass = pass_rate and pass_merge and pass_wait and pass_physics
    print(f"\nSMOKE TEST {'PASSED' if all_pass else 'FAILED'}")

    if write_sidecar:
        write_smoke_sidecar(ckpt_path, {
            "checkpoint": os.path.basename(ckpt_path),
            "passed": all_pass,
            "success_rate": success_rate,
            "successes": successes,
            "total": total,
            "crashes": crashes,
            "timeouts": timeouts,
            "avg_merge_s": None if avg_merge_s == float("inf") else avg_merge_s,
            "max_wait_s": None if max_wait_s_obs == float("inf") else max_wait_s_obs,
            "physics_violation_runs": physics_bad_runs,
            "physics_violation_kinds": sorted(physics_kinds),
            "n_seeds": n_seeds,
            "scenario": scenario,
            "tested_at": datetime.now(timezone.utc).isoformat(),
        })

    return all_pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ckpt", type=str, default=None,
                        help="Path to .pth checkpoint. Defaults to runtime checkpoint.")
    parser.add_argument("--seeds", type=int, default=20,
                        help="Number of seeds to test (default 20).")
    parser.add_argument("--max-steps", type=int, default=3000,
                        help="Max simulation steps per episode (default 3000 = 300 s).")
    parser.add_argument("--min-success", type=float, default=0.90,
                        help="Minimum success rate (default 0.90).")
    parser.add_argument("--max-avg-merge", type=float, default=30.0,
                        help="Max average merge time in seconds (default 30).")
    parser.add_argument("--max-wait", type=float, default=45.0,
                        help="Max time from end of boarding to merged, worst seed (default 45 s).")
    parser.add_argument("--scenario", type=str, default="B",
                        help="Scenario letter (default B = bay merge).")
    parser.add_argument("--disable-governor", action="store_true", default=False,
                        help="Match exp7sat training: bypass predictive governor.")
    parser.add_argument("--traffic-rate", type=float, default=0.4,
                        help="Poisson spawn rate cars/s (default 0.4 = Streamlit default).")
    parser.add_argument("--total-cars", type=int, default=50,
                        help="Max cars to spawn per episode (default 50 = Streamlit default).")
    args = parser.parse_args()

    # Resolve checkpoint
    ckpt = args.ckpt
    if ckpt is None:
        ckpt = str(DEFAULT_BRAIN)

    passed = run_smoke_test(
        ckpt_path       = ckpt,
        n_seeds         = args.seeds,
        max_steps       = args.max_steps,
        min_success_rate= args.min_success,
        max_avg_merge_s = args.max_avg_merge,
        max_wait_s      = args.max_wait,
        scenario        = args.scenario,
        governor_disabled=args.disable_governor,
        traffic_rate    = args.traffic_rate,
        total_cars      = args.total_cars,
    )
    sys.exit(0 if passed else 1)
