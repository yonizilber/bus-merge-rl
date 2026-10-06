"""
Shared state encoding for 4-, 7-, and 11-feature PPO stacks.
Training env and simulation.py must call the same function for a given feature_dim.

Human Perception Model v2 (sensor noise):
  - Distance / lateral: linear in gap (sharp close, vague far)
  - Speed: quadratic in gap (looming near, fuzzy far)
  - Acceleration (11-feat): heavy fog + low-pass lag
  - Temporal: Ornstein–Uhlenbeck biases — steady frame-to-frame, not i.i.d. jitter

Ground-truth physics for governor / shield / crash detection stay unnoised.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np
import torch

FEATURE_DIMS = (4, 7, 11)

# Reference range for distance scaling (m).
_NOISE_REF_RANGE_M = 50.0
_NOISE_DIST_FLOOR = 0.05
_NOISE_DIST_CEIL = 1.2
_SPD_FLOOR = 0.04

# Channel coefficients (k = noise_sigma slider / curriculum scale).
_GAP_SIGMA = 10.0
_LAT_SIGMA = 6.0
_RS_SIGMA = 5.0
_ACC_SIGMA = 12.0
_ACC_BIAS_SCALE = 1.5
_DIM_TINY_SCALE = 0.1
_HEADING_SIGMA = 2.0  # × dist_lin × 1°

# OU revert rate (1/s): low κ → long-lived misperception (~3 s at 0.35).
_OU_KAPPA = 0.35
_ACCEL_LP_ALPHA = 0.15


def distance_noise_scale(true_gap_m: float) -> float:
    """Linear distance index d_lin = clip(|gap|/50, 0.05, 1.2)."""
    return float(np.clip(
        abs(float(true_gap_m)) / _NOISE_REF_RANGE_M,
        _NOISE_DIST_FLOOR,
        _NOISE_DIST_CEIL,
    ))


def speed_noise_scale(true_gap_m: float) -> float:
    """Quadratic speed index max((gap/50)², SPD_FLOOR²)."""
    d = abs(float(true_gap_m)) / _NOISE_REF_RANGE_M
    return max(d * d, _SPD_FLOOR * _SPD_FLOOR)


def perception_noise_sigmas(base_sigma: float, true_gap_m: float) -> dict[str, float]:
    """Per-channel stationary std-devs for OU biases (Human Perception Model v2)."""
    k = float(base_sigma)
    if k <= 0.0:
        return {}
    d_lin = distance_noise_scale(true_gap_m)
    d_spd = speed_noise_scale(true_gap_m)
    d_acc = d_spd
    tiny = k * _DIM_TINY_SCALE
    return {
        "gap": k * _GAP_SIGMA * d_lin,
        "lat": k * _LAT_SIGMA * d_lin,
        "rel_speed": k * _RS_SIGMA * d_spd,
        "car_speed": k * _RS_SIGMA * d_spd,
        "car_accel": k * _ACC_SIGMA * d_acc + k * _ACC_BIAS_SCALE,
        "rel_accel": k * _ACC_SIGMA * d_acc + k * _ACC_BIAS_SCALE,
        "car_heading": k * _HEADING_SIGMA * d_lin * np.radians(1.0),
        "width": tiny,
        "length": tiny,
    }


@dataclass
class PerceptionNoiseState:
  """Slow-varying perception biases — one OU state per observable channel."""

  tracked_car_id: Optional[int] = None
  gap_bias: float = 0.0
  lat_bias: float = 0.0
  rel_speed_bias: float = 0.0
  car_speed_bias: float = 0.0
  car_accel_bias: float = 0.0
  rel_accel_bias: float = 0.0
  car_heading_bias: float = 0.0
  width_bias: float = 0.0
  length_bias: float = 0.0
  _filt_car_accel: float = field(default=0.0, repr=False)
  _filt_rel_accel: float = field(default=0.0, repr=False)

  def reset(self, car_id: Optional[int] = None) -> None:
      self.tracked_car_id = car_id
      self.gap_bias = 0.0
      self.lat_bias = 0.0
      self.rel_speed_bias = 0.0
      self.car_speed_bias = 0.0
      self.car_accel_bias = 0.0
      self.rel_accel_bias = 0.0
      self.car_heading_bias = 0.0
      self.width_bias = 0.0
      self.length_bias = 0.0
      self._filt_car_accel = 0.0
      self._filt_rel_accel = 0.0


def _ou_step(bias: float, sigma: float, dt: float, kappa: float = _OU_KAPPA) -> float:
    """One Ornstein–Uhlenbeck step; stationary std ≈ sigma."""
    if sigma <= 0.0 or dt <= 0.0:
        return bias
    drift = -kappa * bias * dt
    diffusion = np.sqrt(2.0 * kappa) * sigma * np.sqrt(dt) * np.random.randn()
    return float(bias + drift + diffusion)


def step_perception_noise(
    state: PerceptionNoiseState,
    base_sigma: float,
    true_gap_m: float,
    dt: float,
    car_id: Optional[int] = None,
) -> None:
    """Advance steady perception biases; reset when the tracked car changes."""
    if base_sigma <= 0.0:
        return

    if car_id != state.tracked_car_id:
        state.reset(car_id)

    sig = perception_noise_sigmas(base_sigma, true_gap_m)
    state.gap_bias = _ou_step(state.gap_bias, sig["gap"], dt)
    state.lat_bias = _ou_step(state.lat_bias, sig["lat"], dt)
    state.rel_speed_bias = _ou_step(state.rel_speed_bias, sig["rel_speed"], dt)
    state.car_speed_bias = _ou_step(state.car_speed_bias, sig["car_speed"], dt)
    state.car_accel_bias = _ou_step(state.car_accel_bias, sig["car_accel"], dt)
    state.rel_accel_bias = _ou_step(state.rel_accel_bias, sig["rel_accel"], dt)
    state.car_heading_bias = _ou_step(state.car_heading_bias, sig["car_heading"], dt)
    state.width_bias = _ou_step(state.width_bias, sig["width"], dt)
    state.length_bias = _ou_step(state.length_bias, sig["length"], dt)


def apply_sensor_noise(
    base_sigma: float,
    merge_progress: float,
    bus_heading_rad: float,
    lon_dist: float,
    lat_clearance: float,
    car_speed: float,
    car_accel: float,
    car_width: float,
    car_length: float,
    rel_speed: float,
    rel_accel: float,
    car_heading_rad: float,
    *,
    noise_state: Optional[PerceptionNoiseState] = None,
    dt: float = 0.1,
    car_id: Optional[int] = None,
) -> Tuple[float, float, float, float, float, float, float, float, float, float, float]:
    """
    Perturb exogenous perception features before state encoding.

    Self-state (progress, bus heading) is noise-free — the bus knows its own pose.
    When noise_state is provided, biases evolve via OU (steady perception).
    Without noise_state, a one-shot ephemeral state is used (tests / legacy).
    """
    if base_sigma <= 0.0:
        return (
            merge_progress, bus_heading_rad, lon_dist, lat_clearance,
            car_speed, car_accel, car_width, car_length,
            rel_speed, rel_accel, car_heading_rad,
        )

    ephemeral = noise_state is None
    if ephemeral:
        noise_state = PerceptionNoiseState()

    step_perception_noise(noise_state, base_sigma, lon_dist, dt, car_id)

    raw_car_accel = car_accel + noise_state.car_accel_bias
    raw_rel_accel = rel_accel + noise_state.rel_accel_bias
    a = _ACCEL_LP_ALPHA
    noise_state._filt_car_accel = (1.0 - a) * noise_state._filt_car_accel + a * raw_car_accel
    noise_state._filt_rel_accel = (1.0 - a) * noise_state._filt_rel_accel + a * raw_rel_accel

    return (
        merge_progress,
        bus_heading_rad,
        lon_dist + noise_state.gap_bias,
        lat_clearance + noise_state.lat_bias,
        car_speed + noise_state.car_speed_bias,
        noise_state._filt_car_accel,
        car_width + noise_state.width_bias,
        car_length + noise_state.length_bias,
        rel_speed + noise_state.rel_speed_bias,
        noise_state._filt_rel_accel,
        car_heading_rad + noise_state.car_heading_bias,
    )


def encode_features(
    feature_dim: int,
    merge_progress: float,
    bus_heading_rad: float,
    lon_dist: float,
    lat_clearance: float,
    car_speed: float,
    car_accel: float,
    car_width: float,
    car_length: float,
    rel_speed: float,
    rel_accel: float,
    car_heading_rad: float,
    noise_sigma: float = 0.0,
    *,
    noise_state: Optional[PerceptionNoiseState] = None,
    dt: float = 0.1,
    car_id: Optional[int] = None,
) -> np.ndarray:
    """Normalised state vector; ranges are the single definition used by the engine and the training env."""
    if feature_dim not in FEATURE_DIMS:
        raise ValueError(f"feature_dim must be one of {FEATURE_DIMS}, got {feature_dim}")

    if noise_sigma > 0.0:
        (
            merge_progress, bus_heading_rad, lon_dist, lat_clearance,
            car_speed, car_accel, car_width, car_length,
            rel_speed, rel_accel, car_heading_rad,
        ) = apply_sensor_noise(
            noise_sigma,
            merge_progress, bus_heading_rad, lon_dist, lat_clearance,
            car_speed, car_accel, car_width, car_length,
            rel_speed, rel_accel, car_heading_rad,
            noise_state=noise_state,
            dt=dt,
            car_id=car_id,
        )

    merge_progress = float(np.clip(merge_progress, 0.0, 1.0))
    bus_heading_rad = float(np.clip(bus_heading_rad, -0.54, 0.54))
    lon_dist = float(np.clip(lon_dist, -10.0, 60.0))
    lat_clearance = float(np.clip(lat_clearance, -2.0, 4.0))
    car_speed = float(np.clip(car_speed, 0.0, 20.0))
    car_accel = float(np.clip(car_accel, -9.0, 3.0))
    car_width = float(np.clip(car_width, 1.70, 2.05))
    car_length = float(np.clip(car_length, 3.5, 5.5))
    rel_speed = float(np.clip(rel_speed, -15.0, 15.0))
    rel_accel = float(np.clip(rel_accel, -15.0, 15.0))
    car_heading_rad = float(np.clip(car_heading_rad, -0.15, 0.15))

    p_n = merge_progress
    ang_n = bus_heading_rad / 0.54
    lon_n = (lon_dist + 10.0) / 70.0
    lat_n = (lat_clearance + 2.0) / 6.0
    spd_n = car_speed / 20.0
    acc_n = car_accel / 9.0
    wid_n = (car_width - 1.85) / 0.20
    len_n = (car_length - 4.5) / 1.0
    rs_n = rel_speed / 15.0
    ra_n = rel_accel / 15.0
    ca_n = car_heading_rad / 0.15

    if feature_dim == 4:
        return np.array([p_n, ang_n, lon_n, rs_n], dtype=np.float32)
    if feature_dim == 7:
        return np.array([p_n, ang_n, lon_n, lat_n, spd_n, wid_n, rs_n], dtype=np.float32)
    return np.array(
        [p_n, ang_n, lon_n, lat_n, spd_n, acc_n, wid_n, len_n, rs_n, ra_n, ca_n],
        dtype=np.float32,
    )


FEATURE_NAMES = {
    4: ("progress", "bus heading", "gap", "relative speed"),
    7: ("progress", "bus heading", "gap", "lateral clearance", "car speed", "car width", "relative speed"),
    11: ("progress", "bus heading", "gap", "lateral clearance", "car speed", "car acceleration",
         "car width", "car length", "relative speed", "relative acceleration", "car heading"),
}


def infer_state_dim_from_checkpoint(path: str) -> int:
    """Read actor_trunk input size from a .pth file (11feat/7feat/4feat trunk arch)."""
    try:
        sd = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:
        sd = torch.load(path, map_location="cpu")
    if "actor_trunk.0.weight" in sd:
        return int(sd["actor_trunk.0.weight"].shape[1])
    if "actor_mean.0.weight" in sd:
        return int(sd["actor_mean.0.weight"].shape[1])
    return 11


def feature_dim_from_run_tag(run_tag: str) -> int | None:
    if "4feat" in run_tag or run_tag.endswith("_4"):
        return 4
    if "7feat" in run_tag or run_tag.endswith("_7"):
        return 7
    if "11feat" in run_tag:
        return 11
    return None
