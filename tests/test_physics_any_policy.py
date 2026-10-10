"""Physics must stay possible whatever the merging policy does.

A random driver replaces the brain while merging: steer and gas are drawn at random and held for
0.5-3 s, either anywhere in [-1, 1] or only at the extremes (full in / out, full gas / brake). Running
off the road or hitting a car are legitimate outcomes for such a driver and are not checked here. What
must never happen, for any vehicle, is a physically impossible moment: braking or accelerating beyond
the limits, a negative speed, moving backwards, a position that does not follow from the speed, or an
extreme heading.
"""
import random

import numpy as np
import pytest

from busmerge.config import SimConfig
from busmerge.invariants import check_invariants
from busmerge.simulation import SimulationEngine

IMPOSSIBLE = ("decel_over_limit", "accel_over_limit", "negative_speed", "backward_motion",
              "position_jump", "extreme_heading")


def _random_driver_run(seed: int, traffic_rate: float, extremes: bool):
    random.seed(seed)
    np.random.seed(seed)
    policy = np.random.default_rng(1000 + seed)
    sim = SimulationEngine("B", SimConfig(traffic_rate=traffic_rate, total_cars_to_spawn=30),
                           governor_disabled=True, load_brain=False)
    sim.init_scenario()
    hold = 0
    while not sim.all_vehicles_finished() and sim.time < 200.0:
        if hold <= 0:
            draw = (lambda: float(policy.choice([-1.0, 1.0]))) if extremes else (lambda: float(policy.uniform(-1, 1)))
            sim.external_action = (draw(), draw())   # used only while the bus is merging
            hold = int(policy.integers(5, 30))
        hold -= 1
        sim.step()
    return sim.get_results()


@pytest.mark.parametrize("seed,traffic_rate,extremes", [(0, 0.4, False), (1, 0.8, False), (2, 0.4, True), (3, 0.8, True)],
                         ids=["uniform-0.4", "uniform-0.8", "extremes-0.4", "extremes-0.8"])
def test_no_physically_impossible_moment_under_a_random_merging_policy(seed, traffic_rate, extremes):
    df = _random_driver_run(seed, traffic_rate, extremes)
    rep = check_invariants(df)
    found = {k: rep.counts[k] for k in IMPOSSIBLE if rep.counts[k]}
    assert not found, {k: rep.examples[k] for k in found}
    assert (df["type"] == "Car").any(), "the run must include traffic"
