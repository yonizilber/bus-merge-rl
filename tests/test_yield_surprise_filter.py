#!/usr/bin/env python3
"""Surprise Filter (yield slew-rate) — IN_BAY → WAITING must not cliff-brake via Y."""


from busmerge.vehicle import Vehicle, Bus, BusState, CAR_PARAMS, MAX_YIELD_SLEW_RATE
from busmerge.rl.traffic_leaders import resolve_car_leader


def _leader(car, bus):
    vehicles = sorted([bus, car], key=lambda v: v.position, reverse=True)
    idx = vehicles.index(car)
    leader, _ = resolve_car_leader(vehicles, idx, bus)
    return leader


def test_yield_slew_caps_first_frame_idm():
    """Raw Y may jump high; applied Y / IDM blend must move at most MAX_YIELD_SLEW_RATE*dt.

    Note: bumper kinematics may still cap approach speed once the bus is leader —
    that is a separate path from the yield Surprise Filter under test here.
    """
    bus = Bus(0, 300.0, 0.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus._merge_progress = 0.35  # material merge — not early bay-waiting
    bus.lateral_offset = -2.0
    bus.heading_angle = 0.0

    # ~6.5 m rear gap — same regime as telemetry cliff (~frame 149→150)
    car = Vehicle(5, 300.0 - 11.0 - 6.5, 13.5, CAR_PARAMS)
    car.last_applied_yield = 0.0
    dt = 0.1
    max_step = MAX_YIELD_SLEW_RATE * dt

    raw = car._merge_yield_factor(bus)
    assert raw > 0.5, f"expected large raw yield at close gap, got {raw:.3f}"

    leader = _leader(car, bus)
    car.reaction_timer = 0.0
    a = car._calculate_idm_accel(leader, bus, dt=dt)
    applied = car.last_applied_yield
    assert abs(applied - max_step) < 1e-9, (
        f"first-frame applied yield {applied:.4f} != max_step {max_step:.4f}"
    )
    # With Y=0.05, free-road + tiny bus blend must not reach emergency levels.
    assert a > -2.0, f"rate-limited IDM accel too harsh: {a:.3f}"


def test_yield_ramps_to_one_in_about_two_seconds():
    bus = Bus(0, 300.0, 0.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus._merge_progress = 0.2
    bus.lateral_offset = -2.5

    car = Vehicle(5, 300.0 - 11.0 - 8.0, 12.0, CAR_PARAMS)
    car.last_applied_yield = 0.0
    dt = 0.1
    for _ in range(20):  # 2.0 s — enough to reach raw Y ≤ 1.0
        leader = _leader(car, bus)
        car.reaction_timer = 0.0
        car._calculate_idm_accel(leader, bus, dt=dt)

    raw = car._merge_yield_factor(bus)
    assert car.last_applied_yield >= min(0.95, raw) - 1e-6, (
        f"after 2s expected applied≈raw ({raw:.3f}), got {car.last_applied_yield:.3f}"
    )
    assert abs(car.last_applied_yield - min(1.0, raw)) < 1e-6


def test_decrease_also_rate_limited():
    car = Vehicle(1, 100.0, 10.0, CAR_PARAMS)
    car.last_applied_yield = 1.0
    applied = car._rate_limit_yield(0.0, dt=0.1)
    assert abs(applied - 0.95) < 1e-9


def test_full_physics_tracks_slew_state():
    """update_physics must update last_applied_yield (not leave it stuck at 0)."""
    bus = Bus(0, 300.0, 0.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus._merge_progress = 0.35
    bus.lateral_offset = -2.0

    car = Vehicle(5, 280.0, 10.0, CAR_PARAMS)  # larger gap → softer bumper
    car.last_applied_yield = 0.0
    car.reaction_timer = 0.0
    for i in range(5):
        leader = _leader(car, bus)
        car.reaction_timer = 0.0
        car.update_physics(0.1, leader, bus=bus)
    assert car.last_applied_yield >= 0.24 - 1e-3  # 5 * 0.05 slew steps toward raw


if __name__ == "__main__":
    test_yield_slew_caps_first_frame_idm()
    test_yield_ramps_to_one_in_about_two_seconds()
    test_decrease_also_rate_limited()
    test_full_physics_tracks_slew_state()
    print("PASS: Surprise Filter yield slew-rate")
