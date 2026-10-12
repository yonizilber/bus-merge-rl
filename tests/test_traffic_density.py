"""Traffic at every inflow setting: physically possible (#10), and as dense as requested (#17).

- **#10, physics sweep.** At every inflow the app offers in the tests (0.2-0.8 cars/s), a run with the
  default brain has no physically impossible moment. That means no braking or acceleration beyond the
  limits, negative speed, backward motion, position jump or extreme heading. Cars never overlap each
  other. Contact with the bus and the bus's road edges are the brain's outcomes, measured elsewhere.
  The nightly gate repeats this on 400 seeds.
- **#17, arrivals.** The car generator should deliver what is asked for: at least 90% of the requested
  arrival rate. It does not, at any setting (strict `xfail`, BUGS O20). An arrival is drawn only while
  the entry is clear (0.5 s since the last car and 15 m to it), and arrivals during a blocked entry are
  lost. Each car blocks the entry for about 1.5 s, so the delivered rate is about λ / (1 + 1.5·λ):
  80% at 0.2 cars/s, 71% at 0.4 (the app default), 46% at 0.8.
"""
import random

import numpy as np
import pytest

from busmerge.config import SimConfig
from busmerge.evaluation import APP_DEFAULTS, run_episode
from busmerge.invariants import check_invariants
from busmerge.paths import DEFAULT_BRAIN
from busmerge.simulation import SimulationEngine

IMPOSSIBLE = ("decel_over_limit", "accel_over_limit", "negative_speed", "backward_motion",
              "position_jump", "extreme_heading")


@pytest.mark.parametrize("traffic_rate", [0.2, 0.4, 0.6, 0.8])
@pytest.mark.parametrize("seed", [0, 1])
def test_no_physically_impossible_moment_at_any_inflow(traffic_rate, seed):
    cfg = SimConfig(**{**APP_DEFAULTS, "traffic_rate": traffic_rate, "total_cars_to_spawn": 30})
    df = run_episode("B", cfg, str(DEFAULT_BRAIN), governor_disabled=True, seed=seed).get_results()
    rep = check_invariants(df)
    found = {k: rep.counts[k] for k in IMPOSSIBLE if rep.counts[k]}
    assert not found, {k: rep.examples[k] for k in found}
    assert check_invariants(df[df["type"] == "Car"]).counts["overlap"] == 0, "cars overlapped each other"


def _achieved_arrival_rate(traffic_rate: float, seed: int, cars: int = 50) -> float:
    random.seed(seed)
    np.random.seed(seed)
    sim = SimulationEngine("B", SimConfig(traffic_rate=traffic_rate, total_cars_to_spawn=cars),
                           governor_disabled=True, load_brain=False)
    sim.record_frames = False
    sim.init_scenario()
    # Arrivals do not depend on the bus: send it on without stopping, so only the traffic is simulated.
    next(v for v in sim.vehicles if v.id == 999)._stop_served = True
    while sim.cars_spawned_count < cars and sim.time < 600.0:
        sim.step()
    return sim.cars_spawned_count / sim.last_spawn_time


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUGS O20: arrivals during a blocked entry are lost; delivered rate is about "
                          "lambda / (1 + 1.5 lambda): 80% at 0.2 cars/s, 71% at 0.4, 46% at 0.8")
@pytest.mark.parametrize("traffic_rate", [0.2, 0.4, 0.6, 0.8])
def test_the_car_generator_delivers_the_requested_inflow(traffic_rate):
    achieved = np.mean([_achieved_arrival_rate(traffic_rate, seed) for seed in range(6)])
    assert achieved >= 0.9 * traffic_rate, f"asked {traffic_rate} cars/s, got {achieved:.3f}"
