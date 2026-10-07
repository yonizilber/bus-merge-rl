"""Physical sanity checks on a finished run.

A simulation can "work" (the bus merges, nothing is flagged) and still contain moments that cannot
happen in reality: braking harder than tyres allow, a vehicle jumping backwards, a position that does
not follow from the speed, or two vehicles occupying the same space. These checks look at the frame
log only, so they are independent of whatever code produced it, and they count violations instead of
hiding them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from busmerge.geometry import compute_sat_overlap_area, vehicle_corners

MAX_DECEL_MS2 = 9.0        # the limit the vehicle model itself documents (hard braking on dry road)
DECEL_TOLERANCE = 0.5      # numerical slack on top of the limit
MAX_ACCEL_MS2 = 5.0        # no vehicle here can accelerate faster than this
OVERLAP_MIN_AREA_M2 = 0.01  # ignore numerical touching
OVERLAP_SCAN_M = 20.0
POSITION_TOLERANCE_M = 0.5  # |Δx − v·dt| allowed (the position update uses a mix of old and new speed)


@dataclass
class InvariantReport:
    frames: int = 0
    counts: dict = field(default_factory=lambda: {
        "decel_over_limit": 0, "accel_over_limit": 0, "negative_speed": 0,
        "backward_motion": 0, "position_jump": 0, "overlap": 0,
    })
    worst_decel: float = 0.0
    examples: dict = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def add(self, kind: str, example: dict) -> None:
        self.counts[kind] += 1
        self.examples.setdefault(kind, example)


def check_invariants(df: pd.DataFrame, dt: float = 0.1) -> InvariantReport:
    """Count physically impossible moments in a frame log (columns: time, id, type, x, v, length, width, total_lat)."""
    rep = InvariantReport(frames=int(df["time"].nunique()) if len(df) else 0)
    if df.empty:
        return rep

    d = df.sort_values(["id", "time"]).copy()
    g = d.groupby("id")
    d["dv"] = g["v"].diff()
    d["dx"] = g["x"].diff()
    d["dt_obs"] = g["time"].diff()
    d = d[d["dt_obs"].between(dt * 0.5, dt * 1.5)]  # skip a vehicle's first frame and gaps

    accel = d["dv"] / d["dt_obs"]
    rep.worst_decel = float(accel.min()) if len(accel) else 0.0
    for kind, mask in (
        ("decel_over_limit", accel < -(MAX_DECEL_MS2 + DECEL_TOLERANCE)),
        ("accel_over_limit", accel > MAX_ACCEL_MS2),
        ("negative_speed", d["v"] < -1e-6),
        ("backward_motion", d["dx"] < -1e-6),
        ("position_jump", (d["dx"] - d["v"] * d["dt_obs"]).abs() > POSITION_TOLERANCE_M),
    ):
        for _, row in d[mask].iterrows():
            rep.add(kind, {"time": float(row["time"]), "id": int(row["id"]), "type": row["type"],
                           "v": float(row["v"]), "dv": float(row["dv"]), "dx": float(row["dx"])})

    # Overlap: real rotated rectangles; x is the front bumper (physics convention).
    for time_s, frame in df.groupby("time"):
        if len(frame) < 2:
            continue
        rows = frame.to_dict("records")
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a_, b_ = rows[i], rows[j]
                if abs(a_["x"] - b_["x"]) > OVERLAP_SCAN_M:
                    continue
                area = compute_sat_overlap_area(
                    vehicle_corners(a_["x"], a_["total_lat"], a_["length"], a_["width"], np.radians(a_["heading_deg"])),
                    vehicle_corners(b_["x"], b_["total_lat"], b_["length"], b_["width"], np.radians(b_["heading_deg"])),
                )
                if area > OVERLAP_MIN_AREA_M2:
                    rep.add("overlap", {"time": float(time_s), "ids": (int(a_["id"]), int(b_["id"])), "area_m2": round(area, 3)})
    return rep

    d = df.sort_values(["id", "time"]).copy()
    g = d.groupby("id")
    d["dv"] = g["v"].diff()
    d["dx"] = g["x"].diff()
    d["dt_obs"] = g["time"].diff()
    d = d[d["dt_obs"].between(dt * 0.5, dt * 1.5)]  # skip a vehicle's first frame and gaps

    accel = d["dv"] / d["dt_obs"]
    rep.worst_decel = float(accel.min()) if len(accel) else 0.0
    for kind, mask in (
        ("decel_over_limit", accel < -(MAX_DECEL_MS2 + DECEL_TOLERANCE)),
        ("accel_over_limit", accel > MAX_ACCEL_MS2),
        ("negative_speed", d["v"] < -1e-6),
        ("backward_motion", d["dx"] < -1e-6),
        ("position_jump", (d["dx"] - d["v"] * d["dt_obs"]).abs() > POSITION_TOLERANCE_M),
    ):
        for _, row in d[mask].iterrows():
            rep.add(kind, {"time": float(row["time"]), "id": int(row["id"]), "type": row["type"],
                           "v": float(row["v"]), "dv": float(row["dv"]), "dx": float(row["dx"])})

    # Overlap: bounding boxes (x is the front bumper, so a vehicle occupies [x - length, x]).
    for t, f in df.groupby("time"):
        if len(f) < 2:
            continue
        x = f["x"].to_numpy(); L = f["length"].to_numpy(); lat = f["total_lat"].to_numpy(); w = f["width"].to_numpy()
        lon = np.minimum(x[:, None], x[None, :]) - np.maximum((x - L)[:, None], (x - L)[None, :]) > 0.05
        lateral = np.abs(lat[:, None] - lat[None, :]) < (w[:, None] + w[None, :]) / 2.0 - 0.05
        hit = np.triu(lon & lateral, k=1)
        for i, j in zip(*np.nonzero(hit)):
            rep.add("overlap", {"time": float(t), "ids": (int(f["id"].iloc[i]), int(f["id"].iloc[j]))})
    return rep
