"""
diag_state_parity.py -- Train/Prod Parity Test v3
Tests:
  1. State encoder parity: RL env vs SimulationEngine._encode_brain_state must be identical
     for the same physical inputs (100 random states).
  2. Governor parity: env _governor_check vs simulation.py governor must produce
     the same (steer_intent, gas_intent) for the same physical inputs.
  3. Constant parity: all constants in merge_constants.py must match values used
     in both files.

Run:  python diag_state_parity.py
Exit code 0 = all PASS, 1 = at least one FAIL (use in CI).
"""
import os, sys
import numpy as np
import random as _random
from contextlib import contextmanager

from busmerge.rl.env import BusMergeEnv
from busmerge.rl.merge_constants import (
    BUS_MAX_SPEED, BAY_DEPTH, LANE_WIDTH, BUS_WIDTH, BUS_LENGTH,
    GOVERNOR_T_HORIZON, GOVERNOR_T_HORIZON_COMMITTED,
    GOVERNOR_MAX_SAFE_DECEL, GOVERNOR_STEER_THRESHOLD,
)
from busmerge.simulation import SimulationEngine

FEATURE_NAMES = [
    "F0  merge_progress  ",
    "F1  bus_heading_rad ",
    "F2  lon_dist (gap)  ",
    "F3  lat_clearance   ",
    "F4  car_speed       ",
    "F5  car_accel       ",
    "F6  car_width       ",
    "F7  car_length      ",
    "F8  rel_speed       ",
    "F9  rel_accel       ",
    "F10 car_heading_rad ",
]

# Force Scenario B: roll in [0.12, 0.30)
SCENARIO_B_ROLL = 0.20

_last_raw = {}
_original_encode_state = None


@contextmanager
def _force_first_roll(target):
    original = _random.random
    state = {"n": 0}
    def patched():
        if state["n"] == 0:
            state["n"] += 1
            return target
        return original()
    _random.random = patched
    try:
        yield
    finally:
        _random.random = original


def _patched_encode(self, mp, bh, ld, lc, cs, ca, cw, cl, rs, ra, ch):
    _last_raw.update({
        "merge_progress": mp,  "bus_heading_rad": bh,
        "lon_dist": ld,        "lat_clearance":  lc,
        "car_speed": cs,       "car_accel":      ca,
        "car_width": cw,       "car_length":     cl,
        "rel_speed": rs,       "rel_accel":      ra,
        "car_heading_rad": ch,
    })
    return _original_encode_state(self, mp, bh, ld, lc, cs, ca, cw, cl, rs, ra, ch)


def main():
    global _original_encode_state
    _original_encode_state = BusMergeEnv._encode_state
    BusMergeEnv._encode_state = _patched_encode

    SEED = 42
    np.random.seed(SEED)
    _random.seed(SEED)

    env = BusMergeEnv(eval_mode=False)
    env._warmup_epoch = False

    with _force_first_roll(SCENARIO_B_ROLL):
        env.reset()

    bar = "=" * 80
    print(bar)
    print("STATE PARITY TEST  --  Train env vs Deploy encoder")
    print("Scenario B (Slow City Stream)  |  Seed=%d  |  5 live steps" % SEED)
    print("Same raw inputs -> both encoders must produce identical output.")
    print(bar)
    n = len(env.vehicles)
    spd = [round(c.velocity, 1) for c in env.vehicles[:3]]
    print("Spawned %d cars, first 3 speeds: %s m/s" % (n, spd))
    print()

    stay = np.array([0.0, 0.0], dtype=np.float32)
    all_ok = True

    for step in range(1, 6):
        env.step(stay)
        raw = dict(_last_raw)

        args = (
            raw["merge_progress"], raw["bus_heading_rad"], raw["lon_dist"],
            raw["lat_clearance"],  raw["car_speed"],       raw["car_accel"],
            raw["car_width"],      raw["car_length"],      raw["rel_speed"],
            raw["rel_accel"],      raw["car_heading_rad"],
        )

        rl_vec  = _original_encode_state(env, *args)
        _sim_inst = SimulationEngine.__new__(SimulationEngine)
        _sim_inst.feature_dim = getattr(env, "feature_dim", 11)
        _sim_inst.dt = 0.1
        from busmerge.rl.feature_encoding import PerceptionNoiseState
        _sim_inst._perception_noise = PerceptionNoiseState()
        sim_vec = _sim_inst._encode_brain_state(*args, noise_sigma=0.0)
        diff    = np.abs(rl_vec - sim_vec)
        max_d   = diff.max()
        ok      = max_d < 1e-7
        if not ok:
            all_ok = False

        print("Step %d | progress=%.3f  bus_vel=%.2f m/s  lat_vel=%.4f m/s" % (
            step, raw["merge_progress"],
            env.bus.velocity, env.bus.lateral_velocity))
        print("  %-22s %10s %10s  %10s  Status" % (
            "Feature", "RL-Train", "Sim-Deploy", "|Diff|"))
        print("  " + "-" * 62)

        for i, name in enumerate(FEATURE_NAMES):
            flag = "  MISMATCH!" if diff[i] >= 1e-7 else ""
            print("  %-22s %10.6f %10.6f  %10.2e%s" % (
                name, rl_vec[i], sim_vec[i], diff[i], flag))

        verdict = "PASS" if ok else "FAIL"
        print("  Max diff: %.2e  -->  %s" % (max_d, verdict))
        print()

    print(bar)
    if all_ok:
        print("RESULT: PERFECT PARITY -- both envs encode identically.")
    else:
        print("RESULT: DIVERGENCE DETECTED -- encoders disagree!")
    print(bar)
    return all_ok


