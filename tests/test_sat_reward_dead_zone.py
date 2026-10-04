#!/usr/bin/env python3
"""Bug 4: SAT-overlap reward has a punishment-free dead zone for 0 < area <= 1.0 m^2.

Under the DEFAULT shipped profile (sat_penalty_enabled=True, spongy_danger_zone_enabled=False,
i.e. the exp7satv9 profile), env.py's reward Term 5 has these branches, in order:
  - progress>=1.0                                       -> Term 4 (success), skips Term 5 entirely
  - elif _sat_enabled and _spongy: ...                   -> requires spongy=True, not our profile
  - elif _sat_enabled and _sat_area > 1.0: ...            -> binary terminal crash
  - elif not _spongy and not (_sat_enabled and _sat_area>0.0) and gap<=0.0 ...  -> explicitly
    gated OFF whenever sat_enabled and any overlap exists
For 0.0 < _sat_area <= 1.0 (a real, sideswipe-scale overlap) under the default profile, NONE of
these fire -- no terminal, no gradient, nothing. A real physical overlap produces zero reward
signal.

Technique: deep-copy the env before stepping, so two runs differing only in the monkeypatched
compute_sat_overlap_area() return value see bit-identical physics up to that point -- any reward
difference must come from Term 5, nothing else. Avoids depending on exact car/bus geometry to
hit a precise overlap area.
"""
import copy
import sys


import numpy as np

import busmerge.rl.env as ew
from busmerge.rl.env import BusMergeEnv
from busmerge.vehicle import Vehicle, CAR_PARAMS

ACTION = np.array([0.0, 0.0], dtype=np.float32)


def _make_env_with_nearby_car():
    """Default v9 profile (sat_penalty_enabled, non-spongy) with a guaranteed nearby car so
    compute_sat_overlap_area() is actually called (it's skipped entirely when no car is in
    the SAT scan window)."""
    env = BusMergeEnv(eval_mode=False, governor_disabled=True)
    env.reset()
    env.sat_penalty_enabled = True
    env.spongy_danger_zone_enabled = False
    # Car placed so rear_gap (bus rear bumper -> car front) is comfortably POSITIVE --
    # bus.position is the bus's front reference and BUS_LENGTH (~11m) is behind it, so a car
    # only 5m behind bus.position is still within the bus's own footprint (gap<0), which
    # would spuriously trip the OLD 1D fallback crash branch (gap<=0.0) regardless of SAT
    # area and contaminate the comparison. 20m clears the bus length with margin.
    car = Vehicle(4, env.bus.position - 20.0, env.bus.velocity, CAR_PARAMS)
    env.vehicles = [car]
    gap, _, _, _, _, nearest = env._scan_nearest_car()
    assert nearest is not None, "setup invalid: no car in SAT scan window"
    assert gap > 0.0, f"setup invalid: rear_gap={gap} must be positive to isolate SAT-only branches"
    return env


def _step_with_area(env, area, *, spongy=False):
    """Deep-copy env, force compute_sat_overlap_area() to return a fixed value, step once."""
    e = copy.deepcopy(env)
    e.spongy_danger_zone_enabled = spongy
    original = ew.compute_sat_overlap_area
    ew.compute_sat_overlap_area = lambda *a, **k: area
    try:
        _, reward, done, info = e.step(ACTION)
    finally:
        ew.compute_sat_overlap_area = original
    return reward, done, e


# ---------------------------------------------------------------------------

def test_dead_zone_now_penalized():
    """MUST FAIL TODAY, PASS AFTER FIX. area=0.5 must be strictly more punishing than area=0.0,
    and must NOT be terminal (preserves the existing >1.0 binary-terminal semantics)."""
    env = _make_env_with_nearby_car()
    reward_0, done_0, _ = _step_with_area(env, 0.0)
    reward_half, done_half, _ = _step_with_area(env, 0.5)
    assert done_0 is False and done_half is False, (
        f"a 0.5 m^2 overlap must not be terminal: done_0={done_0} done_half={done_half}"
    )
    assert reward_half < reward_0, (
        f"area=0.5 should be more punishing than area=0.0: {reward_half} !< {reward_0}"
    )
    print(f"  PASS  dead_zone_now_penalized  area=0.0 reward={reward_0:.4f}  "
          f"area=0.5 reward={reward_half:.4f}")


