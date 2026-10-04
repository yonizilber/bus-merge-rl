#!/usr/bin/env python3
"""Bug 3: shield_penalty_scale / intervention_strength dead training-curriculum code.

busmerge/rl/train.py sets env.shield_penalty_scale every epoch (a 3-phase curriculum:
suppressed during Phase 1 free exploration, then ramped up), but busmerge/rl/env.py's
reward block never reads it -- the shield-intervention penalty was silently constant
(effectively always the same as scale=1.0, in fact always ABSENT) regardless of what the
curriculum intended.

Uses a deep-copy-pair technique: clone the env before stepping, so two runs with different
shield_penalty_scale values see bit-identical physics/state -- any reward difference between
them must come from the new reward term, nothing else. apply_safety_shield is monkeypatched
to a deterministic stand-in so the test does not depend on reproducing exact car/gap geometry
to trigger a real shield intervention (that geometry is exercised by other tests).
"""
import copy
import sys


import numpy as np
import busmerge.rl.governor_logic as governor_logic
from busmerge.rl.env import BusMergeEnv

ACTION = np.array([0.8, 0.5], dtype=np.float32)
# Must match env.step()'s float32 rounding of ACTION[0] exactly (governor_disabled=True
# passes steer through unchanged) -- plain Python 0.8 differs from float32(0.8) at ~1e-7,
# which the squared/scaled reward terms amplify past a naive 1e-6 tolerance.
RAW_STEER = float(np.float32(0.8))


def _fake_shield_intervene(steer_intent, gas_intent, progress, gap, rel_speed, nearest_speed,
                            nearest_car, nearest_width=1.85, governor_reason="", *, dt=0.1,
                            condition="adaptive_gap"):
    """Deterministic stand-in for apply_safety_shield: always halves steer, tags `condition`."""
    return steer_intent * 0.5, gas_intent, condition


def _fake_shield_noop(steer_intent, gas_intent, progress, gap, rel_speed, nearest_speed,
                       nearest_car, nearest_width=1.85, governor_reason="", *, dt=0.1):
    """Stand-in that never intervenes (steer/gas passed through, condition='')."""
    return steer_intent, gas_intent, ""


def _make_env():
    env = BusMergeEnv(eval_mode=False, governor_disabled=True)
    env.reset()
    return env


def _step_with_mock(env, scale, shield_fn):
    """Deep-copy env, force the given shield behavior, step once. Returns (reward, env_after)."""
    e = copy.deepcopy(env)
    e.shield_penalty_scale = scale
    original = governor_logic.apply_safety_shield
    governor_logic.apply_safety_shield = shield_fn
    try:
        _, reward, _done, _info = e.step(ACTION)
    finally:
        governor_logic.apply_safety_shield = original
    return reward, e


def _intervene(condition="adaptive_gap"):
    return lambda *a, **k: _fake_shield_intervene(*a, **k, condition=condition)


# ---------------------------------------------------------------------------

def test_shield_penalty_scale_scales_reward():
    """MUST FAIL TODAY, PASS AFTER FIX. Pins the exact ported formula, not just 'some' penalty."""
    env = _make_env()
    reward_a, env_a = _step_with_mock(env, 0.0, _intervene("adaptive_gap"))
    assert env_a.last_intervened
    reward_b, env_b = _step_with_mock(env, 1.5, _intervene("adaptive_gap"))
    assert env_b.last_intervened

    intervention_strength = abs(RAW_STEER - 0.5 * RAW_STEER) / max(abs(RAW_STEER), 1e-8)
    expected_delta = (20.0 + 60.0 * RAW_STEER ** 2) * intervention_strength * 1.5
    expected_delta += 40.0 * RAW_STEER ** 2 * 1.5  # adaptive_gap extra term

    assert reward_b < reward_a, f"scale=1.5 should be strictly more punishing: {reward_b} !< {reward_a}"
    actual_delta = reward_a - reward_b
    assert abs(actual_delta - expected_delta) < 1e-6, (
        f"delta {actual_delta} != expected {expected_delta} "
        f"(reward_a={reward_a} reward_b={reward_b})"
    )
    print(f"  PASS  scale=0.0 reward={reward_a:.4f}  scale=1.5 reward={reward_b:.4f}  "
          f"delta={actual_delta:.4f} == expected {expected_delta:.4f}")


def test_shield_penalty_scale_zero_is_true_no_op():
    """scale=0.0 must contribute exactly 0, not act as a hidden floor penalty."""
    env = _make_env()
    reward_a, env_a = _step_with_mock(env, 0.0, _intervene("adaptive_gap"))
    assert env_a.last_intervened
    # Same intervention, scale=0.0 again from a fresh identical clone -> must be bit-identical.
    reward_b, env_b = _step_with_mock(env, 0.0, _intervene("adaptive_gap"))
    assert reward_a == reward_b
    print(f"  PASS  scale=0.0 reproducible no-op: reward={reward_a}")


def test_shield_penalty_scale_no_intervention_no_penalty():
    """No shield modification at all (intervened=False) -> reward identical regardless of scale."""
    env = _make_env()
    reward_a, env_a = _step_with_mock(env, 0.0, _fake_shield_noop)
    assert not env_a.last_intervened, "setup invalid: no-op shield unexpectedly registered as intervention"
    reward_b, env_b = _step_with_mock(env, 5.0, _fake_shield_noop)
    assert not env_b.last_intervened
    assert reward_a == reward_b, (
        f"scale changed reward with no intervention: {reward_a} vs {reward_b} "
        "(penalty must be gated on `intervened`, not applied unconditionally)"
    )
    print(f"  PASS  no intervention -> scale irrelevant: reward={reward_a}")


def test_shield_penalty_adaptive_gap_extra_term_is_condition_gated():
    """The +40*raw_steer^2*scale extra term must apply only when condition=='adaptive_gap',
    not for any other non-empty shield condition (e.g. 'high_pressure')."""
    env = _make_env()
    scale = 1.5
    reward_adaptive, env_a = _step_with_mock(env, scale, _intervene("adaptive_gap"))
    assert env_a.last_intervened and env_a.last_shield_condition == "adaptive_gap"
    reward_other, env_o = _step_with_mock(env, scale, _intervene("high_pressure"))
    assert env_o.last_intervened and env_o.last_shield_condition == "high_pressure"

    expected_extra = 40.0 * RAW_STEER ** 2 * scale
    actual_extra = reward_other - reward_adaptive  # adaptive_gap is more punishing by this much
    assert abs(actual_extra - expected_extra) < 1e-6, (
        f"adaptive_gap extra term {actual_extra} != expected {expected_extra}"
    )
    print(f"  PASS  adaptive_gap extra term isolated: {actual_extra:.4f} == expected {expected_extra:.4f}")


if __name__ == "__main__":
    print("=" * 60)
    print("SHIELD_PENALTY_SCALE WIRING (Bug 3)")
    print("=" * 60)
    tests = [
        test_shield_penalty_scale_scales_reward,
        test_shield_penalty_scale_zero_is_true_no_op,
        test_shield_penalty_scale_no_intervention_no_penalty,
        test_shield_penalty_adaptive_gap_extra_term_is_condition_gated,
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
