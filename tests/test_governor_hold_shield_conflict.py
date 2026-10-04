#!/usr/bin/env python3
"""Bug 1: safety shield overrides a governor "hold" (gas=0.0) with a forward lunge.

governor_check()'s G1 branch returns _hold(steer) -- gas=0.0 -- when a trailing car
requires more than GOVERNOR_MAX_SAFE_DECEL to avoid contact and progress > 0.05
(reason="governor_hold"). apply_safety_shield() only special-cases
governor_reason == "governor_escape"; "governor_hold" falls through, and its
emergency_forward / late_overlap / late_push_through branches can force gas back UP
to 0.5-0.7, directly contradicting the governor's same-frame decision.

Part (i): direct unit tests on governor_check / apply_safety_shield, extending the
_FakeCar + hand-built-scalar pattern from test_governor_clear_road.py.
Part (ii): full-pipeline integration checks via a real SimulationEngine and a real
BusMergeEnv, confirming the fix holds in the actual per-frame code path in both
production and training, not just in isolated function calls.
"""
import sys


import numpy as np
import torch

from busmerge.rl.governor_logic import governor_check, apply_safety_shield
from busmerge.rl.merge_constants import GOVERNOR_MAX_SAFE_DECEL
from busmerge.config import SimConfig
from busmerge.simulation import SimulationEngine
from busmerge.vehicle import Bus, BusState, Vehicle, CAR_PARAMS
from busmerge.rl.env import BusMergeEnv


class _FakeCar:
    pass


LUNGE_CONDITIONS = ("emergency_forward", "late_overlap", "late_push_through")


# ---------------------------------------------------------------------------
# (i) Direct unit tests
# ---------------------------------------------------------------------------

def test_hold_fires_for_reported_scenario():
    """Sanity-check the governor half in isolation: req_decel = 3.0**2/(2*0.40)
    = 11.25 > GOVERNOR_MAX_SAFE_DECEL (9.0) -> governor_hold, gas=0.0."""
    car = _FakeCar()
    ok, s, g, r = governor_check(0.6, 0.6, 0.35, 0.40, -3.0, car)
    assert GOVERNOR_MAX_SAFE_DECEL == 9.0, "constant drifted, re-derive the scenario numbers"
    assert not ok and g == 0.0 and r == "governor_hold"
    print(f"  PASS  hold_fires_for_reported_scenario  steer={s} gas={g} reason={r!r}")


def test_shield_does_not_lunge_after_hold():
    """MUST FAIL TODAY, PASS AFTER FIX. Feed the exact governor_hold output into the shield."""
    steer, gas, cond = apply_safety_shield(
        0.6, 0.0, 0.35, 0.40, -3.0, nearest_speed=5.0, nearest_car=_FakeCar(),
        governor_reason="governor_hold",
    )
    assert gas <= 1e-6, f"shield lunged: gas={gas} cond={cond!r}"
    assert cond not in LUNGE_CONDITIONS, f"shield lunged via {cond!r}"
    print(f"  PASS  shield_does_not_lunge_after_hold  steer={steer} gas={gas} cond={cond!r}")


def test_emergency_stop_still_fires_when_gap_closes_within_frame():
    """gap=0.30, rel_speed=-3.0, dt=0.1 -> next_gap=0.0 exactly -> emergency_stop.
    Must be UNAFFECTED by the fix (already conservative, independent of hold-vs-lunge)."""
    steer, gas, cond = apply_safety_shield(
        0.6, 0.0, 0.35, 0.30, -3.0, nearest_speed=5.0, nearest_car=_FakeCar(),
        governor_reason="governor_hold",
    )
    assert (steer, gas, cond) == (0.0, 0.0, "emergency_stop")
    print(f"  PASS  emergency_stop_still_fires_when_gap_closes_within_frame  ({steer}, {gas}, {cond!r})")


def test_dead_zone_just_above_emergency_stop_boundary():
    """gap=0.31 -> next_gap=0.01>0, misses the within-frame guard -> pre-fix falls into
    emergency_forward. MUST FAIL TODAY, PASS AFTER FIX."""
    steer, gas, cond = apply_safety_shield(
        0.6, 0.0, 0.35, 0.31, -3.0, nearest_speed=5.0, nearest_car=_FakeCar(),
        governor_reason="governor_hold",
    )
    assert gas <= 1e-6, f"shield lunged in the dead zone: gas={gas} cond={cond!r}"
    assert cond not in LUNGE_CONDITIONS
    print(f"  PASS  dead_zone_just_above_emergency_stop_boundary  steer={steer} gas={gas} cond={cond!r}")


def test_progress_boundary_at_030():
    """progress=0.2999 (falls to the nearest_speed>=2.0 branch even pre-fix, already safe --
    a control case) vs progress=0.30 exactly (pre-fix: lunges; post-fix: must not, proving the
    fix isn't still silently gated only by the old progress>=0.30 check for the hold case)."""
    steer_a, gas_a, cond_a = apply_safety_shield(
        0.6, 0.0, 0.2999, 0.40, -3.0, nearest_speed=5.0, nearest_car=_FakeCar(),
        governor_reason="governor_hold",
    )
    assert gas_a <= 1e-6, f"control case unexpectedly lunged: gas={gas_a}"

    steer_b, gas_b, cond_b = apply_safety_shield(
        0.6, 0.0, 0.30, 0.40, -3.0, nearest_speed=5.0, nearest_car=_FakeCar(),
        governor_reason="governor_hold",
    )
    assert gas_b <= 1e-6, f"progress==0.30 boundary lunged: gas={gas_b} cond={cond_b!r}"
    print(f"  PASS  progress_boundary_at_030  progress=0.2999 gas={gas_a}  progress=0.30 gas={gas_b}")


