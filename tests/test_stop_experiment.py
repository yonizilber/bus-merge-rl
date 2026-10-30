"""The stop-design experiment's data is what it claims to be.

- **Same cars.** With an arrival seed, the in-lane stop (A) and the bay (B) get the identical list of cars
  (arrival times, classes, sizes); a different seed gives a different list; without one, nothing changes.
- **No arrival is lost.** When the queue behind a bus stopped in the lane reaches the entry, scheduled cars wait and
  enter later, and every one of them finishes the road; at a low inflow nobody waits.
- **Trips.** The trip rows measure travel time from the scheduled arrival, and a vehicle still on the road is censored.
- **Runs repeat.** The same (scenario, rate, dwell, seed) gives identical rows.
- **Person-time.** Occupancy weights the two parts linearly, and ΔPT = PT(bay) − PT(lane).
"""
from types import SimpleNamespace

import pandas as pd
import pytest

from busmerge.config import SimConfig
from busmerge.evaluation import APP_DEFAULTS
from busmerge.experiments.stop_design import (Spec, paired_difference, person_time, queue_metrics, run_cell,
                                             trip_rows)
from busmerge.paths import DEFAULT_BRAIN
from busmerge.simulation import SimulationEngine


def _engine(scenario: str, seed, rate: float = 0.4, dwell: float = 15.0) -> SimulationEngine:
    cfg = SimConfig(**{**APP_DEFAULTS, "traffic_rate": rate, "bus_dwell_time": dwell, "arrival_seed": seed})
    sim = SimulationEngine(scenario=scenario, config=cfg, governor_disabled=True, load_brain=False)
    sim.init_scenario()
    return sim


def _cars(sim) -> list[tuple]:
    return [(round(t, 6), p.vehicle_class, round(p.length, 6), round(p.width, 6), round(f, 6))
            for t, p, f in sim.arrival_schedule]


def _run_to_end(sim, max_s: float = 900.0) -> None:
    while not sim.all_vehicles_finished() and sim.time < max_s:
        sim.step()


def test_both_designs_get_the_same_cars_for_the_same_seed():
    a, b = _engine("A", 4000), _engine("B", 4000)
    assert len(_cars(a)) > 20
    assert _cars(a) == _cars(b)


def test_a_different_seed_gives_different_cars():
    assert _cars(_engine("A", 4000)) != _cars(_engine("A", 4001))


def test_without_an_arrival_seed_the_app_arrivals_are_unchanged():
    sim = _engine("B", None)
    assert sim.arrival_schedule is None
    for _ in range(300):
        sim.step()
    assert sim.trip_log == {} and sim.cars_spawned_count > 0


@pytest.mark.parametrize("rate,dwell,blocked", [(0.5, 45.0, True), (0.1, 10.0, False)])
def test_cars_wait_at_a_blocked_entry_and_none_is_lost(rate, dwell, blocked):
    # Scenario A at 0.5 cars/s with a 45 s stop: the queue behind the bus reaches the entry (on `main` the old
    # arrivals would be lost there, BUGS O20). At 0.1 cars/s and a 10 s stop the entry is never blocked.
    sim = _engine("A", 4000, rate, dwell)
    scheduled = len(sim.arrival_schedule)
    _run_to_end(sim)
    cars = [t for t in sim.trip_log.values() if t["type"] == "Car"]
    assert len(cars) == scheduled and all(t["exit_t"] is not None for t in cars)
    longest_wait = max(t["entered_t"] - t["scheduled_t"] for t in cars)
    assert (longest_wait > 10.0) if blocked else (longest_wait < 3.0), longest_wait


def test_trip_rows_measure_from_the_scheduled_arrival_and_mark_censored_trips():
    sim = SimpleNamespace(road_length=1000.0, trip_log={
        999: {"type": "Bus", "class": "Bus", "scheduled_t": 0.0, "entered_t": 0.0, "exit_t": 120.0,
              "stopped_s": 15.0, "desired_speed": 10.0},
        1: {"type": "Car", "class": "Mid", "scheduled_t": 10.0, "entered_t": 14.0, "exit_t": 100.0,
            "stopped_s": 3.0, "desired_speed": 12.5},
        2: {"type": "Car", "class": "SUV", "scheduled_t": 20.0, "entered_t": 20.0, "exit_t": None,
            "stopped_s": 0.0, "desired_speed": 12.5}})
    rows = {r["vehicle_id"]: r for r in trip_rows(sim, "k")}
    assert rows[1]["travel_time_s"] == 90.0 and rows[1]["entry_wait_s"] == 4.0 and rows[1]["free_flow_s"] == 80.0
    assert rows[999]["travel_time_s"] == 120.0 and not rows[999]["censored"]
    assert rows[2]["censored"] and rows[2]["travel_time_s"] is None


def test_the_queue_is_the_stopped_cars_behind_the_bus_while_it_stands():
    frames = []
    for t in (10.0, 10.1):
        frames.append({"time": t, "type": "Bus", "state": "STOPPED_IN_LANE", "x": 300.0, "length": 11.0, "v": 0.0})
        frames += [{"time": t, "type": "Car", "state": "Cruising", "x": x, "length": 4.5, "v": v}
                   for x, v in ((286.0, 0.0), (279.0, 0.0), (272.0, 0.2), (250.0, 8.0), (310.0, 0.0))]
    q = queue_metrics(pd.DataFrame(frames))
    assert q["queue_max_cars"] == 3                     # the moving car and the car ahead of the bus do not count
    assert q["queue_max_m"] == pytest.approx(289.0 - 272.0 + 4.5)


def test_the_same_run_gives_the_same_rows():
    spec = Spec(name="t", brain=str(DEFAULT_BRAIN), scenarios=("A",), traffic_rates=(0.3,), dwell_times=(15,),
                seed_start=4000, seed_count=1, pilot_seeds=1, arrival_window_s=60.0, max_sim_time_s=600.0)
    first, second = run_cell(("A", 0.3, 15, 4000), spec), run_cell(("A", 0.3, 15, 4000), spec)
    assert first == second
    row, trips = first
    assert row["n_cars"] == len(trips) - 1 and not row["censored"]


def _runs() -> pd.DataFrame:
    return pd.DataFrame([
        {"scenario": "A", "traffic_rate": 0.3, "dwell_s": 15, "seed": 1, "bus_travel_time_s": 100.0, "cars_travel_time_s": 1000.0},
        {"scenario": "B", "traffic_rate": 0.3, "dwell_s": 15, "seed": 1, "bus_travel_time_s": 110.0, "cars_travel_time_s": 900.0},
    ])


def test_person_time_weights_each_part_by_its_occupancy():
    runs = _runs()
    one = person_time(runs, pax_car=1.0, pax_bus=50.0)
    two = person_time(runs, pax_car=2.0, pax_bus=50.0)
    assert list(two - one) == [1000.0, 900.0]            # doubling the car occupancy doubles only the cars' part


def test_delta_pt_is_bay_minus_lane():
    d = paired_difference(_runs(), pax_car=1.2, pax_bus=50.0).iloc[0]
    assert d["delta_bus_pt"] == pytest.approx(50 * 10.0)            # the bay costs the bus 10 s
    assert d["delta_car_pt"] == pytest.approx(1.2 * -100.0)         # and saves the cars 100 s
    assert d["delta_pt"] == pytest.approx(500.0 - 120.0)            # positive: the lane stop is better here
