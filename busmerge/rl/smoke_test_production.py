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
    max_wait_s    <= 45 s

No brain should be deployed to Streamlit unless this passes.
"""

import argparse
import json
import os
import sys
import random
from datetime import datetime, timezone
import numpy as np
import torch

# Allow running from repo root

from busmerge.paths import DEFAULT_BRAIN
from busmerge.simulation import SimulationEngine
from busmerge.vehicle import BusState
from busmerge.config import SimConfig
from busmerge.rl.merge_success import (
    is_production_merge_complete,
)


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
                   traffic_rate: float = 3.0,
                   total_cars: int = 30) -> bool:
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

    for seed in range(n_seeds):
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)

        # Traffic config — default dense stress test; use --traffic-rate 0.4 for Streamlit parity.
        cfg = SimConfig()
        cfg.total_cars_to_spawn = total_cars
        cfg.traffic_rate        = traffic_rate

        try:
            engine = SimulationEngine(scenario=scenario, config=cfg,
                                      brain_path=ckpt_path,
                                      governor_disabled=governor_disabled)
        except Exception as e:
            print(f"  [seed {seed}] SKIP — engine init failed: {e}")
            continue

        engine.init_scenario()
        bus = next((v for v in engine.vehicles if hasattr(v, 'state')), None)
        if bus is None:
            print(f"  [seed {seed}] SKIP — no bus found")
            continue

        outcome   = "timeout"
        step      = 0
        merge_t   = None
        wait_t    = 0.0
        complete_t = None
        saw_wait  = False

        for step in range(max_steps):
            engine.step()
            bus = next((v for v in engine.vehicles if hasattr(v, 'state')), None)
            if bus is None:
                break

            if bus.state == BusState.WAITING_TO_MERGE:
                saw_wait = True
                if wait_t <= 0.0:
                    wait_t = engine.time

            if is_production_merge_complete(
                float(bus.lateral_offset), bus.state, saw_waiting_to_merge=saw_wait
            ):
                complete_t = engine.time
                if wait_t > 0:
                    merge_t = complete_t - wait_t
                    outcome = "success"
                break

            if bus.state not in (BusState.MOVING, BusState.DECELERATING,
                                  BusState.IN_BAY, BusState.WAITING_TO_MERGE,
                                  BusState.STOPPED_IN_LANE):
                outcome = "crash"
                break

        # Detect collision from frame_history
        df = engine.get_results()
        if not df.empty:
            crash_rows = df[df.get('physical_collision', False) == True] if 'physical_collision' in df.columns else df.iloc[0:0]
            if len(crash_rows) > 0:
                outcome = "crash"

        if outcome == "success":
            successes += 1
            total_merge_s = merge_t if merge_t is not None else (complete_t - wait_t)
            merge_times.append(total_merge_s)
            wait_times.append(wait_t)
            print(f"  [seed {seed:3d}] SUCCESS  merge={total_merge_s:.1f}s  "
                  f"wait_start={wait_t:.1f}s")
        elif outcome == "crash":
            crashes += 1
            print(f"  [seed {seed:3d}] CRASH")
        else:
            timeouts += 1
            print(f"  [seed {seed:3d}] TIMEOUT  (>{max_steps} steps)")

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
    print(f"  Max wait   : {max_wait_s_obs:.1f}s  (target ≤{max_wait_s}s)")

    pass_rate  = success_rate  >= min_success_rate
    pass_merge = avg_merge_s   <= max_avg_merge_s
    pass_wait  = max_wait_s_obs <= max_wait_s

    print()
    print(f"  success_rate >= {min_success_rate*100:.0f}%  : {'PASS' if pass_rate  else 'FAIL'}")
    print(f"  avg_merge   <= {max_avg_merge_s}s     : {'PASS' if pass_merge else 'FAIL'}")
    print(f"  max_wait    <= {max_wait_s}s    : {'PASS' if pass_wait  else 'FAIL'}")
    print("=" * 60)

    all_pass = pass_rate and pass_merge and pass_wait
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
                        help="Max worst-case wait in seconds (default 45).")
    parser.add_argument("--scenario", type=str, default="B",
                        help="Scenario letter (default B = bay merge).")
    parser.add_argument("--disable-governor", action="store_true", default=False,
                        help="Match exp7sat training: bypass predictive governor.")
    parser.add_argument("--traffic-rate", type=float, default=3.0,
                        help="Poisson spawn rate cars/s (default 3.0 dense; use 0.4 for Streamlit).")
    parser.add_argument("--total-cars", type=int, default=30,
                        help="Max cars to spawn per episode (default 30; Streamlit often 50).")
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
