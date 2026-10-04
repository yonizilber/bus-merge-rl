#!/usr/bin/env python3
"""Scenario A: in-lane bus stop must resume and exit at road_length."""
import sys



from busmerge.config import SimConfig
from busmerge.simulation import SimulationEngine
from busmerge.vehicle import Bus, BusState


def test_scenario_a_bus_resumes_after_dwell():
    """No cars — bus must leave the stop and pass bay-end (was frozen at ~316 m)."""
    sim = SimulationEngine(
        scenario="A",
        config=SimConfig(total_cars_to_spawn=0, traffic_rate=0.0),
    )
    sim.init_scenario()
    bus = next(v for v in sim.vehicles if isinstance(v, Bus))
    stop_x = bus.target_stop_x
    saw_stop = False
    for _ in range(1500):
        sim.step()
        for v in sim.vehicles:
            if isinstance(v, Bus) and v.state == BusState.STOPPED_IN_LANE:
                saw_stop = True
    df = sim.get_results()
    bus_max = float(df[df["type"] == "Bus"]["x"].max())
    assert saw_stop, "bus never stopped in lane"
    assert bus_max > stop_x + 50, f"bus stuck after dwell: max_x={bus_max:.1f}"
    print(f"  PASS  bus_resumes  max_x={bus_max:.1f}m")


def test_scenario_a_vehicles_exit_road():
    sim = SimulationEngine(scenario="A", config=SimConfig(total_cars_to_spawn=10, traffic_rate=0.3))
    sim.init_scenario()
    for _ in range(2500):
        sim.step()
    df = sim.get_results()
    past = (df.groupby("id")["x"].max() > sim.road_length).sum()
    assert past >= 5, f"too few vehicles exited road: {past}"
    print(f"  PASS  vehicles_exit  count={past}")


if __name__ == "__main__":
    print("=" * 60)
    print("SCENARIO A ROAD EXIT")
    print("=" * 60)
    failed = []
    for fn in (test_scenario_a_bus_resumes_after_dwell, test_scenario_a_vehicles_exit_road):
        try:
            fn()
        except AssertionError as e:
            failed.append((fn.__name__, str(e)))
            print(f"  FAIL  {fn.__name__}: {e}")
    print("=" * 60)
    sys.exit(1 if failed else 0)
