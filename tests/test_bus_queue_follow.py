#!/usr/bin/env python3
"""Bus queue-following on main road (MOVING) — same IDM as cars."""
import sys



from busmerge.vehicle import Vehicle, Bus, BusState, CAR_PARAMS
from busmerge.rl.traffic_leaders import resolve_bus_leader


def _step_pair(bus, car, dt=0.1):
    vehicles = sorted([bus, car], key=lambda v: v.position, reverse=True)
    bus_i = vehicles.index(bus)
    car_i = vehicles.index(car)
    from busmerge.rl.traffic_leaders import resolve_car_leader

    car_lead, _ = resolve_car_leader(vehicles, car_i, bus)
    bus_lead = resolve_bus_leader(vehicles, bus_i)
    car.reaction_timer = 0.0
    car.update_physics(dt, car_lead, bus=bus)
    bus.update_physics(dt, bus_lead, bus=bus)


def test_bus_movING_resolves_queue_leader():
    bus = Bus(999, 590.0, 13.9, CAR_PARAMS)
    bus.state = BusState.MOVING
    car = Vehicle(5, 600.0, 12.0, CAR_PARAMS)
    vehicles = sorted([bus, car], key=lambda v: v.position, reverse=True)
    lead = resolve_bus_leader(vehicles, vehicles.index(bus))
    assert lead is not None
    assert lead["id"] == 5
    print("  PASS  bus_resolves_leader")


def test_bus_movING_no_overtake_slower_car():
    """Bus faster than car ahead must not pass — same IDM queue as cars."""
    bus = Bus(999, 590.0, 13.9, CAR_PARAMS)
    bus.state = BusState.MOVING
    car = Vehicle(5, 600.0, 11.5, CAR_PARAMS)
    x_bus0 = bus.position
    for _ in range(300):
        _step_pair(bus, car)
    assert bus.position < car.position - 2.0, (
        f"bus overtook: bus={bus.position:.1f} car={car.position:.1f}"
    )
    assert bus.position > x_bus0, "bus should have moved forward"
    print(f"  PASS  bus_no_overtake  gap={car.position - bus.position:.1f}m")


def test_bus_movING_telemetry_leader_id():
    bus = Bus(999, 596.0, 13.5, CAR_PARAMS)
    bus.state = BusState.MOVING
    car = Vehicle(5, 600.0, 13.5, CAR_PARAMS)
    _step_pair(bus, car)
    lead = resolve_bus_leader(
        sorted([bus, car], key=lambda v: v.position, reverse=True),
        1,
    )
    bus.update_physics(0.1, lead, bus=bus)
    assert lead and lead["id"] == 5
    print("  PASS  bus_leader_is_car_ahead")


def test_bus_movING_no_pass_close_gap():
    """Repro t≈80 s: bus 13.9 m/s closing on car 12.55 m/s — must not pass."""
    bus = Bus(999, 858.0, 13.9, CAR_PARAMS)
    bus.state = BusState.MOVING
    car = Vehicle(3, 862.0, 12.55, CAR_PARAMS)
    for _ in range(300):
        _step_pair(bus, car)
    assert bus.position < car.position - 1.0, (
        f"bus passed car: bus={bus.position:.2f} car={car.position:.2f}"
    )
    print(f"  PASS  bus_close_gap  gap={car.position - bus.position:.1f}m")


if __name__ == "__main__":
    print("=" * 60)
    print("BUS QUEUE FOLLOW (MOVING)")
    print("=" * 60)
    failed = []
    for fn in (
        test_bus_movING_resolves_queue_leader,
        test_bus_movING_no_overtake_slower_car,
        test_bus_movING_telemetry_leader_id,
        test_bus_movING_no_pass_close_gap,
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
    print("ALL BUS QUEUE TESTS PASSED")
    sys.exit(0)
