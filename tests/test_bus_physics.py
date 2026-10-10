"""The bus pulls into the bay along the drawn kerb and stops in it by physics alone.

Runs the app engine itself (no brain is needed before the merge): the bus must stay on the road
(exact check, including the kerb corners), arrive at its stop point at bay depth and parallel to the
kerb, with a continuous heading, and nothing may move while it is stopped.
"""
import random

import numpy as np
import pytest

from busmerge.config import SimConfig
from busmerge.evaluation import APP_DEFAULTS
from busmerge.invariants import check_invariants
from busmerge.rl.merge_constants import BAY_DEPTH, BAY_FLAT_END_X, BAY_FLAT_START_X, BUS_ALIGN_HEADING_DEG
from busmerge.simulation import SimulationEngine
from busmerge.vehicle import BusState


def _pull_in(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    sim = SimulationEngine(scenario="B", config=SimConfig(**APP_DEFAULTS), governor_disabled=True,
                           load_brain=False)
    sim.external_action = (-1.0, 0.0)   # only used if the run reached the merge
    sim.init_scenario()
    bus = next(v for v in sim.vehicles if v.id == 999)
    while bus.state != BusState.IN_BAY and sim.time < 90.0:
        sim.step()
    for _ in range(20):                 # 2 s stopped in the bay
        sim.step()
    return sim, bus


@pytest.mark.parametrize("seed", range(5))
def test_bus_pulls_into_the_bay_on_the_road_and_parallel(seed):
    sim, bus = _pull_in(seed)
    df = sim.get_results()
    b = df[df["type"] == "Bus"]

    assert bus.state == BusState.IN_BAY
    assert BAY_FLAT_START_X + bus.params.length <= bus.position <= BAY_FLAT_END_X
    assert -0.5 <= bus.target_stop_x - bus.position <= 0.5
    assert abs(bus.lateral_offset - BAY_DEPTH) < 0.1
    assert abs(np.degrees(bus.heading_angle)) <= BUS_ALIGN_HEADING_DEG

    rep = check_invariants(b)
    assert rep.total == 0, rep.examples
    assert b["heading_deg"].diff().abs().max() < 2.0
    stopped = b[b["state"] == "IN_BAY"]
    assert stopped["x"].nunique() == 1 and stopped["heading_deg"].nunique() == 1
