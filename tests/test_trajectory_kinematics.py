#!/usr/bin/env python3
"""
Trajectory / location kinematics tests — catch car teleport and bus jitter.

Run:  python3 test_trajectory_kinematics.py

These complement test_idm_merge_yield.py (yield logic) by checking that
vehicle x-positions evolve smoothly when a car follows a merging bus.
"""
import sys
import numpy as np


from busmerge.vehicle import Vehicle, Bus, BusState, CAR_PARAMS
from busmerge.rl.traffic_leaders import resolve_car_leader, vehicle_leader_state, bus_rear_bumper_x
from busmerge.safe_speed import leader_max_follower_front
from busmerge.rl.merge_yield import bus_gap_to_car_front

MAX_BACKWARD_STEP_M = 0.0    # cars must never move backward on the road
MIN_GAP_M = CAR_PARAMS.min_gap


def _rear_gap(bus, car):
    return bus_gap_to_car_front(bus, car)


def _step_pair(bus, car, dt=0.1):
    vehicles = sorted([bus, car], key=lambda v: v.position, reverse=True)
    idx = vehicles.index(car)
    leader, _ = resolve_car_leader(vehicles, idx, bus)
    car.reaction_timer = 0.0
    car.update_physics(dt, leader, bus=bus)


def assert_smooth_trajectory(name, bus_x, car_x, car_vs=None, max_back=MAX_BACKWARD_STEP_M):
    """Cars never reverse: position non-decreasing, velocity >= 0."""
    for i in range(1, len(car_x)):
        d = car_x[i] - car_x[i - 1]
        assert d >= -max_back - 1e-6, (
            f"{name} car backward step {i}: x {car_x[i-1]:.2f} -> {car_x[i]:.2f} (Δ={d:.2f})"
        )
    if car_vs is not None:
        for i, v in enumerate(car_vs):
            assert v >= -1e-6, f"{name} car reverse velocity step {i}: v={v:.3f}"
    for i in range(1, len(bus_x)):
        d = bus_x[i] - bus_x[i - 1]
        assert d >= -2.1 * 0.1 - 1e-6, (
            f"{name} bus teleport step {i}: x {bus_x[i-1]:.2f} -> {bus_x[i]:.2f}"
        )


