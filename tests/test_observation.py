"""build_observation is the only observation builder; pin its contract."""
import numpy as np
import pytest

from busmerge.rl.feature_encoding import PerceptionNoiseState
from busmerge.rl.observation import EMPTY_ROAD_GAP_M, build_observation
from busmerge.vehicle import Bus, BusState, CAR_PARAMS, Vehicle


def _bus():
    bus = Bus(v_id=999, position=300.0, velocity=0.0, params=CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -3.5
    return bus


def test_empty_road_uses_sentinels():
    obs = build_observation(_bus(), [], 0.0, 0.1, 11)
    assert obs.nearest_car is None
    assert obs.gap == EMPTY_ROAD_GAP_M
    assert obs.state.shape == (11,)
    assert obs.state[2] == pytest.approx(1.0)  # 60 m is the top of the normalised gap range


def test_feature_dim_selects_state_width():
    bus = _bus()
    for dim in (4, 7, 11):
        assert build_observation(bus, [], 0.0, 0.1, dim).state.shape == (dim,)


def test_car_behind_bus_is_reported_as_truth():
    bus = _bus()
    car = Vehicle(v_id=1, position=285.0, velocity=8.0, params=CAR_PARAMS)
    obs = build_observation(bus, [bus, car], 0.0, 0.1, 11)
    assert obs.nearest_car is car
    assert obs.nearest_speed == pytest.approx(8.0)
    assert np.isfinite(obs.gap) and obs.gap != EMPTY_ROAD_GAP_M


def test_noise_changes_the_state_but_not_the_facts():
    bus = _bus()
    car = Vehicle(v_id=1, position=270.0, velocity=8.0, params=CAR_PARAMS)
    clean = build_observation(bus, [bus, car], 0.0, 0.1, 11)
    noisy_state = PerceptionNoiseState()
    np.random.seed(0)
    noisy = build_observation(bus, [bus, car], 0.0, 0.1, 11, noise_sigma=0.3, noise_state=noisy_state)
    assert (clean.gap, clean.nearest_speed, clean.merge_progress) == (noisy.gap, noisy.nearest_speed, noisy.merge_progress)
    assert not np.allclose(clean.state, noisy.state)


def test_relative_acceleration_uses_previous_bus_speed():
    bus = _bus()
    bus.velocity = 1.0
    car = Vehicle(v_id=1, position=270.0, velocity=8.0, params=CAR_PARAMS)
    same = build_observation(bus, [bus, car], 1.0, 0.1, 11).state
    accelerating = build_observation(bus, [bus, car], 0.0, 0.1, 11).state  # +10 m/s^2 over the last 0.1 s
    assert not np.allclose(same, accelerating)
