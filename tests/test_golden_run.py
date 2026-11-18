"""Regression guard: fixed-seed simulations must reproduce their stored trajectories.

Every vehicle's (id, x, v, total_lat, state) is stored every 5 s of simulated time and compared within
``tests.golden_compare.ATOL`` (states, ids, step and row counts exactly), so any behavioural change in the simulation,
physics or policy inference shows up here, while the last bit of a float may differ between machines.
If a change is *intended* to alter behaviour, regenerate the golden file with
``python -m tests.test_golden_run --update`` and explain the change in the commit.
"""
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
from tests.golden_compare import mismatches

GOLDEN_FILE = Path(__file__).parent / "golden" / "golden_runs.json"
CASES = [("B", 0), ("B", 1), ("B", 2), ("A", 0), ("A", 1)]
MAX_STEPS = 1500  # 150 s of simulated time
CARS_PER_RUN = 20


SAMPLE_EVERY_S = 5.0


def _trajectory(df) -> dict:
    """{time: [[id, x, v, total_lat, state], ...]} every SAMPLE_EVERY_S seconds, vehicles in id order."""
    out = {}
    tenths = (df["time"].astype(float) * 10).round().astype(int)
    for t, frame in df[tenths % int(SAMPLE_EVERY_S * 10) == 0].groupby(tenths):
        frame = frame.sort_values("id")
        out[f"{t / 10:g}"] = [[str(r.id), round(float(r.x), 6), round(float(r.v), 6), round(float(r.total_lat), 6),
                               str(r.state)] for r in frame.itertuples()]
    return out


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
        "trajectory": _trajectory(df),
    }


@pytest.mark.parametrize("scenario,seed", CASES, ids=[f"{s}-{n}" for s, n in CASES])
def test_simulation_matches_golden(scenario, seed):
    expected = json.loads(GOLDEN_FILE.read_text())[f"{scenario}-{seed}"]
    diff = mismatches(run_case(scenario, seed), expected)
    assert not diff, diff[:10]


if __name__ == "__main__" and "--update" in sys.argv:
    results = {f"{s}-{n}": run_case(s, n) for s, n in CASES}
    GOLDEN_FILE.write_text(json.dumps(results, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"Wrote {GOLDEN_FILE}")


def test_the_golden_comparison_can_fail():
    """A car 1 cm off, a changed state or a missing vehicle is caught; a difference in the last bits of a float is not."""
    expected = json.loads(GOLDEN_FILE.read_text())["B-0"]
    t, rows = next(iter(expected["trajectory"].items()))
    for change in (lambda r: r[0].__setitem__(1, r[0][1] + 0.01), lambda r: r[0].__setitem__(4, "changed"), lambda r: r.pop()):
        actual = json.loads(json.dumps(expected))
        change(actual["trajectory"][t])
        assert mismatches(actual, expected), change
    actual = json.loads(json.dumps(expected))
    actual["trajectory"][t][0][1] += 1e-9
    actual["bus_final_x"] += 1e-9
    assert not mismatches(actual, expected)