def test_yaw_oscillation_no_car_teleport():
    """
    Bus heading swings 5°–17° (projected length jumps) while creeping forward.
    Car #4 scenario: follower must not snap backward.
    """
    bus = Bus(999, 308.0, 0.4, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.2
    bus._merge_progress = 0.30
    car = Vehicle(4, 292.0, 9.0, CAR_PARAMS)

    bus_x, car_x, car_vs, gaps = [], [], [], []
    headings = np.linspace(5.0, 17.0, 40).tolist() + np.linspace(17.0, 8.0, 40).tolist()
    for deg in headings:
        bus.heading_angle = np.radians(deg)
        bus.position += 0.04
        _step_pair(bus, car)
        bus_x.append(bus.position)
        car_x.append(car.position)
        car_vs.append(car.velocity)
        gaps.append(_rear_gap(bus, car))

    assert_smooth_trajectory("yaw_oscillation", bus_x, car_x, car_vs)
    assert car_x[-1] >= car_x[0] - 0.5, "car should end near or ahead of start, not far behind"
    print(
        f"  PASS  yaw_oscillation  car {car_x[0]:.1f}->{car_x[-1]:.1f}m  "
        f"gap {gaps[0]:.1f}->{gaps[-1]:.1f}m  bus {bus_x[0]:.1f}->{bus_x[-1]:.1f}m"
    )


def test_car4_merge_hold_locations():
    """
    Streamlit-like layout: bus ~308 m merging, car #4 ~292 m approaching/holding.
    Assert final hold respects min_gap and no backward step > 25 cm.
    """
    bus = Bus(999, 308.0, 0.5, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.0
    bus.heading_angle = np.radians(12.0)
    bus._merge_progress = 0.35
    car = Vehicle(4, 292.0, 10.0, CAR_PARAMS)

    bus_x, car_x, car_vs = [], [], []
    for step in range(150):
        bus.heading_angle = np.radians(10.0 + 7.0 * np.sin(step * 0.15))
        bus.position += 0.03
        bus.lateral_offset = min(0.0, -2.0 + step * 0.012)
        bus._merge_progress = float(np.clip((bus.lateral_offset + 3.5) / 3.5, 0, 1))
        _step_pair(bus, car)
        bus_x.append(round(bus.position, 3))
        car_x.append(round(car.position, 3))
        car_vs.append(car.velocity)

    assert_smooth_trajectory("car4_merge_hold", bus_x, car_x, car_vs)
    leader = vehicle_leader_state(bus)
    max_front = leader_max_follower_front(leader, MIN_GAP_M)
    assert car.position <= max_front + 0.06, (
        f"car past bumper: car={car.position:.2f} max_front={max_front:.2f}"
    )
    # Forward-only: car may sit slightly beyond min_gap until leader advances — never reverse to close
    assert max_front - car.position <= 6.0, (
        f"car unreasonably far behind: gap={max_front - car.position:.2f}"
    )
    print(
        f"  PASS  car4_merge_hold  bus={bus_x[-1]:.1f}m car={car_x[-1]:.1f}m "
        f"rear_gap={_rear_gap(bus, car):.2f}m stable_rear={bus_rear_bumper_x(bus):.1f}"
    )


def test_stable_rear_blocks_yaw_only_jump():
    """Pure yaw must not move follower rear bumper (static BUS_LENGTH)."""
    bus = Bus(999, 310.0, 0.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    rears = []
    for deg in [0, 5, 10, 15, 17, 12, 8]:
        bus.heading_angle = np.radians(deg)
        rears.append(bus_rear_bumper_x(bus))
    assert max(rears) - min(rears) < 1e-6, (
        f"yaw changed follower rear: {rears}"
    )
    print(f"  PASS  static_rear_yaw_invariant  rear={rears[0]:.1f}")


def test_car_stays_behind_a_blocking_bus_until_it_advances():
    """A car that has stopped behind a bus stays behind it, and moves on once the bus advances.

    The car starts 25 m behind the bus's bumper line: a car that is already on the line at 8 m/s
    (the old setup) cannot stop there physically (3.6 m are needed even at 9 m/s^2); the old
    stop-hold froze it in place instead.
    """
    bus = Bus(999, 308.0, 0.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.0
    bus.heading_angle = np.radians(10.0)
    bus._merge_progress = 0.35
    car = Vehicle(4, 270.0, 8.0, CAR_PARAMS)
    for _ in range(120):
        _step_pair(bus, car)
    max_front = leader_max_follower_front(vehicle_leader_state(bus), MIN_GAP_M)
    assert car.velocity < 0.05, f"car should have stopped behind the bus, v={car.velocity:.2f}"
    assert car.position <= max_front + 1e-6, f"car passed the bus's bumper line: {car.position:.2f} > {max_front:.2f}"
    stopped_x = car.position
    for k in range(30):
        bus.heading_angle = np.radians(12.0 + 5.0 * np.sin(k * 0.2))
        _step_pair(bus, car)
    assert abs(car.position - stopped_x) < 0.02, "car moved while the bus still blocked it"
    for _ in range(20):
        bus.position += 0.5
        _step_pair(bus, car)
    assert car.position > stopped_x + 0.1, "car should move on after the bus advances"
    print(f"  PASS  car_stays_behind_bus  stopped={stopped_x:.2f} final={car.position:.2f}")

def test_no_overlap_with_bus_bumper():
    """Car never moves backward; may sit slightly past max_front until bus advances."""
    bus = Bus(999, 308.0, 0.4, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.2
    bus._merge_progress = 0.30
    car = Vehicle(4, 280.0, 12.0, CAR_PARAMS)
    xs = []
    for step in range(120):
        bus.heading_angle = np.radians(8.0 + 9.0 * np.sin(step * 0.12))
        bus.position += 0.035
        _step_pair(bus, car)
        xs.append(car.position)
        leader = vehicle_leader_state(bus)
        max_front = leader_max_follower_front(leader, MIN_GAP_M)
        assert car.position <= max_front + 2.5, (
            f"extreme overshoot step {step}: car={car.position:.2f} max_front={max_front:.2f}"
        )
    for i in range(1, len(xs)):
        assert xs[i] >= xs[i - 1] - 1e-6
    print(f"  PASS  monotonic_near_bumper  car={car.position:.2f} rear_gap={_rear_gap(bus, car):.2f}")


def test_merge_start_alongside_no_teleport():
    """IN_BAY → WAITING: car alongside bus must advance monotonically."""
    bus = Bus(999, 300.316, 0.0, CAR_PARAMS)
    bus.state = BusState.IN_BAY
    bus.lateral_offset = -3.5
    bus._merge_progress = 0.0
    car = Vehicle(4, 299.565, 13.77, CAR_PARAMS)

    xs = [car.position]
    for step in range(5):
        if step == 2:
            bus.state = BusState.WAITING_TO_MERGE
            bus._merge_progress = 0.08
            bus.velocity = 0.2
        _step_pair(bus, car)
        xs.append(car.position)

    for i in range(1, len(xs)):
        assert xs[i] >= xs[i - 1] - 1e-5, (
            f"merge-start teleport step {i}: {xs[i-1]:.3f} -> {xs[i]:.3f}"
        )
    print(f"  PASS  merge_start_alongside  {xs[0]:.3f}->{xs[-1]:.3f}m")


def test_car_past_the_bumper_line_brakes_without_moving_back():
    """Streamlit t≈46.8 s case: a car already past the legal line never moves backward and never brakes
    beyond 9 m/s^2. (The old stop-hold also froze it at 0 m/s; once the car is alongside the bus it no
    longer follows the bus, and whether it touches the bus is judged by the contact check.)"""
    bus = Bus(999, 318.25, 0.36, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.heading_angle = np.radians(12.0)
    bus.lateral_offset = -2.0
    bus._merge_progress = 0.04
    car = Vehicle(4, 307.057, 3.4, CAR_PARAMS)
    max_front = leader_max_follower_front(vehicle_leader_state(bus), MIN_GAP_M)
    assert car.position > max_front + 0.5, "setup: car ahead of legal line"
    xs, vs = [car.position], [car.velocity]
    for _ in range(10):
        _step_pair(bus, car)
        xs.append(car.position)
        vs.append(car.velocity)
    assert all(b >= a - 1e-9 for a, b in zip(xs, xs[1:])), f"car moved back: {xs}"
    assert all((a - b) / 0.1 <= 9.0 + 1e-6 for a, b in zip(vs, vs[1:])), f"braking beyond 9 m/s^2: {vs}"
    print(f"  PASS  past_line_brakes_physically  pos={car.position:.3f} max_front={max_front:.3f}")

def test_streamlit_yaw_merge_window_monotonic():
    """Aggressive yaw + creeping bus — 200 steps, zero backward car steps."""
    bus = Bus(999, 308.0, 0.3, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.2
    bus._merge_progress = 0.35
    car = Vehicle(4, 298.0, 10.0, CAR_PARAMS)
    xs = []
    for step in range(200):
        bus.heading_angle = np.radians(5.0 + 14.0 * np.sin(step * 0.18))
        bus.position += 0.038
        bus.lateral_offset = min(0.0, -2.2 + step * 0.01)
        bus._merge_progress = float(np.clip((bus.lateral_offset + 3.5) / 3.5, 0, 1))
        _step_pair(bus, car)
        xs.append(car.position)
    for i in range(1, len(xs)):
        d = xs[i] - xs[i - 1]
        assert d >= -1e-5, f"backward at step {i}: {xs[i-1]:.3f} -> {xs[i]:.3f} (Δ={d:.3f})"
    print(f"  PASS  streamlit_yaw_window  car {xs[0]:.1f}->{xs[-1]:.1f}m  steps={len(xs)}")


def test_bus_rear_retreat_does_not_snap_car_backward():
    """When bus rear bumper retreats (yaw), follower must not move backward."""
    bus = Bus(999, 310.0, 0.5, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.0
    bus._merge_progress = 0.35
    car = Vehicle(4, 298.0, 6.0, CAR_PARAMS)
    for deg in [8.0, 14.0, 17.0, 10.0, 6.0, 15.0, 12.0]:
        bus.heading_angle = np.radians(deg)
        bus.position += 0.05
        _step_pair(bus, car)
    xs = []
    for _ in range(60):
        bus.heading_angle = np.radians(10.0 + 8.0 * np.sin(_ * 0.25))
        bus.position += 0.04
        _step_pair(bus, car)
        xs.append(car.position)
    for i in range(1, len(xs)):
        assert xs[i] >= xs[i - 1] - 1e-5, (
            f"car snapped back step {i}: {xs[i-1]:.3f} -> {xs[i]:.3f}"
        )
    print(f"  PASS  bus_rear_retreat_no_snap  car {xs[0]:.1f}->{xs[-1]:.1f}m")


def test_bus_no_snap_when_car_alongside():
    """t≈42.3 s: car front past bus front but rear beside bus — bus must not snap back."""
    from busmerge.safe_speed import bus_blocking_max_front

    bus = Bus(999, 317.0, 12.5, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    car = Vehicle(5, 319.0, 14.3, CAR_PARAMS)
    mf, _ = bus_blocking_max_front(bus, [bus, car])
    assert mf is None, f"alongside car must not block bus, got max_front={mf}"
    print("  PASS  bus_alongside_not_blocked")


def test_bus_blocks_when_car_fully_ahead():
    """Car rear cleared bus front — bumper line applies."""
    from busmerge.safe_speed import bus_blocking_max_front

    bus = Bus(999, 310.0, 5.0, CAR_PARAMS)
    car = Vehicle(5, 325.0, 10.0, CAR_PARAMS)
    car_rear = 325.0 - car.params.length
    mf, _ = bus_blocking_max_front(bus, [bus, car])
    assert mf is not None
    assert abs(mf - (car_rear - bus.params.min_gap)) < 1e-4
    print(f"  PASS  bus_blocks_fully_ahead  max_front={mf:.1f}")


def test_queue_car_monotonic_behind_car():
    """Normal IDM queue: second car never teleports backward behind first."""
    lead = Vehicle(10, 320.0, 0.0, CAR_PARAMS)
    follow = Vehicle(11, 300.0, 11.0, CAR_PARAMS)
    xs, vs = [], []
    for _ in range(100):
        follow.reaction_timer = 0.0
        lead.reaction_timer = 0.0
        from busmerge.rl.traffic_leaders import vehicle_leader_state
        follow.update_physics(0.1, vehicle_leader_state(lead), bus=None)
        lead.update_physics(0.1, None, bus=None)
        xs.append(follow.position)
        vs.append(follow.velocity)
    assert_smooth_trajectory("queue", [0] * len(xs), xs, vs)
    print(f"  PASS  queue_monotonic  follow {xs[0]:.1f}->{xs[-1]:.1f}m gap={lead.position - lead.params.length - follow.position:.2f}")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
