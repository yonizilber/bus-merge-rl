"""The cars' steering controller does not reach its target line cleanly (BUGS O21).

Cars steer by ``atan2(lateral_error, max(v, 5))``, the law the bus used before the case study's fix:
it has no heading term, so the heading integrates the steering and the position integrates the
heading, with nothing damping it. The bus now steers by pure pursuit (`Vehicle.steer_toward`),
which does the same step with a few percent of overshoot (tests/test_steering_controller.py).

In v1.0 the only sideways move a car makes is the 0.5 m nudge that makes room for a merging bus, which
hides the defect (and causes most of the cars crossing the centre line, BUGS O10/O14). These tests
drive a car through that very nudge with the production code (`Vehicle.update_physics`).

- **Strict `xfail` (the honest requirement):** the step overshoots by at most 5% and settles within 5 s.
  It fails today because the car overshoots by about 100% and never settles. It turns red the day the
  cars steer by pure pursuit; then delete the pinning test below and the `xfail` mark.
- **Pinning test:** records what the controller does today, so the failure above is understood.
- **Contrast:** the bus's pure pursuit meets the same requirement on the same step, so the requirement is
  not too strict.
"""
import copy

import numpy as np
import pytest

from busmerge.vehicle import CAR_PARAMS, Bus, Vehicle

DT = 0.1
STEP_M = 0.5                  # the nudge: MAX_NUDGE (0.5 m) x politeness (1.0)
MAX_OVERSHOOT = 0.05          # of the step
SETTLED_FRACTION = 0.05       # within this share of the step counts as arrived
SETTLE_WITHIN_S = 5.0
SPEEDS = (10.0, 13.0)         # m/s, constant (the car's top speed is set equal, so the IDM does not accelerate it)


def _car(speed: float) -> Vehicle:
    params = copy.deepcopy(CAR_PARAMS)
    params.max_speed = speed
    params.politeness_factor = 1.0
    car = Vehicle(1, 0.0, speed, params)
    car.is_squeezing = True       # the car is making room for a bus: lat_target = 0.5 m x politeness
    return car


def _production_step_response(speed: float, seconds: float = 30.0) -> tuple[np.ndarray, float]:
    """Sideways positions of a car through its production update, and the peak heading in degrees."""
    car, bus = _car(speed), Bus(999, 1e6, 0.0, CAR_PARAMS)       # a bus far ahead keeps the car squeezing
    lats, peak = [], 0.0
    for _ in range(int(seconds / DT)):
        car.update_physics(DT, None, bus)
        lats.append(car.lateral_offset)
        peak = max(peak, abs(np.degrees(car.heading_angle)))
    assert car.lat_target == pytest.approx(STEP_M), "the scenario must drive the car to a 0.5 m target"
    return np.array(lats), peak


def _pure_pursuit_step_response(speed: float, look_ahead: float = 18.0, seconds: float = 30.0) -> np.ndarray:
    car = _car(speed)
    lats = []
    for _ in range(int(seconds / DT)):
        car.steer_toward(STEP_M, look_ahead, DT)
        lats.append(car.lateral_offset)
    return np.array(lats)


def _overshoot(lats: np.ndarray) -> float:
    return max(0.0, float(lats.max()) - STEP_M) / STEP_M


def _settling_time_s(lats: np.ndarray) -> float:
    """Time after which the position stays within 5% of the step; infinity if it never does."""
    away = np.nonzero(np.abs(lats - STEP_M) > SETTLED_FRACTION * STEP_M)[0]
    if len(away) == 0:
        return 0.0
    return float("inf") if away[-1] == len(lats) - 1 else (away[-1] + 1) * DT


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUGS O21: the cars' steering law has no heading term and overshoots every target")
def test_a_car_reaches_its_nudge_target_without_overshoot_and_settles():
    for speed in SPEEDS:
        lats, _ = _production_step_response(speed)
        assert _overshoot(lats) <= MAX_OVERSHOOT, f"{speed:g} m/s: overshoot {_overshoot(lats):.0%}"
        assert _settling_time_s(lats) <= SETTLE_WITHIN_S, f"{speed:g} m/s: settles after {_settling_time_s(lats)} s"


@pytest.mark.parametrize("speed", SPEEDS)
def test_today_the_car_overshoots_its_target_by_about_100_percent_and_never_settles(speed):
    # Pins the measured behaviour (2026-10-25). When the cars are fixed this test fails: delete it with the xfail.
    lats, _ = _production_step_response(speed)
    assert _overshoot(lats) > 0.9, f"overshoot {_overshoot(lats):.0%}"
    assert _settling_time_s(lats) > SETTLE_WITHIN_S


def test_the_requirement_is_met_by_the_bus_controller_on_the_same_step():
    # The check must be able to pass: pure pursuit on the same 0.5 m step, same speeds.
    for speed in SPEEDS:
        lats = _pure_pursuit_step_response(speed)
        assert _overshoot(lats) <= MAX_OVERSHOOT, f"{speed:g} m/s: overshoot {_overshoot(lats):.1%}"
        assert _settling_time_s(lats) <= SETTLE_WITHIN_S, f"{speed:g} m/s: settles after {_settling_time_s(lats)} s"