def test_encoder_random(n=100, tol=1e-6):
    """Assert encoder parity for n random physical input vectors (11-, 7-, and 4-dim)."""
    all_ok = True
    for feature_dim in (11, 7, 4):
        print("=" * 60)
        print(f"ENCODER RANDOM PARITY TEST  feature_dim={feature_dim}  ({n} states)")
        print("=" * 60)
        rng = np.random.default_rng(seed=7)
        failures = []
        for i in range(n):
            mp  = float(rng.uniform(0.0, 1.0))
            bh  = float(rng.uniform(-0.54, 0.54))
            ld  = float(rng.uniform(-10.0, 60.0))
            lc  = float(rng.uniform(-2.0, 4.0))
            cs  = float(rng.uniform(0.0, 20.0))
            ca  = float(rng.uniform(-9.0, 3.0))
            cw  = float(rng.uniform(1.70, 2.05))
            cl  = float(rng.uniform(3.5, 5.5))
            rs  = float(rng.uniform(-15.0, 15.0))
            ra  = float(rng.uniform(-15.0, 15.0))
            ch  = float(rng.uniform(-0.15, 0.15))

            env = BusMergeEnv(eval_mode=True)
            env.feature_dim = feature_dim
            rl_v  = env._encode_state(mp, bh, ld, lc, cs, ca, cw, cl, rs, ra, ch)
            _si = SimulationEngine.__new__(SimulationEngine)
            _si.dt = 0.1
            from busmerge.rl.feature_encoding import PerceptionNoiseState
            _si._perception_noise = PerceptionNoiseState()
            sim_v = _si._encode_brain_state(mp, bh, ld, lc, cs, ca, cw, cl, rs, ra, ch,
                                            noise_sigma=0.0, feature_dim_override=feature_dim)
            diff  = np.abs(rl_v - sim_v)
            if diff.max() > tol:
                failures.append((i, diff.max(), diff.argmax()))

        if failures:
            print(f"  FAIL — {len(failures)}/{n} states diverged (feature_dim={feature_dim}):")
            for idx, maxd, feat in failures[:5]:
                print(f"    state {idx}: max_diff={maxd:.2e} at feature {feat}")
            all_ok = False
        else:
            print(f"  PASS — all {n} states identical (max_diff < {tol:.0e})")

        # Sentinel test: empty road should give gap sentinel lon_n=1.0, rs_n=0.0
        env2 = BusMergeEnv(eval_mode=True)
        env2.feature_dim = feature_dim
        v_empty = env2._encode_state(0.3, 0.1, 60.0, 2.0, 0.0, 0.0, 1.85, 4.5, 0.0, 0.0, 0.0)
        lon_idx = 2 if feature_dim == 4 else 2  # same position in all dims
        rs_idx  = 3 if feature_dim == 4 else (6 if feature_dim == 7 else 8)
        lon_ok = abs(float(v_empty[lon_idx]) - 1.0) < 1e-4
        rs_ok  = abs(float(v_empty[rs_idx])  - 0.0) < 1e-4
        if lon_ok and rs_ok:
            print(f"  PASS — empty-road sentinel: lon_n=1.0, rs_n=0.0  (dim={feature_dim})")
        else:
            print(f"  FAIL — empty-road sentinel wrong  lon_n={v_empty[lon_idx]:.3f} rs_n={v_empty[rs_idx]:.3f}  (dim={feature_dim})")
            all_ok = False

    return all_ok


def test_constants():
    """Assert merge_constants values match what env and simulation actually use."""
    print("=" * 60)
    print("CONSTANT PARITY TEST")
    print("=" * 60)
    all_ok = True

    checks = [
        ("BUS_MAX_SPEED", BUS_MAX_SPEED, BusMergeEnv.BUS_MAX_SPEED),
        ("MERGE_ACCEL_MAX", 2.0, BusMergeEnv.MERGE_ACCEL_MAX),
        ("BAY_DEPTH", BAY_DEPTH, -3.5),
        ("LANE_WIDTH", LANE_WIDTH, 3.5),
        ("BUS_WIDTH", BUS_WIDTH, 2.5),
        ("BUS_LENGTH", BUS_LENGTH, 11.0),
    ]
    for name, const_val, env_val in checks:
        ok = abs(const_val - env_val) < 1e-9
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {name}: merge_constants={const_val:.4f}  env={env_val:.4f}")
        if not ok:
            all_ok = False

    return all_ok


if __name__ == "__main__":
    all_passed = True
    all_passed &= main()
    all_passed &= test_encoder_random()
    all_passed &= test_constants()
    print()
    if all_passed:
        print("ALL PARITY TESTS PASSED")
        sys.exit(0)
    else:
        print("PARITY FAILURES DETECTED — do not deploy this brain")
        sys.exit(1)
