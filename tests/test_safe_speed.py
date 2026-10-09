"""Unit tests for the strict-physics safe-speed law (busmerge/safe_speed.py)."""
import math

import pytest

from busmerge.rl.merge_constants import MAX_BRAKE_MS2
from busmerge.safe_speed import _bounded_acceleration, follower_acceleration
from busmerge.vehicle import CAR_PARAMS, Vehicle

DT = 0.1
B = 2.0


def test_free_road_keeps_the_driver_command():
    assert _bounded_acceleration(10.0, 1.2, gap=500.0, v_leader=10.0, b_comf=B, dt=DT) == pytest.approx(1.2)


def test_equal_speeds_with_room_do_not_brake():
    a = _bounded_acceleration(10.0, 0.0, gap=20.0, v_leader=10.0, b_comf=B, dt=DT)
    assert a == pytest.approx(0.0)


def test_bound_targets_the_safe_speed_for_a_stopped_leader():
    # v_safe = sqrt(0 + 2*2*16) = 8 m/s; from 10 m/s the bound asks (8 - 10) / 0.1 = -20, clipped at -9.
    a = _bounded_acceleration(10.0, 0.0, gap=16.0, v_leader=0.0, b_comf=B, dt=DT)
    assert a == pytest.approx(-MAX_BRAKE_MS2)


def test_bound_is_exact_when_within_physical_limits():
    v_safe = math.sqrt(2 * B * 16.0)                      # 8 m/s
    a = _bounded_acceleration(8.5, 0.0, gap=16.0, v_leader=0.0, b_comf=B, dt=DT)
    assert a == pytest.approx((v_safe - 8.5) / DT)       # -5 m/s^2


def test_never_brakes_beyond_the_physical_limit():
    assert _bounded_acceleration(20.0, -30.0, gap=0.0, v_leader=0.0, b_comf=B, dt=DT) == -MAX_BRAKE_MS2


def test_zero_gap_stopped_leader_brakes_to_a_stop():
    assert _bounded_acceleration(0.5, 1.0, gap=0.0, v_leader=0.0, b_comf=B, dt=DT) == pytest.approx(-5.0)


def test_never_closes_more_than_the_gap_in_one_step():
    # With a fast leader v_safe is large, but the follower may not close more than the 0.3 m gap.
    a = _bounded_acceleration(10.0, 3.0, gap=0.3, v_leader=10.0, b_comf=B, dt=DT)
    v_next = 10.0 + a * DT
    assert (v_next - 10.0) * DT <= 0.3 + 1e-9


def test_follower_keeps_min_gap_to_the_leader_rear():
    car = Vehicle(1, 100.0, 10.0, CAR_PARAMS)
    leader = {"id": 2, "position": 100.0 + CAR_PARAMS.min_gap + 4.5 + 10.0, "length": 4.5, "velocity": 0.0}
    a = follower_acceleration(car, leader, 0.0, DT)
    v_safe = math.sqrt(2 * CAR_PARAMS.comfortable_brake * 10.0)   # 10 m of room before the min_gap buffer
    assert a == pytest.approx(max((v_safe - 10.0) / DT, -MAX_BRAKE_MS2))


def test_no_leader_only_applies_the_physical_limit():
    car = Vehicle(1, 100.0, 10.0, CAR_PARAMS)
    assert follower_acceleration(car, None, -12.0, DT) == -MAX_BRAKE_MS2
    assert follower_acceleration(car, None, 1.0, DT) == 1.0
