"""The bus's steering reaches its target line without overshooting it.

The old merge steering, atan2(lateral error, max(v, 5)), had no heading term: it carried the bus about
as far past its target as it started from it. The v9-v11 brains learned to rely on that overshoot
(docs/CASE_STUDY_REWARD_HACKING.md). These tests drive a bus with the production method
(`Vehicle.steer_toward`: pure pursuit, steering-rate limit, bicycle model) from a parallel start at
a distance from the line, over the speeds and steering rates each controller meets.

The 6 m pull-in look-ahead is not tested this way: it follows the gradual kerb line
(tests/test_bus_physics.py) and is not stable for a sudden 3.5 m step at speed (BUGS O16).
"""
import itertools

import numpy as np
import pytest

from busmerge.rl.merge_constants import BUS_LANE_LOOKAHEAD_M, BUS_MERGE_LOOKAHEAD_M
from busmerge.vehicle import CAR_PARAMS, Bus

DT = 0.1
MAX_OVERSHOOT = 0.05     # of the initial distance to the line
SETTLED_M = 0.05         # within this of the line counts as arrived
STARTS = (-3.5, -2.0, -0.5, 1.0)            # bus centre relative to the target line (m)
STEER_RATES = (18.0, 33.0)                  # the range a bus is drawn from (deg/s)

CONTROLLERS = {
    "merge": (BUS_MERGE_LOOKAHEAD_M, (1.0, 2.0, 5.0, 8.0), 60.0),   # look-ahead, speeds (m/s), arrival within (m)
    "lane": (BUS_LANE_LOOKAHEAD_M, (5.0, 10.0, 14.0), 90.0),
}


def _drive(lat0: float, speed: float, steer_rate: float, step) -> np.ndarray:
    """Lateral positions of a bus that starts parallel, lat0 from the line y = 0, at constant speed."""
    bus = Bus(999, 0.0, speed, CAR_PARAMS)
    bus.params.steer_rate_deg_per_s = steer_rate
    bus.lateral_offset = lat0
    lats = []
    for _ in range(int(300.0 / speed / DT)):     # 300 m of road
        step(bus)
        lats.append(bus.lateral_offset)
    return np.array(lats)


def _overshoot(lat0: float, lats: np.ndarray) -> float:
    """Furthest the bus went past the line, as a fraction of where it started."""
    return max(0.0, float((-np.sign(lat0) * lats).max())) / abs(lat0)


CASES = [(name, lat0, speed, rate) for name, (_, speeds, _) in CONTROLLERS.items()
         for lat0, speed, rate in itertools.product(STARTS, speeds, STEER_RATES)]


@pytest.mark.parametrize("name,lat0,speed,rate", CASES,
                         ids=[f"{n}-from{l:+.1f}m-{v:g}ms-rate{r:g}" for n, l, v, r in CASES])
def test_pure_pursuit_reaches_the_line_without_overshoot(name, lat0, speed, rate):
    look_ahead, _, arrive_within_m = CONTROLLERS[name]
    lats = _drive(lat0, speed, rate, lambda bus: bus.steer_toward(0.0, look_ahead, DT))
    assert _overshoot(lat0, lats) <= MAX_OVERSHOOT
    away = np.nonzero(np.abs(lats) > SETTLED_M)[0]
    arrived_after_m = (away[-1] + 1) * speed * DT if len(away) else 0.0
    assert arrived_after_m <= arrive_within_m


def test_the_old_merge_steering_fails_this_check():
    # The check must be able to fail: the steering that v9-v11 exploited overshoots by about the
    # whole distance it started from.
    def old_law(bus):
        max_steer = np.radians(bus.params.max_steer_angle_deg)
        bus.apply_steering(float(np.clip(np.arctan2(-bus.lateral_offset, max(bus.velocity, 5.0)),
                                         -max_steer, max_steer)), DT)
    lats = _drive(-3.5, 5.0, 25.0, old_law)
    assert _overshoot(-3.5, lats) > 0.5
