"""The one place where the agent's observation is built.

Both the production engine (the Streamlit app) and the training environment call
``build_observation`` so the policy sees exactly the same numbers in both worlds.
"""
from __future__ import annotations

from typing import Any, List, NamedTuple, Optional

import numpy as np

from busmerge.rl.feature_encoding import PerceptionNoiseState, encode_features
from busmerge.rl.merge_constants import BUS_WIDTH, LANE_WIDTH
from busmerge.rl.merge_success import merge_progress_from_lateral
from busmerge.rl.merge_yield import scan_nearest_car_for_merge

# What the agent is told when no car is within the scan window: "safe, no threat".
# gap = 60 m maps to the top of the normalised range; relative speed 0 maps to the middle.
EMPTY_ROAD_GAP_M = 60.0
DEFAULT_CAR_LENGTH_M = 4.5


class Observation(NamedTuple):
    """The encoded state plus the ground-truth facts the governor and shield also need."""

    state: np.ndarray
    merge_progress: float
    gap: float                 # bus rear to nearest car front; EMPTY_ROAD_GAP_M when no car
    nearest_speed: float
    nearest_width: float
    nearest_car: Any


def build_observation(
    bus,
    vehicles: List,
    prev_bus_velocity: float,
    dt: float,
    feature_dim: int,
    *,
    noise_sigma: float = 0.0,
    noise_state: Optional[PerceptionNoiseState] = None,
) -> Observation:
    """Encode what the bus driver perceives right now.

    ``prev_bus_velocity`` is the bus speed one decision ago (for the relative acceleration).
    Noise, when enabled, only affects the encoded ``state``; the returned facts are the truth.
    """
    gap, nearest_speed, nearest_accel, nearest_width, relative_speed, nearest_car = (
        scan_nearest_car_for_merge(bus, vehicles)
    )

    merge_progress = merge_progress_from_lateral(float(bus.lateral_offset))
    car_lat_offset = getattr(nearest_car, "total_lateral_offset", 0.0) if nearest_car else 0.0
    bus_lat_edge = bus.lateral_offset + BUS_WIDTH / 2.0
    lat_clearance = LANE_WIDTH - bus_lat_edge - (nearest_width - car_lat_offset)

    bus_accel = (bus.velocity - prev_bus_velocity) / dt
    rel_accel = bus_accel - nearest_accel
    car_length = nearest_car.params.length if nearest_car else DEFAULT_CAR_LENGTH_M
    car_heading = getattr(nearest_car, "heading_angle", 0.0) if nearest_car else 0.0

    if nearest_car is None:
        gap = EMPTY_ROAD_GAP_M
        relative_speed = 0.0

    state = encode_features(
        feature_dim,
        merge_progress, bus.heading_angle, gap, lat_clearance,
        nearest_speed, nearest_accel, nearest_width, car_length,
        relative_speed, rel_accel, car_heading,
        noise_sigma=noise_sigma,
        noise_state=noise_state if noise_sigma > 0.0 else None,
        dt=dt,
        car_id=nearest_car.id if nearest_car is not None else None,
    )
    return Observation(state, merge_progress, gap, nearest_speed, nearest_width, nearest_car)
