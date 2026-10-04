"""Follower-behind-bus merge telemetry (simulation.py)."""
import numpy as np
import pandas as pd
import pytest

from busmerge.config import SimConfig
from busmerge.simulation import SimulationEngine
from busmerge.vehicle import Bus, BusState, Vehicle, CAR_PARAMS


def _engine_scenario_b():
    cfg = SimConfig(total_cars_to_spawn=15, traffic_rate=0.4, bus_dwell_time=5.0)
    eng = SimulationEngine(scenario="B", config=cfg, governor_disabled=True)
    eng.init_scenario()
    return eng


def test_follower_trace_columns_no_decel_rate():
    eng = _engine_scenario_b()
    for _ in range(200):
        eng.step()
    ft = eng.get_follower_trace()
    if ft.empty:
        pytest.skip("no follower trace in short run")
    assert "decel_rate" not in ft.columns
    assert "accel" in ft.columns
    assert "car_dv" in ft.columns
    assert "follower_switched" in ft.columns


def test_brake_note_uses_accel_not_dv_spike():
    """After follower ID switch, car_dv may spike but brake_note must follow accel."""
    bus = Bus(999, 300.0, 0.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.0
    bus.heading_angle = 0.1
    bus.velocity = 0.5

    eng = SimulationEngine(scenario="B", config=SimConfig(), governor_disabled=True)
    eng.time = 40.0
    eng._follower_trace_active = True
    eng._trace_prev_car_id = 1
    eng._trace_prev_car_v = 15.0  # stale velocity from previous follower

    car = Vehicle(2, 285.0, 5.0, CAR_PARAMS)
    car.acceleration = -2.8  # comfort tier for default CAR_PARAMS (comfort ~2.5)
    eng.vehicles = [bus, car]

    eng._record_bus_follower_trace(bus)
    row = eng.follower_trace[-1]
    assert row["follower_switched"] is True
    assert np.isnan(row["car_dv"])  # prev velocity cleared on switch — no bogus spike
    assert row["brake_note"] == "comfort"  # accel -2.8, not emergency from dv spike


def test_brake_note_emergency_from_accel():
    bus = Bus(999, 300.0, 0.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -1.0
    bus.heading_angle = 0.2
    bus.velocity = 0.8

    eng = SimulationEngine(scenario="B", config=SimConfig(), governor_disabled=True)
    eng.time = 41.0
    eng._follower_trace_active = True
    eng._trace_prev_car_id = 5
    eng._trace_prev_car_v = 5.0

    car = Vehicle(5, 286.0, 4.0, CAR_PARAMS)
    car.acceleration = -8.2
    eng.vehicles = [bus, car]

    eng._record_bus_follower_trace(bus)
    row = eng.follower_trace[-1]
    assert row["brake_note"] == "emergency"
    assert row["accel"] == pytest.approx(-8.2)


def test_summarize_follower_brakes_uses_accel():
    """Mirror app._summarize_follower_brakes — avoid importing streamlit in pytest."""
    ft = pd.DataFrame([
        {
            "time": 40.0, "bus_state": "WAITING_TO_MERGE", "bus_merge_progress": 0.5,
            "car_id": 5, "v": 5.0, "accel": -8.0, "brake_note": "emergency",
        },
        {
            "time": 40.1, "bus_state": "WAITING_TO_MERGE", "bus_merge_progress": 0.6,
            "car_id": 5, "v": 4.2, "accel": -4.0, "brake_note": "hard",
        },
    ])
    merge = ft[
        ft["bus_state"].isin(["WAITING_TO_MERGE", "MOVING"])
        & (ft["bus_merge_progress"].fillna(0.0) < 0.995)
    ]
    car = merge[merge["car_id"].notna()]
    worst = car.loc[car["accel"].idxmin()]
    assert float(worst["accel"]) == pytest.approx(-8.0)
    assert len(car[car["brake_note"].isin(["hard", "emergency"])]) == 2


def test_record_extends_into_moving_until_progress_complete():
    bus = Bus(999, 300.0, 2.0, CAR_PARAMS)
    bus.state = BusState.MOVING
    bus.lateral_offset = -0.05  # ~99% merge progress
    bus.heading_angle = 0.0

    eng = SimulationEngine(scenario="B", config=SimConfig(), governor_disabled=True)
    eng._follower_trace_active = True
    assert eng._should_record_follower_trace(bus) is True

    bus.lateral_offset = 0.0  # merge complete
    assert eng._should_record_follower_trace(bus) is False
