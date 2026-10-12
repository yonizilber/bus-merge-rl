"""Mechanical limits of the vehicle model.

- **Bicycle model (#12).** Every steering update made during a real run, by every vehicle and every
  controller, respects the vehicle's own limits. The steering angle changes at most at the steering
  rate and stays within the maximum angle. The heading changes exactly as v·tan(δ)/wheelbase. The
  lateral position follows from the heading. Nothing turns or slides while standing still.
- **Speed continuity.** Speed never jumps: from one 0.1 s step to the next it changes only within the
  braking and acceleration limits.
- **Known gaps, as strict `xfail`.** The model has no vehicle mass and one braking limit for every
  vehicle (BUGS O17). Acceleration can switch from cruising to full braking within a single step,
  with no brake actuation lag (BUGS O18).
"""
import numpy as np
import pytest

from busmerge.config import SimConfig
from busmerge.evaluation import APP_DEFAULTS, run_episode
from busmerge.invariants import DECEL_TOLERANCE, MAX_ACCEL_MS2, MAX_DECEL_MS2
from busmerge.paths import DEFAULT_BRAIN
from busmerge.vehicle import CAR_PARAMS, Bus, BusState, Vehicle, sample_vehicle_params

DT = 0.1
# Brake actuation: a real brake system needs roughly 0.15-0.3 s to build full pressure, which caps
# the rate of change of deceleration at about 30-60 m/s³. There is no single standard value; 50 m/s³
# here means full 9 m/s² braking can be reached no faster than in about 0.2 s.
JERK_LIMIT_MS3 = 50.0


def _run(seed: int = 2000):
    cfg = SimConfig(**{**APP_DEFAULTS, "total_cars_to_spawn": 30})
    return run_episode("B", cfg, str(DEFAULT_BRAIN), governor_disabled=True, seed=seed).get_results()


def test_every_steering_update_in_a_run_respects_the_bicycle_model(monkeypatch):
    violations, updates = [], 0
    original = Vehicle.apply_steering

    def checked(self, delta_target, dt):
        nonlocal updates
        steer0, heading0, lat0, v = self.steer_angle, self.heading_angle, self.lateral_offset, self.velocity
        original(self, delta_target, dt)
        updates += 1
        p = self.params
        rate, max_steer = np.radians(p.steer_rate_deg_per_s), np.radians(p.max_steer_angle_deg)
        problems = []
        if abs(self.steer_angle - steer0) > rate * dt + 1e-12:
            problems.append("steering faster than the steering rate")
        if abs(self.steer_angle) > max_steer + 1e-9:
            problems.append("steering beyond the maximum angle")
        if not np.isclose(self.heading_angle - heading0, v * np.tan(self.steer_angle) / max(p.wheelbase, 0.1) * dt,
                          rtol=1e-9, atol=1e-12):
            problems.append("heading change is not v·tan(δ)/L·dt")
        if not np.isclose(self.lateral_velocity, v * np.sin(self.heading_angle), rtol=1e-9, atol=1e-12):
            problems.append("lateral velocity is not v·sin(heading)")
        if not np.isclose(self.lateral_offset - lat0, self.lateral_velocity * dt, rtol=1e-9, atol=1e-12):
            problems.append("lateral position does not follow the lateral velocity")
        if v == 0.0 and (self.heading_angle != heading0 or self.lateral_offset != lat0):
            problems.append("turned or slid while standing still")
        if problems:
            violations.append((type(self).__name__, self.id, problems))

    monkeypatch.setattr(Vehicle, "apply_steering", checked)
    _run()
    assert updates > 5000, "the run must exercise the steering of many vehicles"
    assert not violations, violations[:5]


def test_steering_stays_within_its_limits_when_asked_for_the_impossible():
    # The controller is told to reach a line 100 m away, either side, at speed: the wheel turns at
    # its rate up to its maximum angle and no further.
    for target in (100.0, -100.0):
        bus = Bus(999, 0.0, 12.0, CAR_PARAMS)
        rate, max_steer = np.radians(bus.params.steer_rate_deg_per_s), np.radians(bus.params.max_steer_angle_deg)
        previous, widest = bus.steer_angle, 0.0
        for _ in range(100):
            bus.steer_toward(target, 12.0, DT)
            assert abs(bus.steer_angle - previous) <= rate * DT + 1e-12
            assert abs(bus.steer_angle) <= max_steer + 1e-12
            previous, widest = bus.steer_angle, max(widest, abs(bus.steer_angle))
        assert widest == pytest.approx(max_steer)    # the limit was reached, so it was really tested


def _accelerations(df):
    d = df.sort_values(["id", "time"]).copy()
    g = d.groupby("id")
    d["dt"] = g["time"].diff()
    d["dv"] = g["v"].diff()
    d["a"] = d["dv"] / d["dt"]
    d["jerk"] = d.groupby("id")["a"].diff() / d["dt"]
    return d[d["dt"].between(0.5 * DT, 1.5 * DT)]


def test_speed_never_steps():
    d = _accelerations(_run())
    assert (d["dv"] >= -(MAX_DECEL_MS2 + DECEL_TOLERANCE) * d["dt"] - 1e-9).all()
    assert (d["dv"] <= MAX_ACCEL_MS2 * d["dt"] + 1e-9).all()


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUGS O18: no brake actuation lag. Cars go from cruising to -9 m/s² (and back) in "
                          "one 0.1 s step: about 90-107 m/s³ at braking onset and release")
def test_acceleration_changes_within_brake_actuation_limits():
    d = _accelerations(_run(seed=2054)).dropna(subset=["jerk"])
    moving = d[d["v"] > 0.05]          # coming to rest drops the deceleration to 0 at once, as in reality
    worst = moving.loc[moving["jerk"].abs().idxmax()]
    assert abs(worst["jerk"]) <= JERK_LIMIT_MS3, (worst["type"], round(worst["v"], 2), round(worst["jerk"], 1))


def _emergency_stop(vehicle) -> tuple[float, float]:
    """Brake as hard as the model allows from 15 m/s toward a stopped obstacle just ahead.
    Returns (stopping distance, hardest deceleration)."""
    vehicle.velocity, vehicle.position = 15.0, 100.0
    obstacle = {"id": 7, "position": 100.0 + vehicle.params.min_gap + 4.5 + 1.0, "velocity": 0.0, "length": 4.5}
    start, hardest, v_prev = vehicle.position, 0.0, vehicle.velocity
    while vehicle.velocity > 0.0:
        vehicle.update_physics(DT, obstacle, bus=None)
        hardest = max(hardest, (v_prev - vehicle.velocity) / DT)
        v_prev = vehicle.velocity
    return vehicle.position - start, hardest


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUGS O17: no vehicle mass; every vehicle brakes up to the same 9 m/s², so an 11 m "
                          "bus stops as short as a compact car")
def test_a_bus_needs_more_room_to_stop_than_a_compact_car():
    _, compact_params = sample_vehicle_params("Compact")
    car_distance, car_decel = _emergency_stop(Vehicle(1, 100.0, 15.0, compact_params))
    bus = Bus(999, 100.0, 15.0, CAR_PARAMS)
    bus.state = BusState.MOVING
    bus_distance, bus_decel = _emergency_stop(bus)
    assert bus_decel < car_decel, (bus_decel, car_decel)
    assert bus_distance > car_distance, (bus_distance, car_distance)
