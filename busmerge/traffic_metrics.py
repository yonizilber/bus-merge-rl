"""Traffic measures that show whether a change to the simulation altered the traffic itself.

A brain can look better simply because there is less traffic around it, and a physics fix can make
cars drive jerkily. These numbers come from the frame log only and are reported next to the brain's results.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

COUNT_POINT_X = 300.0        # where flow is counted (the bus stop)
NEAR_BUS_M = 60.0            # "around the bus": cars whose front is within this distance


def traffic_metrics(df: pd.DataFrame) -> dict:
    """Flow past the stop, density around the bus when boarding ends, and car jerk."""
    cars = df[df["type"] == "Car"].sort_values(["id", "time"])
    out = {"flow_veh_per_min": float("nan"), "cars_near_bus_at_merge_start": float("nan"),
           "jerk_p95": float("nan"), "jerk_max": float("nan")}
    if cars.empty:
        return out

    # Flow: cars whose front crosses COUNT_POINT_X, per minute of the crossing window.
    prev_x = cars.groupby("id")["x"].shift()
    crossed = cars[(prev_x < COUNT_POINT_X) & (cars["x"] >= COUNT_POINT_X)]
    if len(crossed) >= 2:
        window_min = (crossed["time"].max() - crossed["time"].min()) / 60.0
        out["flow_veh_per_min"] = round(float((len(crossed) - 1) / window_min), 2) if window_min > 0 else float("nan")

    bus = df[df["type"] == "Bus"].sort_values("time")
    waiting = bus[bus["state"].astype(str) == "WAITING_TO_MERGE"]
    if not waiting.empty:
        t0, bx = float(waiting["time"].iloc[0]), float(waiting["x"].iloc[0])
        at = cars[np.isclose(cars["time"], t0)]
        out["cars_near_bus_at_merge_start"] = int(((at["x"] - bx).abs() <= NEAR_BUS_M).sum())

    # Jerk (m/s^3) of every car, from consecutive accelerations in the frame log.
    g = cars.groupby("id")
    dt = g["time"].diff()
    accel = g["v"].diff() / dt
    jerk = (accel.groupby(cars["id"]).diff() / dt).abs().dropna()
    if len(jerk):
        out["jerk_p95"] = round(float(jerk.quantile(0.95)), 2)
        out["jerk_max"] = round(float(jerk.max()), 1)
    return out
