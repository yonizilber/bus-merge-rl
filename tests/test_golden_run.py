"""Regression guard: fixed-seed simulations must reproduce stored fingerprints.

The fingerprint hashes every vehicle's (time, id, x, v, total_lat, state) per frame,
so any behavioural change in the simulation, physics or policy inference shows up here.
If a change is *intended* to alter behaviour, regenerate the golden file with
``python tests/test_golden_run.py --update`` and explain the change in the commit.
"""
import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

from busmerge.config import SimConfig
from busmerge.simulation import SimulationEngine
from tests.brains import GOLDEN_BRAIN

GOLDEN_FILE = Path(__file__).parent / "golden" / "golden_runs.json"
CASES = [("B", 0), ("B", 1), ("B", 2), ("A", 0), ("A", 1)]
MAX_STEPS = 1500  # 150 s of simulated time
CARS_PER_RUN = 20


def _fingerprint(df) -> str:
    snap = df[["time", "id", "x", "v", "total_lat", "state"]].copy()
    for col in ("time", "x", "v", "total_lat"):
        snap[col] = snap[col].astype(float).round(6)
    return hashlib.sha256(snap.to_csv(index=False).encode()).hexdigest()[:16]


def run_case(scenario: str, seed: int) -> dict:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    sim = SimulationEngine(scenario=scenario, config=SimConfig(total_cars_to_spawn=CARS_PER_RUN),
                           brain_path=str(GOLDEN_BRAIN))
    sim.init_scenario()
    steps = 0
    while not sim.all_vehicles_finished() and steps < MAX_STEPS:
        sim.step()
        steps += 1
    df = sim.get_results()
    bus = df[df["type"] == "Bus"]
    return {
        "steps": steps,
        "rows": len(df),
        "bus_final_x": round(float(bus["x"].iloc[-1]), 6) if len(bus) else None,
        "fingerprint": _fingerprint(df),
    }


@pytest.mark.parametrize("scenario,seed", CASES, ids=[f"{s}-{n}" for s, n in CASES])
def test_simulation_matches_golden(scenario, seed):
    expected = json.loads(GOLDEN_FILE.read_text())[f"{scenario}-{seed}"]
    assert run_case(scenario, seed) == expected


if __name__ == "__main__" and "--update" in sys.argv:
    results = {f"{s}-{n}": run_case(s, n) for s, n in CASES}
    GOLDEN_FILE.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
    print(f"Wrote {GOLDEN_FILE}")
