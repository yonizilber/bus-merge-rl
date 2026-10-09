"""The training env's crash judge must agree with the acceptance gate (busmerge.invariants).

Contact = the bus body and any car body overlap by more than OVERLAP_MIN_AREA_M2 (exact rotated
polygons, front-bumper convention, bus lateral position including its lane drift). Contact is
judged before success and ends the episode as a crash. History: until 2026-10 the env looked only at
the single nearest car, used the bus's lateral_offset without lane drift, treated overlaps up to
1 m^2 as a small per-frame penalty, and let a merge that touched a car count as a success.
"""
import copy

import numpy as np
import pytest

import busmerge.rl.env as ew
from busmerge.invariants import OVERLAP_MIN_AREA_M2
from busmerge.rl.env import BusMergeEnv
from busmerge.vehicle import CAR_PARAMS, Vehicle

ACTION = np.array([0.0, 0.0], dtype=np.float32)


def _env_with_car_alongside():
    """SAT profile (exp7sat*, non-spongy) with one car beside the bus's rear half."""
    env = BusMergeEnv(eval_mode=False, governor_disabled=True)
    env.reset()
    env.sat_penalty_enabled = True
    env.spongy_danger_zone_enabled = False
    env.vehicles = [Vehicle(4, env.bus.position - 8.0, env.bus.velocity, CAR_PARAMS)]
    return env


def _step_with_area(env, area, *, spongy=False):
    """Deep-copy the env, force the polygon overlap to ``area`` for every car, step once."""
    e = copy.deepcopy(env)
    e.spongy_danger_zone_enabled = spongy
    original = ew.compute_sat_overlap_area
    ew.compute_sat_overlap_area = lambda *a, **k: area
    try:
        _, reward, done, _ = e.step(ACTION)
    finally:
        ew.compute_sat_overlap_area = original
    return reward, done, e


def test_no_contact_is_not_a_crash():
    reward, done, e = _step_with_area(_env_with_car_alongside(), 0.0)
    assert not done and not e.last_crash


def test_touching_below_the_gate_threshold_is_not_a_crash():
    _, done, e = _step_with_area(_env_with_car_alongside(), OVERLAP_MIN_AREA_M2 * 0.5)
    assert not done and not e.last_crash


@pytest.mark.parametrize("area", [OVERLAP_MIN_AREA_M2 * 2, 0.12, 0.5, 1.5])
def test_any_contact_the_gate_counts_is_a_terminal_crash(area):
    reward, done, e = _step_with_area(_env_with_car_alongside(), area)
    assert done and e.last_crash and not e.last_success
    assert reward <= -2500.0


def test_contact_on_the_completing_frame_is_a_crash_not_a_success():
    env = _env_with_car_alongside()
    env.bus.lateral_offset = -0.05          # the merge completes on this step
    _, done, e = _step_with_area(env, 0.5)
    assert done and e.last_crash and not e.last_success


def test_contact_with_a_car_that_is_not_the_nearest_is_seen():
    """The old judge looked only at the nearest car; a second car scraping the bus was invisible."""
    env = BusMergeEnv(eval_mode=False, governor_disabled=True)
    env.reset()
    bus = env.bus
    bus.position, bus.lateral_offset, bus.heading_angle, bus.lane_drift = 300.0, -2.5, 0.0, 0.0
    nearest = Vehicle(1, 301.0, 5.0, CAR_PARAMS)        # just ahead, clear of the bus laterally
    nearest.lateral_offset, nearest.lane_drift = 0.5, 0.0
    scraper = Vehicle(2, 295.0, 5.0, CAR_PARAMS)        # beside the bus body, 0.15 m into it
    scraper.lateral_offset, scraper.lane_drift = -0.5, 0.0
    env.vehicles = [nearest, scraper]
    assert env._scan_nearest_car()[5] is nearest
    assert env._bus_contact_area() > OVERLAP_MIN_AREA_M2


def test_spongy_profile_keeps_its_own_rules():
    """The experimental v10 profile is unchanged: overlap up to 3 m^2 costs 50/m^2, not terminal."""
    env = _env_with_car_alongside()
    reward_0, done_0, _ = _step_with_area(env, 0.0, spongy=True)
    reward_half, done_half, _ = _step_with_area(env, 0.5, spongy=True)
    assert not done_0 and not done_half
    assert reward_0 - reward_half == pytest.approx(50.0 * 0.5)
