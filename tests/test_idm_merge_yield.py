#!/usr/bin/env python3
"""
IDM merge-yield diagnostic — continuous yield blend (Option A).

Run:  python3 test_idm_merge_yield.py
Exit 0 = all PASS (use before retraining PPO).
"""
import sys
import numpy as np


from busmerge.vehicle import Vehicle, Bus, BusState, CAR_PARAMS
from busmerge.rl.traffic_leaders import resolve_car_leader, should_ignore_bus_as_leader
from busmerge.rl.merge_yield import (
    compute_yield_factor,
    yield_progress_factor,
    yield_distance_factor,
    car_is_ahead_of_merging_bus,
    scan_nearest_car_for_merge,
)


def _step_car(car, bus, dt=0.1):
    vehicles = sorted([bus, car], key=lambda v: v.position, reverse=True)
    idx = vehicles.index(car)
    leader, _ = resolve_car_leader(vehicles, idx, bus)
    car.reaction_timer = 0.0
    car.last_presence_seen = 0.0
    car.update_physics(dt, leader, bus=bus)
    return leader


def _seed_full_yield(car, bus):
    """Skip Surprise Filter ramp for steady-state brake assertions."""
    car.last_applied_yield = float(car._merge_yield_factor(bus))


def _gap(bus, car):
    return bus.position - bus.projected_length_along_x() - car.position


def test_yield_factor_math():
    assert yield_progress_factor(0.02) == 0.0
    assert yield_progress_factor(0.50) == 1.0
    assert abs(yield_progress_factor(0.225) - 0.5) < 0.01
    assert yield_distance_factor(60.0) == 0.0
    # Continuous smoothstep: mid-range (25 m of 50 m ignore) ≈ 0.5, not a hard 1.0.
    assert abs(yield_distance_factor(25.0) - 0.5) < 0.05
    assert yield_distance_factor(0.0) == 1.0
    y = compute_yield_factor(0.15, 45.0)
    assert 0.0 < y < 0.15, f"mid-range Y_eff too high: {y}"
    # Blinker path: low continuous Y, no floor spike.
    y_b = compute_yield_factor(0.0, 15.0, 0.10, is_blinker=True)
    assert 0.0 < y_b < 0.25, f"blinker Y too high at 15m: {y_b}"
    print(f"  PASS  yield_factor_math  Y(0.15,45m)={y:.3f} blinker={y_b:.3f}")


def test_yield_no_discontinuity_near_close_gaps():
    """No violent Y_eff jump crossing 8 m or 20 m (smooth close-range curve)."""
    progress, presence = 0.30, 0.20
    pairs = [(8.2, 7.8), (20.2, 19.8), (12.1, 11.9)]
    for g_hi, g_lo in pairs:
        y_hi = compute_yield_factor(progress, g_hi, presence)
        y_lo = compute_yield_factor(progress, g_lo, presence)
        assert abs(y_lo - y_hi) < 0.12, (
            f"yield jump {g_hi}->{g_lo}m: {y_hi:.3f} -> {y_lo:.3f}"
        )
    print("  PASS  yield_no_discontinuity_near_close_gaps")


def test_approach_speed_soft_cap():
    """High speed + small gap must not allow full-gap closure in one frame."""
    from busmerge.rl.bumper_kinematics import max_approach_speed
    dt = 0.1
    gap = 1.5
    cap = max_approach_speed(gap, dt, comfortable_brake=2.5)
    assert cap < gap / dt, f"cap should be below gap/dt={gap/dt}, got {cap:.2f}"
    assert cap <= (2.0 * 2.5 * gap) ** 0.5 + 1e-6
    print(f"  PASS  approach_speed_soft_cap  cap={cap:.2f} m/s (gap={gap}m)")


