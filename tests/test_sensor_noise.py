#!/usr/bin/env python3
"""Human Perception Model v2 — distance curves + steady OU noise."""
import sys

import numpy as np


from busmerge.rl.feature_encoding import (
    PerceptionNoiseState,
    apply_sensor_noise,
    distance_noise_scale,
    encode_features,
    perception_noise_sigmas,
    speed_noise_scale,
    step_perception_noise,
)


def test_dist_scale_floor_and_ceiling():
    assert distance_noise_scale(2.0) == 0.05
    assert distance_noise_scale(50.0) == 1.0
    assert distance_noise_scale(80.0) == 1.2  # clipped ceiling
    assert speed_noise_scale(2.0) == 0.04 * 0.04
    assert abs(speed_noise_scale(50.0) - 1.0) < 1e-9
    print("  PASS  dist_scale")


def test_self_state_unnoised():
    state = PerceptionNoiseState()
    np.random.seed(0)
    for _ in range(20):
        step_perception_noise(state, 0.3, 8.0, 0.1, car_id=1)
    out = apply_sensor_noise(
        0.3, 0.42, 0.12, 8.0, 1.5, 12.0, -1.0, 1.85, 4.5, 2.0, 0.1, 0.02,
        noise_state=state, dt=0.1, car_id=1,
    )
    assert out[0] == 0.42
    assert out[1] == 0.12
    print("  PASS  self_state_clean")


def test_close_gap_noise_smaller_than_far():
    sigma = 0.3
    close = []
    far = []
    for seed in range(300):
        np.random.seed(seed)
        st_c = PerceptionNoiseState()
        st_f = PerceptionNoiseState()
        for _ in range(40):
            step_perception_noise(st_c, sigma, 2.0, 0.1, car_id=1)
            step_perception_noise(st_f, sigma, 50.0, 0.1, car_id=1)
        _, _, g_close, *_ = apply_sensor_noise(
            sigma, 0.5, 0.0, 2.0, 1.0, 10.0, 0.0, 1.85, 4.5, 1.0, 0.0, 0.0,
            noise_state=st_c, dt=0.1, car_id=1,
        )
        _, _, g_far, *_ = apply_sensor_noise(
            sigma, 0.5, 0.0, 50.0, 1.0, 10.0, 0.0, 1.85, 4.5, 1.0, 0.0, 0.0,
            noise_state=st_f, dt=0.1, car_id=1,
        )
        close.append(abs(g_close - 2.0))
        far.append(abs(g_far - 50.0))
    assert np.mean(far) > np.mean(close) * 3.0, (
        f"far noise {np.mean(far):.3f} should >> close {np.mean(close):.3f}"
    )
    print(f"  PASS  gap_noise  close_mean={np.mean(close):.3f} far_mean={np.mean(far):.3f}")


def test_speed_noise_quadratic():
    sig = perception_noise_sigmas(0.3, 2.0)
    sig_far = perception_noise_sigmas(0.3, 50.0)
    assert sig["rel_speed"] < 0.05
    assert sig_far["rel_speed"] >= 1.4
    assert sig_far["rel_speed"] / max(sig["rel_speed"], 1e-6) > 50.0
    print(f"  PASS  speed_quadratic  close={sig['rel_speed']:.4f} far={sig_far['rel_speed']:.3f}")


def test_accel_foggy_at_range():
    sig_close = perception_noise_sigmas(0.3, 2.0)
    sig_far = perception_noise_sigmas(0.3, 50.0)
    assert sig_far["rel_accel"] > sig_close["rel_accel"] * 5.0
    assert sig_far["rel_accel"] > 4.0
    print(f"  PASS  accel_fog  close={sig_close['rel_accel']:.2f} far={sig_far['rel_accel']:.2f}")


def test_steady_noise_high_autocorrelation():
    """OU biases should not flip sign every frame at fixed truth."""
    sigma = 0.3
    state = PerceptionNoiseState()
    np.random.seed(42)
    rs_errs = []
    for _ in range(80):
        step_perception_noise(state, sigma, 8.0, 0.1, car_id=7)
        *_, rs, _, _ = apply_sensor_noise(
            sigma, 0.3, 0.0, 8.0, 1.0, 10.0, 0.0, 1.85, 4.5, 1.5, 0.0, 0.0,
            noise_state=state, dt=0.1, car_id=7,
        )
        rs_errs.append(rs - 1.5)
    ac1 = np.corrcoef(rs_errs[:-1], rs_errs[1:])[0, 1]
    sign_flips = sum(
        1 for a, b in zip(rs_errs[:-1], rs_errs[1:]) if a * b < 0
    )
    flip_rate = sign_flips / max(1, len(rs_errs) - 1)
    assert ac1 > 0.80, f"lag-1 autocorr {ac1:.3f} too low for steady perception"
    assert flip_rate < 0.15, f"sign flip rate {flip_rate:.2f} too high"
    print(f"  PASS  steady_noise  ac1={ac1:.3f} flip_rate={flip_rate:.2f}")


def test_car_change_resets_bias():
    state = PerceptionNoiseState()
    np.random.seed(1)
    for _ in range(50):
        step_perception_noise(state, 0.3, 5.0, 0.1, car_id=1)
    state.reset(car_id=2)
    assert state.rel_speed_bias == 0.0
    print("  PASS  car_change_reset")


def test_encode_features_path():
    state = PerceptionNoiseState()
    np.random.seed(1)
    v0 = encode_features(
        4, 0.5, 0.1, 3.0, 1.0, 11.0, 0.0, 1.85, 4.5, 0.5, 0.0, 0.0, noise_sigma=0.0,
    )
    np.random.seed(1)
    v1 = encode_features(
        4, 0.5, 0.1, 3.0, 1.0, 11.0, 0.0, 1.85, 4.5, 0.5, 0.0, 0.0,
        noise_sigma=0.3, noise_state=state, dt=0.1, car_id=3,
    )
    assert np.allclose(v0[[0, 1]], v1[[0, 1]])
    assert not np.allclose(v0, v1)
    print("  PASS  encode_features")


if __name__ == "__main__":
    print("=" * 60)
    print("SENSOR NOISE (Human Perception v2 + steady OU)")
    print("=" * 60)
    failed = []
    for fn in (
        test_dist_scale_floor_and_ceiling,
        test_self_state_unnoised,
        test_close_gap_noise_smaller_than_far,
        test_speed_noise_quadratic,
        test_accel_foggy_at_range,
        test_steady_noise_high_autocorrelation,
        test_car_change_resets_bias,
        test_encode_features_path,
    ):
        try:
            fn()
        except AssertionError as e:
            failed.append((fn.__name__, str(e)))
            print(f"  FAIL  {fn.__name__}: {e}")
    print("=" * 60)
    sys.exit(1 if failed else 0)
