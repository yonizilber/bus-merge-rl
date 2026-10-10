"""Forced situations for behavioural tests: the app engine, an empty road, and cars placed on purpose.

The bus drives in and stops at ``stop_x`` exactly as in the app. The moment boarding ends, each car in
``cars`` (front position relative to the bus front, speed) is placed in the lane. Everything after that
is the brain and the physics.
"""
from __future__ import annotations

import random

import numpy as np
import pandas as pd
import torch

from busmerge.config import SimConfig
from busmerge.rl.merge_success import PRODUCTION_MERGE_LATERAL_THRESHOLD
from busmerge.simulation import SimulationEngine
from busmerge.vehicle import BusState, Vehicle, sample_vehicle_params

STALL_WINDOW_S = 3.0      # a bus out of the bay that holds its lateral position this long has stalled
STALL_RANGE_M = 0.02


def run_merge_scenario(brain, stop_x: float, cars=(), seed: int = 0, after_s: float = 30.0):
    """Run the scenario; return the frame log and the time boarding ended."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    sim = SimulationEngine("B", SimConfig(traffic_rate=0.0, total_cars_to_spawn=0), brain_path=str(brain),
                           governor_disabled=True)
    sim.init_scenario()
    bus = next(v for v in sim.vehicles if v.id == 999)
    bus.set_stop_schedule(stop_x, sim.cfg.bus_dwell_time)
    while bus.state != BusState.WAITING_TO_MERGE:
        sim.step()
        assert sim.time < 120.0, "the bus never finished boarding"
    for i, (dx, speed) in enumerate(cars):
        _, params = sample_vehicle_params("Mid")
        sim.vehicles.append(Vehicle(500 + i, bus.position + dx, speed, params))
    boarding_ended = sim.time
    while sim.time - boarding_ended < after_s:
        sim.step()
    return sim.get_results(), boarding_ended


def bus_after(df: pd.DataFrame, t0: float) -> pd.DataFrame:
    return df[(df["type"] == "Bus") & (df["time"] >= t0)].sort_values("time")


def merge_time(df: pd.DataFrame, t0: float):
    """Seconds from the end of boarding until the bus reaches the merge threshold, or None."""
    b = bus_after(df, t0)
    done = b[b["lateral_offset"] >= PRODUCTION_MERGE_LATERAL_THRESHOLD]
    return float(done["time"].iloc[0] - t0) if len(done) else None


def stalled(df: pd.DataFrame, t0: float, dt: float = 0.1) -> bool:
    """True if the bus, out of the bay but short of the merge threshold, held its lateral position
    (within STALL_RANGE_M) for STALL_WINDOW_S: the half-way stop of the v11 reward hack."""
    lat = bus_after(df, t0)["lateral_offset"].to_numpy()
    n = int(round(STALL_WINDOW_S / dt))
    for i in range(len(lat) - n):
        w = lat[i:i + n]
        if w.max() < PRODUCTION_MERGE_LATERAL_THRESHOLD and w.min() > -3.0 and w.max() - w.min() < STALL_RANGE_M:
            return True
    return False


def lateral_while_car_alongside(df: pd.DataFrame, t0: float) -> float:
    """Highest bus lateral position while any car overlaps the bus along the road (-inf if never)."""
    b = bus_after(df, t0).set_index("time")
    cars = df[(df["type"] == "Car") & (df["time"] >= t0)]
    highest = float("-inf")
    for t, rows in cars.groupby("time"):
        if t not in b.index:
            continue
        front, rear = float(b.at[t, "x"]), float(b.at[t, "x"] - b.at[t, "length"])
        if ((rows["x"] > rear) & (rows["x"] - rows["length"] < front)).any():
            highest = max(highest, float(b.at[t, "lateral_offset"]))
    return highest