def test_area_tiny_positive_graded():
    """area=1e-6 (just above the dead zone's lower edge) must already be graded, non-terminal."""
    env = _make_env_with_nearby_car()
    reward_0, done_0, _ = _step_with_area(env, 0.0)
    reward_tiny, done_tiny, _ = _step_with_area(env, 1e-6)
    assert done_tiny is False
    assert reward_tiny < reward_0, f"tiny overlap should still be penalized: {reward_tiny} !< {reward_0}"
    print(f"  PASS  area_tiny_positive_graded  delta={reward_0 - reward_tiny:.6f}")


def test_area_exactly_1_0_still_graded():
    """area=1.0 exactly falls in the new graded branch (0.0 < area <= 1.0), not the existing
    binary terminal (which requires area > 1.0, strict)."""
    env = _make_env_with_nearby_car()
    reward_0, _, _ = _step_with_area(env, 0.0)
    reward_1, done_1, _ = _step_with_area(env, 1.0)
    assert done_1 is False, "area==1.0 must not be terminal (that boundary belongs to >1.0)"
    assert reward_1 < reward_0, f"area=1.0 should be penalized: {reward_1} !< {reward_0}"
    print(f"  PASS  area_exactly_1_0_still_graded  reward={reward_1:.4f}  done={done_1}")


def test_area_just_above_1_0_unchanged_binary_terminal():
    """REGRESSION GUARD -- must pass both before and after the fix. area=1.0+eps must still hit
    the existing v9 binary-terminal crash path untouched by this fix."""
    env = _make_env_with_nearby_car()
    reward, done, e = _step_with_area(env, 1.0 + 1e-9)
    assert done is True and e.last_crash is True, "area>1.0 must still be the binary terminal crash"
    assert reward <= -2500.0, f"expected terminal crash penalty <= -2500, got {reward}"
    print(f"  PASS  area_just_above_1_0_unchanged_binary_terminal  reward={reward:.4f} done={done}")


def test_area_zero_no_sat_penalty():
    """area=0.0 exactly must never trigger a SAT crash penalty (no false positive on genuine
    non-overlap). Control case -- passes both before and after the fix."""
    env = _make_env_with_nearby_car()
    reward, done, e = _step_with_area(env, 0.0)
    assert done is False and e.last_crash is False
    assert reward > -2500.0, f"area=0.0 should not incur any SAT crash penalty, got {reward}"
    print(f"  PASS  area_zero_no_sat_penalty  reward={reward:.4f}")


def test_spongy_profile_unaffected():
    """REGRESSION GUARD -- must pass both before and after the fix. The existing spongy-profile
    branch (v10, gated on spongy_danger_zone_enabled=True) must be byte-for-byte unchanged: for
    0 < area <= 3.0, spongy already applies -50.0*area, non-terminal. The fix must be additive
    to the non-spongy branch only."""
    env = _make_env_with_nearby_car()
    reward_0, done_0, _ = _step_with_area(env, 0.0, spongy=True)
    reward_half, done_half, _ = _step_with_area(env, 0.5, spongy=True)
    assert done_0 is False and done_half is False
    expected_delta = 50.0 * 0.5
    actual_delta = reward_0 - reward_half
    assert abs(actual_delta - expected_delta) < 1e-6, (
        f"spongy branch formula changed: delta={actual_delta} != expected {expected_delta}"
    )
    print(f"  PASS  spongy_profile_unaffected  delta={actual_delta:.4f} == expected {expected_delta:.4f}")


if __name__ == "__main__":
    print("=" * 60)
    print("SAT REWARD DEAD ZONE (Bug 4)")
    print("=" * 60)
    tests = [
        test_dead_zone_now_penalized,
        test_area_tiny_positive_graded,
        test_area_exactly_1_0_still_graded,
        test_area_just_above_1_0_unchanged_binary_terminal,
        test_area_zero_no_sat_penalty,
        test_spongy_profile_unaffected,
    ]
    failures = []
    for fn in tests:
        try:
            fn()
        except AssertionError as e:
            failures.append((fn.__name__, str(e)))
            print(f"  FAIL  {fn.__name__}: {e}")
    print("=" * 60)
    if failures:
        print(f"{len(failures)}/{len(tests)} FAILED")
        sys.exit(1)
    print("ALL PASSED")
