"""
Tests for the virtual blinker presence and the braking it causes.

Scenarios validated:
  1. Car at 25 m during full dwell (presence=0.1)  → Y > 0, mild decel (no emergency)
  2. Car at 6 m during last 3 s   (presence=0.25) → speed bleeds below 10 m/s in 2 s
  3. Regression: IN_BAY → WAITING_TO_MERGE with gap 6.5 m: |Δv| < 2.0 m/s in first 0.1 s
  4. A car behind a bus that starts to merge never brakes beyond 9 m/s^2
"""


import pytest
from busmerge.vehicle import Vehicle, Bus, BusState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus(state: BusState = BusState.IN_BAY, blinker_presence: float = 0.10,
              signaling: bool = False, position: float = 300.0) -> Bus:
    bus = Bus(0, position, 0.0, None)
    bus.state = state
    bus.blinker_presence = blinker_presence
    bus.signaling_merge = signaling
    bus._merge_progress = 0.0
    bus.lateral_offset = -3.5
    return bus


def _make_car(position: float, velocity: float = 13.0) -> Vehicle:
    car = Vehicle(1, position, velocity)
    car.last_applied_yield = 0.0
    return car


def _advance_n_steps(car: Vehicle, bus, n: int, dt: float = 0.1):
    """Run n IDM steps with no other leader."""
    for _ in range(n):
        car.update_physics(dt, leader=None, bus=bus)


# ---------------------------------------------------------------------------
# Test 1: full dwell presence (0.10) — car 25 m behind bus → Y > 0, gentle decel
# ---------------------------------------------------------------------------

def test_car_behind_a_bus_starting_to_merge_never_brakes_beyond_the_limit():
    """When the bus starts to merge in front of a fast car, the car's speed may drop by at most
    9 m/s^2 · dt per frame (the old bumper cap could remove 6 m/s in one frame)."""
    from busmerge.rl.traffic_leaders import vehicle_leader_state
    bus = _make_bus(state=BusState.WAITING_TO_MERGE, blinker_presence=0.0)
    bus.lateral_offset = -2.5
    bus._merge_progress = 0.05
    bus.velocity = 2.5
    car = _make_car(position=300.0 - 11.0 - 5.5, velocity=10.76)
    car.last_applied_yield = 0.25
    for _ in range(10):
        v0 = car.velocity
        car.reaction_timer = 0.0
        car.update_physics(0.1, leader=vehicle_leader_state(bus), bus=bus)
        assert v0 - car.velocity <= 0.9 + 1e-9, f"speed dropped {v0 - car.velocity:.2f} m/s in one frame"


def test_full_dwell_presence_yields_nonzero():
    """Car 25 m behind bus during full dwell (blinker_presence=0.1) sees Y > 0."""
    bus = _make_bus(blinker_presence=0.10, signaling=False)
    # Car front is 25 m behind bus rear (bus rear ≈ 300 - 11 = 289; car at 264)
    car = _make_car(position=264.0, velocity=13.0)
    raw_y = car._merge_yield_factor(bus)
    assert raw_y > 0.0, f"expected Y > 0 during IN_BAY presence=0.1, got {raw_y}"


def test_full_dwell_presence_no_emergency_brake():
    """With presence=0.1 and car 25 m back, decel should not exceed comfort brake."""
    bus = _make_bus(blinker_presence=0.10, signaling=False)
    car = _make_car(position=264.0, velocity=13.0)
    # Seed yield so we're testing steady-state (bypass slew warm-up)
    car.last_applied_yield = car._merge_yield_factor(bus)
    accel = car._calculate_idm_accel(leader=None, bus=bus, dt=0.1)
    comfort = float(car.params.comfortable_brake)
    assert accel >= -comfort - 0.5, (
        f"Should not exceed comfort brake with gentle presence=0.1 at 25 m; "
        f"got {accel:.2f} m/s² (comfort={comfort:.2f})"
    )


# ---------------------------------------------------------------------------
# Test 2: blinker (last 3s) presence=0.25 — car 6 m behind, speed bleeds
# ---------------------------------------------------------------------------

def test_blinker_presence_bleeds_speed_at_close_range():
    """
    Car 6 m behind the bus during last 3 s of dwell (presence=0.25).
    After 2 s of IDM steps, speed should drop below 10 m/s from 13.5 m/s.
    """
    bus = _make_bus(blinker_presence=0.25, signaling=True)
    # Car front is 6 m behind bus rear (bus rear ≈ 289; car at 283)
    car = _make_car(position=283.0, velocity=13.5)
    # Seed to steady state
    car.last_applied_yield = car._merge_yield_factor(bus)
    _advance_n_steps(car, bus, n=20, dt=0.1)  # 2 s
    assert car.velocity < 10.0, (
        f"Expected speed < 10 m/s after 2 s with presence=0.25 at 6 m; "
        f"got {car.velocity:.2f} m/s"
    )


# ---------------------------------------------------------------------------
# Test 3: Regression — IN_BAY → WAITING_TO_MERGE transition |Δv| < 2 m/s
# ---------------------------------------------------------------------------