def test_far_gap_free_flow():
    """P≈0.02, gap=60 m — no yield, near free flow."""
    bus = Bus(999, 300.0, 0.2, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -3.4
    bus.heading_angle = np.radians(4.0)
    bus._merge_progress = 0.02
    bus.velocity = 0.2

    car = Vehicle(1, 235.0, 10.0, CAR_PARAMS)
    gap = _gap(bus, car)
    assert gap >= 52.0, f"gap setup wrong: {gap:.1f}"
    assert compute_yield_factor(0.02, gap) == 0.0
    assert should_ignore_bus_as_leader(bus, gap)
    _step_car(car, bus)
    assert car.acceleration >= -0.5, (
        f"far gap should cruise, got accel={car.acceleration:.2f}"
    )
    print(f"  PASS  far_gap_free_flow  gap={gap:.1f} accel={car.acceleration:.2f}")


def test_mild_decel_mid_range():
    """P≈0.15, gap≈45 m — mild blend only, not panic stop."""
    bus = Bus(999, 300.0, 0.4, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.8
    bus.heading_angle = np.radians(6.0)
    bus._merge_progress = 0.15
    bus.velocity = 0.4

    car = Vehicle(2, 244.0, 11.0, CAR_PARAMS)
    gap = _gap(bus, car)
    y = compute_yield_factor(0.15, gap)
    assert 0.0 < y < 0.2, f"Y_eff out of mild range: {y:.3f} gap={gap:.1f}"
    _step_car(car, bus)
    assert car.acceleration > -2.5, (
        f"mid-range should not hard-brake: accel={car.acceleration:.2f} Y={y:.3f}"
    )
    print(f"  PASS  mild_decel_mid  gap={gap:.1f} Y={y:.3f} accel={car.acceleration:.2f}")


def test_clear_brake_close():
    """P≈0.30, gap≈8 m — clear braking."""
    bus = Bus(999, 300.0, 0.6, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.2
    bus.heading_angle = np.radians(9.0)
    bus._merge_progress = 0.30
    bus.velocity = 0.6

    car = Vehicle(3, 281.0, 12.0, CAR_PARAMS)
    gap = _gap(bus, car)
    y = compute_yield_factor(0.30, gap)
    assert y > 0.5, f"Y_eff should be high at close gap: {y:.3f} gap={gap:.1f}"
    _seed_full_yield(car, bus)
    _step_car(car, bus)
    assert car.acceleration <= -1.0, (
        f"close gap should brake clearly: accel={car.acceleration:.2f}"
    )
    print(f"  PASS  clear_brake_close  gap={gap:.1f} Y={y:.3f} accel={car.acceleration:.2f}")


def test_low_progress_far_no_yield():
    """P=0.03, far gap, low presence — no yield (cruise)."""
    bus = Bus(999, 300.0, 0.3, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -3.4
    bus.heading_angle = np.radians(2.0)
    bus._merge_progress = 0.03
    bus.velocity = 0.3

    car = Vehicle(4, 235.0, 11.0, CAR_PARAMS)
    gap = _gap(bus, car)
    assert gap > 50.0
    assert should_ignore_bus_as_leader(bus, gap)
    _step_car(car, bus)
    assert car.acceleration >= -0.5, (
        f"far + low P should not yield: accel={car.acceleration:.2f}"
    )
    print(f"  PASS  low_progress_far_no_yield  accel={car.acceleration:.2f}")


def test_presence_yield_close_low_progress():
    """High presence (lane blocked) + close gap — must brake even if P < vis_start."""
    bus = Bus(999, 300.0, 0.4, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.0
    bus.heading_angle = np.radians(11.0)
    bus._merge_progress = 0.04
    bus.velocity = 0.4

    car = Vehicle(12, 281.0, 12.0, CAR_PARAMS)
    gap = _gap(bus, car)
    pf = bus.presence_factor
    y = compute_yield_factor(0.04, gap, pf)
    assert pf > 0.15, f"presence too weak: {pf:.3f}"
    assert y >= 0.85, f"close + presence should force yield: Y={y:.3f}"
    assert not should_ignore_bus_as_leader(bus, gap)
    _seed_full_yield(car, bus)
    _step_car(car, bus)
    assert car.acceleration <= -1.0, (
        f"presence close yield: accel={car.acceleration:.2f} pf={pf:.3f}"
    )
    print(f"  PASS  presence_close_yield  pf={pf:.3f} Y={y:.3f} accel={car.acceleration:.2f}")


def test_car_ahead_of_bus_no_yield():
    """Car downstream of bus front must not brake for bus behind it (car #3 bug)."""
    bus = Bus(999, 300.0, 0.5, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.0
    bus.heading_angle = np.radians(11.0)
    bus._merge_progress = 0.35
    bus.velocity = 0.5

    car = Vehicle(22, 318.0, 12.0, CAR_PARAMS)
    assert car_is_ahead_of_merging_bus(bus, car)
    gap = _gap(bus, car)
    assert compute_yield_factor(0.35, gap, bus.presence_factor, car_ahead=True) == 0.0
    vehicles = sorted([car, bus], key=lambda v: v.position, reverse=True)
    leader, _ = resolve_car_leader(vehicles, vehicles.index(car), bus)
    assert leader is None
    _step_car(car, bus)
    assert car.acceleration >= -0.5, (
        f"car ahead of bus must cruise: accel={car.acceleration:.2f}"
    )
    print(f"  PASS  car_ahead_no_yield  accel={car.acceleration:.2f}")


def test_bus_scan_sees_car_ahead():
    """Bus brain must detect a stopped car 8 m ahead (old scan window missed this)."""
    bus = Bus(999, 300.0, 0.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    car = Vehicle(23, 318.0, 0.0, CAR_PARAMS)
    gap, _, _, _, _, nearest = scan_nearest_car_for_merge(bus, [bus, car])
    assert nearest is not None and nearest.id == 23
    assert gap < 0.0, f"car ahead should give negative rear_gap, got {gap:.1f}"
    print(f"  PASS  bus_scan_car_ahead  gap={gap:.1f}")


def test_no_bumper_jitter_behind_stopped_bus():
    """Follower position must not sawtooth (forward creep + snap back)."""
    bus = Bus(999, 310.0, 0.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.0
    bus.heading_angle = np.radians(10.0)
    bus._merge_progress = 0.35
    car = Vehicle(32, 295.0, 8.0, CAR_PARAMS)
    positions = []
    for _ in range(120):
        vehicles = sorted([bus, car], key=lambda v: v.position, reverse=True)
        idx = vehicles.index(car)
        leader, _ = resolve_car_leader(vehicles, idx, bus)
        car.reaction_timer = 0.0
        car.update_physics(0.1, leader, bus=bus)
        positions.append(car.position)
    for i in range(1, len(positions)):
        assert positions[i] >= positions[i - 1] - 1e-5, (
            f"bumper jitter step {i}: {positions[i-1]:.3f} -> {positions[i]:.3f}"
        )
    print(f"  PASS  no_bumper_jitter  final_gap={bus.position - bus.projected_length_along_x() - car.position:.2f}")


def test_bus_retreat_smooth_not_teleport():
    """Bus too far forward eases back over multiple steps."""
    bus = Bus(999, 315.0, 0.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    car = Vehicle(33, 318.0, 0.0, CAR_PARAMS)
    from busmerge.rl.bumper_kinematics import limit_bus_to_cars_ahead
    p0 = bus.position
    limit_bus_to_cars_ahead(bus, [bus, car], 0.1)
    bus.position += bus.velocity * 0.1
    step1_move = bus.position - p0
    assert step1_move > -0.25, f"bus teleported back {step1_move:.2f} m in one step"
    assert step1_move <= 0.0, "bus should retreat not advance when blocked ahead"
    print(f"  PASS  bus_retreat_smooth  step1_delta={step1_move:.3f}")


def test_queue_no_overlap():
    """Two cars in queue must not occupy the same bumper position."""
    lead = Vehicle(30, 320.0, 8.0, CAR_PARAMS)
    follow = Vehicle(31, 300.0, 10.0, CAR_PARAMS)
    for _ in range(80):
        lead.reaction_timer = 0.0
        follow.reaction_timer = 0.0
        from busmerge.rl.traffic_leaders import vehicle_leader_state
        follow.update_physics(0.1, vehicle_leader_state(lead), bus=None)
        lead.update_physics(0.1, None, bus=None)
    gap = lead.position - lead.params.length - follow.position
    assert gap >= follow.params.min_gap - 0.05, (
        f"queue overlap: gap={gap:.2f} min_gap={follow.params.min_gap}"
    )
    print(f"  PASS  queue_no_overlap  gap={gap:.2f}")


def test_multi_car_no_lookthrough():
    """Car behind bus must not follow a car ahead of the bus through the merge zone."""
    bus = Bus(999, 300.0, 0.5, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.5
    bus.heading_angle = np.radians(8.0)
    bus._merge_progress = 0.04
    bus.velocity = 0.5

    car_ahead = Vehicle(20, 340.0, 13.0, CAR_PARAMS)
    car_behind = Vehicle(21, 275.0, 12.0, CAR_PARAMS)
    vehicles = sorted([car_ahead, bus, car_behind], key=lambda v: v.position, reverse=True)
    idx = vehicles.index(car_behind)
    leader, _ = resolve_car_leader(vehicles, idx, bus)
    gap = _gap(bus, car_behind)
    assert leader is not None and leader["id"] == bus.id, (
        f"look-through bug: leader={leader} gap={gap:.1f}"
    )
    _seed_full_yield(car_behind, bus)
    car_behind.reaction_timer = 0.0
    car_behind.update_physics(0.1, leader, bus=bus)
    assert car_behind.acceleration < -0.5, (
        f"queue car must brake for bus: accel={car_behind.acceleration:.2f}"
    )
    print(f"  PASS  multi_car_no_lookthrough  accel={car_behind.acceleration:.2f}")


def test_first_sight_brakes_when_progress_high():
    """P=0.20, moderate gap — must brake (not coast from shock timer)."""
    bus = Bus(999, 300.0, 0.5, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.5
    bus.heading_angle = np.radians(8.0)
    bus._merge_progress = 0.2
    bus.velocity = 0.5

    car = Vehicle(5, 270.0, 10.0, CAR_PARAMS)
    _seed_full_yield(car, bus)
    leader = _step_car(car, bus)
    assert leader is not None, "bus should be IDM leader at P=0.20"
    assert car.acceleration < -0.5, (
        f"material merge progress: expected braking, accel={car.acceleration:.2f}"
    )
    print(f"  PASS  first_sight_brakes  accel={car.acceleration:.2f}")


def test_in_bay_no_false_leader():
    """Bus freshly in WAITING_TO_MERGE, fully in bay (lateral=-3.5, progress=0).

    Geometric presence is 0 — the synthetic 0.15 floor is for PPO/governor only.
    Cars must IGNORE the bus as a formal IDM leader so they can pass the bay.
    Mild blinker-like yield may still apply (soft bleed, no stop-hold).
    """
    bus = Bus(999, 300.0, 0.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -3.5
    bus.heading_angle = 0.0
    bus._merge_progress = 0.0

    assert bus.geometric_presence_factor <= 0.08
    assert bus.presence_factor >= 0.15  # floor still for brain features

    # --- Close range: bus is NOT a bumper leader ---
    car_close = Vehicle(6, 274.0, 12.0, CAR_PARAMS)
    gap_close = _gap(bus, car_close)
    assert should_ignore_bus_as_leader(bus, gap_close), (
        f"Bay-parked WAITING bus must be ignored as leader at gap={gap_close:.1f}m"
    )
    y = car_close._merge_yield_factor(bus)
    assert y < 0.35, f"early-WAITING yield must stay mild, got {y:.3f}"

    # --- After material progress, bus becomes a real merge threat ---
    bus._merge_progress = 0.30
    bus.lateral_offset = -2.0
    assert not should_ignore_bus_as_leader(bus, gap_close) or bus.geometric_presence_factor > 0.08

    # --- Surprise Filter still caps first-frame applied Y ---
    car_new = Vehicle(8, 274.0, 12.0, CAR_PARAMS)
    car_new.last_applied_yield = 0.0
    car_new._calculate_idm_accel(leader=None, bus=bus, dt=0.1)
    assert car_new.last_applied_yield <= 0.05 + 1e-6
    print(f"  PASS  in_bay_no_false_leader  mild_Y={y:.3f}")


def test_close_hold_distance():
    """P=0.50, gap≈3 m slow bus — hold ~2–5 m behind rear after settling."""
    bus = Bus(999, 300.0, 0.8, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -1.5
    bus.heading_angle = np.radians(12.0)
    bus._merge_progress = 0.5
    bus.velocity = 0.8

    car = Vehicle(7, 286.0, 2.0, CAR_PARAMS)
    init_gap = _gap(bus, car)
    assert 2.0 <= init_gap <= 6.0, f"initial gap setup: {init_gap:.2f}"
    for _ in range(120):
        _step_car(car, bus, dt=0.1)
    gap = _gap(bus, car)
    assert gap > 0.0, f"car must not pass bus (gap={gap:.2f})"
    assert 1.5 <= gap <= 8.0, f"hold distance {gap:.2f} m out of 2–5 m band (tolerance)"
    assert car.velocity < 3.0, f"car still too fast after settle: {car.velocity:.2f}"
    print(f"  PASS  close_hold_distance  gap={gap:.2f} v={car.velocity:.2f}")


def test_alongside_car_yields_during_waiting():
    """Alongside during WAITING_TO_MERGE — must yield/hold, not re-accelerate (CSV t≈39–41).

    Bus is not a bumper leader (alongside), but Yield Y must stay high so the car
    does not treat the road as clear while overlapping the bus longitudinally.
    """
    bus = Bus(999, 300.316, 0.2, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -3.0
    bus.heading_angle = np.radians(5.0)
    bus._merge_progress = 0.08
    bus.velocity = 0.2

    car = Vehicle(40, 299.565, 3.5, CAR_PARAMS)  # already slow (almost stopped)
    gap = _gap(bus, car)
    assert gap < 0.0, f"setup: car should be past bus rear, gap={gap:.2f}"
    assert not car_is_ahead_of_merging_bus(bus, car)
    assert should_ignore_bus_as_leader(bus, gap, car=car)

    y = car._merge_yield_factor(bus)
    assert y >= 0.5, f"alongside WAITING must yield strongly, Y={y:.3f}"

    x0 = car.position
    v0 = car.velocity
    car.last_applied_yield = y
    leader = _step_car(car, bus)
    assert leader is None, f"alongside car must not follow bus, leader={leader}"
    assert car.position >= x0 - 1e-4, f"teleport: {x0:.3f} -> {car.position:.3f}"
    # Must not re-accelerate away from near-stop
    assert car.velocity <= v0 + 0.3, (
        f"alongside car must not re-accelerate: v0={v0:.2f} -> {car.velocity:.2f}"
    )
    print(f"  PASS  alongside_yields_during_waiting  Y={y:.3f} v={car.velocity:.2f}")


def test_alongside_active_merge_brakes():
    """Alongside + high P/presence — must brake, bus still not bumper leader (t≈41 s)."""
    bus = Bus(999, 321.0, 12.4, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -0.5
    bus.heading_angle = np.radians(18.0)
    bus._merge_progress = 0.87
    bus.velocity = 12.4

    car = Vehicle(5, 314.0, 13.8, CAR_PARAMS)
    gap = _gap(bus, car)
    assert gap < 0.0, f"setup: alongside gap={gap:.2f}"
    pf = bus.presence_factor
    y = compute_yield_factor(0.87, gap, pf)
    assert y > 0.5, f"active merge alongside must yield: Y={y:.3f} pf={pf:.3f}"
    assert should_ignore_bus_as_leader(bus, gap, car=car)

    _seed_full_yield(car, bus)
    car.reaction_timer = 0.0
    _step_car(car, bus)
    assert car.acceleration < -0.5, (
        f"alongside high-P must brake: accel={car.acceleration:.2f} Y={y:.3f}"
    )
    print(f"  PASS  alongside_active_merge_brakes  Y={y:.3f} accel={car.acceleration:.2f}")


def test_simulation_resolve_car_leader():
    """Production path: resolve_car_leader + update_physics (train/prod parity)."""
    from busmerge.simulation import SimulationEngine
    from busmerge.config import SimConfig

    sim = SimulationEngine(scenario="B", config=SimConfig())
    bus = Bus(999, 300.0, 0.6, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.4
    bus.heading_angle = np.radians(7.0)
    bus._merge_progress = 0.22
    bus.velocity = 0.6
    car = Vehicle(8, 272.0, 10.5, CAR_PARAMS)
    car.reaction_timer = 0.0
    car.last_presence_seen = 0.0
    _seed_full_yield(car, bus)
    sim.vehicles = sorted([bus, car], key=lambda v: v.position, reverse=True)
    the_bus = bus
    from busmerge.rl.traffic_leaders import resolve_car_leader as rcl
    for i, veh in enumerate(sim.vehicles):
        if isinstance(veh, Bus):
            continue
        lead, _ = rcl(sim.vehicles, i, the_bus)
        veh.update_physics(0.1, lead, bus=the_bus)
    assert car.acceleration < -0.5, f"sim path accel={car.acceleration:.2f}"
    print(f"  PASS  simulation_path  accel={car.acceleration:.2f}")


if __name__ == "__main__":
    print("=" * 60)
    print("IDM MERGE YIELD (continuous blend)")
    print("=" * 60)
    failed = []
    for fn in (
        test_yield_factor_math,
        test_yield_no_discontinuity_near_close_gaps,
        test_approach_speed_soft_cap,
        test_far_gap_free_flow,
        test_mild_decel_mid_range,
        test_clear_brake_close,
        test_low_progress_far_no_yield,
        test_presence_yield_close_low_progress,
        test_car_ahead_of_bus_no_yield,
        test_bus_scan_sees_car_ahead,
        test_no_bumper_jitter_behind_stopped_bus,
        test_bus_retreat_smooth_not_teleport,
        test_queue_no_overlap,
        test_multi_car_no_lookthrough,
        test_first_sight_brakes_when_progress_high,
        test_in_bay_no_false_leader,
        test_close_hold_distance,
        test_alongside_car_yields_during_waiting,
        test_alongside_active_merge_brakes,
        test_simulation_resolve_car_leader,
    ):
        try:
            fn()
        except AssertionError as e:
            failed.append((fn.__name__, str(e)))
            print(f"  FAIL  {fn.__name__}: {e}")
    print("=" * 60)
    if failed:
        print(f"FAILED {len(failed)} test(s)")
        sys.exit(1)
    print("ALL IDM MERGE YIELD TESTS PASSED")
    sys.exit(0)