def test_non_hold_reason_still_allowed_to_lunge():
    """NEGATIVE CONTROL -- same geometry, governor_reason="" (governor did not veto this
    frame). Must PASS both before and after the fix: proves the fix is scoped to
    governor_hold only and does not remove legitimate escape-forward safety behavior."""
    steer, gas, cond = apply_safety_shield(
        0.6, 0.6, 0.35, 0.40, -3.0, nearest_speed=5.0, nearest_car=_FakeCar(),
        governor_reason="",
    )
    assert steer == 1.0 and gas >= 0.5 and cond == "emergency_forward"
    print(f"  PASS  non_hold_reason_still_allowed_to_lunge  steer={steer} gas={gas} cond={cond!r}")


def test_late_overlap_respects_hold():
    """progress=0.70, gap=0.50, rel_speed=1.0 -> pre-fix hits the late_overlap gas-forcing
    branch unconditionally. MUST FAIL TODAY, PASS AFTER FIX."""
    steer, gas, cond = apply_safety_shield(
        0.6, 0.0, 0.70, 0.50, 1.0, nearest_speed=5.0, nearest_car=_FakeCar(),
        governor_reason="governor_hold",
    )
    assert gas <= 1e-6, f"late_overlap lunged: gas={gas} cond={cond!r}"
    assert cond not in LUNGE_CONDITIONS
    print(f"  PASS  late_overlap_respects_hold  steer={steer} gas={gas} cond={cond!r}")


def test_late_push_through_respects_hold():
    """gap=-1.0 (overlap), progress=0.70, rel_speed=-0.5 -> pre-fix hits late_push_through
    unconditionally. MUST FAIL TODAY, PASS AFTER FIX."""
    steer, gas, cond = apply_safety_shield(
        0.6, 0.0, 0.70, -1.0, -0.5, nearest_speed=5.0, nearest_car=_FakeCar(),
        governor_reason="governor_hold",
    )
    assert gas <= 1e-6, f"late_push_through lunged: gas={gas} cond={cond!r}"
    assert cond not in LUNGE_CONDITIONS
    print(f"  PASS  late_push_through_respects_hold  steer={steer} gas={gas} cond={cond!r}")


# ---------------------------------------------------------------------------
# (ii) Full-pipeline integration checks (production + training call sites)
# ---------------------------------------------------------------------------

def _build_hold_scenario_engine():
    """Real SimulationEngine + real Bus/Vehicle geometry reproducing gap~0.40,
    rel_speed~-3.0, progress~0.35 -- the same numbers as the direct unit tests, but
    derived from real positions/velocities through the real scan/encode/governor/shield
    pipeline, with the policy mocked so checkpoint weights don't matter."""
    eng = SimulationEngine(scenario="B", config=SimConfig(), governor_disabled=False)
    eng.brain.policy = lambda state_tensor: (torch.tensor([[0.6, 0.6]]), None, None)
    bus = Bus(999, 300.0, 2.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.275   # -> merge_progress ~0.35
    bus.heading_angle = 0.0
    car = Vehicle(4, 288.60, 5.0, CAR_PARAMS)   # rear_gap ~0.40, rel_speed = 2.0-5.0 = -3.0
    eng.vehicles = [bus, car]
    return eng, bus, car


def test_full_pipeline_no_lunge_after_hold_production():
    """MUST FAIL TODAY, PASS AFTER FIX. Real simulation.py._handle_bus_logic() call path."""
    eng, bus, car = _build_hold_scenario_engine()
    eng._handle_bus_logic(bus)
    assert bus.acceleration <= 0.0, (
        f"production lunged: bus.acceleration={bus.acceleration} "
        "(expected <=0.0, a braking/hold response, not the old ~2.0 lunge)"
    )
    print(f"  PASS  full_pipeline_no_lunge_after_hold_production  bus.acceleration={bus.acceleration}")


def test_full_pipeline_no_lunge_after_hold_training():
    """MUST FAIL TODAY, PASS AFTER FIX. Real busmerge/rl/env.py.step() call path."""
    env = BusMergeEnv(eval_mode=False, governor_disabled=False)
    env.reset()
    env.bus.state = BusState.WAITING_TO_MERGE
    env.bus.position = 300.0
    env.bus.velocity = 2.0
    env.bus.lateral_offset = -2.275
    env.bus.heading_angle = 0.0
    car = Vehicle(4, 288.60, 5.0, CAR_PARAMS)
    env.vehicles = [car]

    env.step(np.array([0.6, 0.6], dtype=np.float32))
    assert env.last_governor_reason == "governor_hold", (
        f"setup invalid: expected governor_hold, got {env.last_governor_reason!r}"
    )
    assert env.bus.acceleration <= 0.0, (
        f"training lunged: bus.acceleration={env.bus.acceleration} "
        f"(shield_condition={env.last_shield_condition!r})"
    )
    print(f"  PASS  full_pipeline_no_lunge_after_hold_training  bus.acceleration={env.bus.acceleration}  "
          f"shield_condition={env.last_shield_condition!r}")


if __name__ == "__main__":
    print("=" * 60)
    print("GOVERNOR HOLD / SHIELD LUNGE CONFLICT (Bug 1)")
    print("=" * 60)
    tests = [
        test_hold_fires_for_reported_scenario,
        test_shield_does_not_lunge_after_hold,
        test_emergency_stop_still_fires_when_gap_closes_within_frame,
        test_dead_zone_just_above_emergency_stop_boundary,
        test_progress_boundary_at_030,
        test_non_hold_reason_still_allowed_to_lunge,
        test_late_overlap_respects_hold,
        test_late_push_through_respects_hold,
        test_full_pipeline_no_lunge_after_hold_production,
        test_full_pipeline_no_lunge_after_hold_training,
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