def test_transition_delta_v_less_than_2():
    """
    The 39.2 s cliff regression test.
    Simulate: bus IN_BAY with blinker, then switch to WAITING_TO_MERGE.
    First 0.1 s step after transition: |Δv| must be < 2.0 m/s.
    (Pre-fix it was ~9.2 m/s; post-fix the car has bled off speed during dwell.)
    """
    # Step A: run 30 dwell steps with blinker so car pre-decelerates
    bus = _make_bus(blinker_presence=0.25, signaling=True, position=300.0)
    car = _make_car(position=284.0, velocity=13.5)
    # Warm up slew rate
    car.last_applied_yield = car._merge_yield_factor(bus)
    for _ in range(30):
        car.update_physics(0.1, leader=None, bus=bus)

    # Step B: transition bus to WAITING_TO_MERGE (cold wake)
    bus.state = BusState.WAITING_TO_MERGE
    bus.blinker_presence = 0.0
    bus.signaling_merge = False
    bus._merge_progress = 0.0

    v_before = float(car.velocity)
    car.update_physics(0.1, leader=None, bus=bus)
    v_after = float(car.velocity)

    delta_v = abs(v_after - v_before)
    assert delta_v < 2.0, (
        f"Velocity cliff at transition: Δv={delta_v:.2f} m/s (must be < 2.0). "
        f"Before={v_before:.2f}, after={v_after:.2f}."
    )


def test_traffic_leaders_always_ignores_bus_in_bay():
    """IN_BAY bus is NEVER a formal IDM queue leader — blinker or not.

    Cars react only via blended Y_eff, not by locking onto a stationary bay bus.
    """
    from busmerge.rl.traffic_leaders import should_ignore_bus_as_leader
    bus_blinker = _make_bus(blinker_presence=0.25, signaling=True)
    bus_quiet = _make_bus(blinker_presence=0.10, signaling=False)
    bus_off = _make_bus(blinker_presence=0.0, signaling=False)
    for bus in (bus_blinker, bus_quiet, bus_off):
        result = should_ignore_bus_as_leader(bus, gap_to_car_front=10.0, car=None)
        assert result is True, (
            f"should_ignore_bus_as_leader must return True during IN_BAY "
            f"(presence={bus.blinker_presence})"
        )


def test_full_dwell_does_not_phantom_stop():
    """Car must keep moving during IN_BAY dwell — no stop-hold lock on bay bus.

    Regression for the phantom queue: presence=0.1 + leader lock stopped cars
    for the entire 15 s dwell.  After the leader-paradox fix, bus is ignored as
    queue leader; only mild Y_eff blend applies.
    """
    bus = _make_bus(blinker_presence=0.10, signaling=False)
    car = _make_car(position=280.0, velocity=12.0)
    car.last_applied_yield = car._merge_yield_factor(bus)
    _advance_n_steps(car, bus, n=50, dt=0.1)  # 5 s
    assert car.velocity > 5.0, (
        f"Car phantom-stopped during IN_BAY dwell: v={car.velocity:.2f} m/s"
    )


def test_early_waiting_bay_bus_not_queue_leader():
    """WAITING_TO_MERGE + still in bay must not stop through traffic.

    The synthetic presence floor (0.15) is for the brain/governor only.
    Cars pass with mild yield; no bumper stop-hold.
    """
    from busmerge.rl.traffic_leaders import should_ignore_bus_as_leader, resolve_car_leader
    bus = Bus(0, 300.0, 0.0, None)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -3.5
    bus.heading_angle = 0.0
    bus._merge_progress = 0.0
    car = _make_car(position=285.0, velocity=12.0)
    gap = 300.0 - 11.0 - 285.0
    assert should_ignore_bus_as_leader(bus, gap, car=car) is True
    vehicles = sorted([bus, car], key=lambda v: v.position, reverse=True)
    leader, _ = resolve_car_leader(vehicles, vehicles.index(car), bus)
    assert leader is None or leader.get("id") != bus.id
    for _ in range(30):
        car.update_physics(0.1, leader=None, bus=bus)
    assert car.velocity > 5.0, f"stuck behind early-WAITING bay bus: v={car.velocity:.2f}"
    assert car.position > 290.0, "car should advance past the stop line region"


def test_blinker_yield_is_low_continuous():
    """Blinker Y stays mild at medium range — no encroachment-floor spike to ~1.0."""
    from busmerge.rl.merge_yield import compute_yield_factor
    # presence=0.1 at 15 m must not approach full yield
    y = compute_yield_factor(0.0, 15.0, 0.10, is_blinker=True)
    assert 0.0 < y < 0.25, f"blinker Y at 15m too high: {y:.3f}"
    # presence=0.25 at 6 m: bleed-off range, not emergency
    y2 = compute_yield_factor(0.0, 6.0, 0.25, is_blinker=True)
    assert 0.15 < y2 < 0.70, f"blinker Y at 6m out of bleed range: {y2:.3f}"
    # Continuity: no jump > 0.08 across 0.5 m
    y_hi = compute_yield_factor(0.0, 10.2, 0.25, is_blinker=True)
    y_lo = compute_yield_factor(0.0, 9.8, 0.25, is_blinker=True)
    assert abs(y_lo - y_hi) < 0.08, f"blinker discontinuity: {y_hi:.3f}->{y_lo:.3f}"


def test_traffic_leaders_ignores_when_no_presence():
    """When bus is IN_BAY with blinker_presence=0, ignore bus (same as always)."""
    from busmerge.rl.traffic_leaders import should_ignore_bus_as_leader
    bus = _make_bus(blinker_presence=0.0, signaling=False)
    result = should_ignore_bus_as_leader(bus, gap_to_car_front=10.0, car=None)
    assert result is True, "should_ignore_bus_as_leader must return True when presence=0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
