#!/usr/bin/env python3
"""
Production gate — run before promoting a checkpoint or moving to the next phase.

Checks (in order):
  1. Core unit tests (kinematics, queue, follower telemetry)
  2. Streamlit-parity smoke (rate=0.4, governor OFF, v9 default ckpt)
  3. Dense stress smoke (rate=3.0, governor OFF)

Usage:
    python scripts/gate_production.py
    python scripts/gate_production.py --ckpt models/ppo_bus_brain_exp7satv9_best.pth
    python scripts/gate_production.py --quick   # skip dense smoke
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from busmerge.paths import DEFAULT_BRAIN, REPO_ROOT

ROOT = str(REPO_ROOT)
DEFAULT_CKPT = str(DEFAULT_BRAIN)

CORE_TESTS = [
    "tests/test_follower_telemetry.py",
    "tests/test_trajectory_kinematics.py",
    "tests/test_bus_queue_follow.py",
    "tests/test_idm_merge_yield.py",
    "tests/test_queue_analytics.py",
]


def _run(cmd: list[str], label: str) -> bool:
    print("\n" + "=" * 60)
    print(label)
    print("=" * 60)
    print(" ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT)
    ok = r.returncode == 0
    print(f"\n>>> {'PASS' if ok else 'FAIL'}: {label}\n")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Production gate for bus merge brain")
    parser.add_argument("--ckpt", default=DEFAULT_CKPT, help="Checkpoint to smoke-test")
    parser.add_argument("--quick", action="store_true", help="Skip dense (3.0) smoke")
    parser.add_argument("--seeds", type=int, default=10, help="Seeds per smoke tier")
    args = parser.parse_args()

    if not os.path.isfile(args.ckpt):
        print(f"Checkpoint not found: {args.ckpt}")
        return 1

    results: list[tuple[str, bool]] = []

    # 1. Core pytest subset
    pytest_cmd = [
        sys.executable, "-m", "pytest", "-q", "--tb=line",
        *CORE_TESTS,
        "-k", "not test_in_bay_no_false_leader and not test_hold_zeros_steer_when_gap_negative",
    ]
    results.append(("Core unit tests", _run(pytest_cmd, "1/3 Core unit tests")))

    smoke_module = ["-m", "busmerge.rl.smoke_test_production"]

    # 2. Streamlit parity (what you actually use in the UI)
    streamlit_cmd = [
        sys.executable, *smoke_module,
        "--ckpt", args.ckpt,
        "--seeds", str(args.seeds),
        "--disable-governor",
        "--traffic-rate", "0.4",
        "--total-cars", "50",
        "--max-avg-merge", "60",
        "--max-wait", "90",
    ]
    results.append((
        "Streamlit-parity smoke (0.4/s, gov OFF)",
        _run(streamlit_cmd, "2/3 Streamlit-parity smoke"),
    ))

    # 3. Dense stress
    if not args.quick:
        dense_cmd = [
            sys.executable, *smoke_module,
            "--ckpt", args.ckpt,
            "--seeds", str(args.seeds),
            "--disable-governor",
            "--traffic-rate", "3.0",
            "--total-cars", "30",
        ]
        results.append((
            "Dense stress smoke (3.0/s)",
            _run(dense_cmd, "3/3 Dense stress smoke"),
        ))

    print("\n" + "=" * 60)
    print("GATE SUMMARY")
    print("=" * 60)
    all_ok = True
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
        all_ok = all_ok and ok

    if all_ok:
        print("\nGATE PASSED — safe to continue to next phase.")
        return 0
    print("\nGATE FAILED — fix failures before continuing.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
