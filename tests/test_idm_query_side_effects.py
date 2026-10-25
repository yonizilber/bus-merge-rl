"""Asking the IDM for an acceleration must not change the vehicle (BUGS O22).

A lane-change model such as MOBIL asks "what would my acceleration be in another lane, or behind another
leader?" without braking the car in the current frame. That needs a pure query. The IDM functions are not
pure: `_idm_accel_core` writes ``is_squeezing`` (directly and through the squeeze hysteresis),
`_calculate_idm_accel` also advances ``last_applied_yield`` (the rate limiter of the yield blend), and
`update_physics` advances ``reaction_timer``. The engine asks once per car per frame, which hides it.

The scenario: a car 20 m behind a bus that is half way out of its bay.

- **Strict `xfail` (the honest requirement):** asking twice gives the same acceleration and leaves the
  squeeze flag and the yield limiter as they were. Fails today. It turns red the day the query and the
  commit are separated; then delete the pinning test below and the `xfail` mark.
- **Pinning test:** records every side effect today, so the failure above is understood.
"""
import copy

import pytest

from busmerge.rl.traffic_leaders import vehicle_leader_state
from busmerge.vehicle import CAR_PARAMS, Bus, BusState, Vehicle

DT = 0.1


def _scene():
    bus = Bus(999, 300.0, 0.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -1.2           # about half out of the bay: presence 0.51
    bus._merge_progress = 0.65
    car = Vehicle(1, 280.0, 10.0, copy.deepcopy(CAR_PARAMS))
    return car, bus, vehicle_leader_state(bus)


def _state(car: Vehicle) -> tuple:
    return (car.is_squeezing, round(car.last_applied_yield, 6), car.reaction_timer)


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUGS O22: the IDM acceleration functions change is_squeezing and last_applied_yield")
def test_asking_for_the_acceleration_twice_changes_nothing():
    car, bus, leader = _scene()
    before = _state(car)
    first = car._calculate_idm_accel(leader, bus, dt=DT)
    second = car._calculate_idm_accel(leader, bus, dt=DT)
    assert _state(car) == before, f"state changed by a query: {before} -> {_state(car)}"
    assert first == second, f"the same question gave {first} and then {second}"


def test_today_the_idm_functions_change_the_squeeze_flag_the_yield_limiter_and_the_reaction_timer():
    # Pins the measured side effects (2026-10-25). When they are removed this test fails: delete it with the xfail.
    car, bus, leader = _scene()
    assert not car.is_squeezing
    car._idm_accel_core(leader, bus)
    assert car.is_squeezing, "_idm_accel_core writes is_squeezing"

    car, bus, leader = _scene()
    first = car._calculate_idm_accel(leader, bus, dt=DT)
    limiter_after_first = car.last_applied_yield
    second = car._calculate_idm_accel(leader, bus, dt=DT)
    assert car.last_applied_yield > limiter_after_first > 0.0, "_calculate_idm_accel advances the yield limiter"
    assert second != pytest.approx(first), "so the same question gets a different answer the second time"

    car, bus, leader = _scene()
    car.reaction_timer = 0.3
    car.update_physics(DT, leader, bus)
    assert car.reaction_timer != 0.3, "update_physics advances the reaction timer"
