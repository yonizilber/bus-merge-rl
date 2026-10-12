"""The same seed gives the same run, with perception noise on (#15).

Every replayed seed in the app, every published number and every regression test relies on this.
Hidden global state or an unseeded random draw would make a replayed failure seed show something
else. Both the app path (`run_episode`) and the training env are run twice in one process.
"""
import random

import numpy as np
import pandas as pd
import torch

from busmerge.config import SimConfig
from busmerge.evaluation import APP_DEFAULTS, run_episode
from busmerge.paths import DEFAULT_BRAIN
from busmerge.rl.env import BusMergeEnv

NOISE = 0.15


def _app_run(seed: int) -> pd.DataFrame:
    cfg = SimConfig(**{**APP_DEFAULTS, "total_cars_to_spawn": 25})
    return run_episode("B", cfg, str(DEFAULT_BRAIN), governor_disabled=True, noise_sigma=NOISE, seed=seed).get_results()


def test_app_run_is_identical_for_the_same_seed_with_noise_on():
    first, second = _app_run(7), _app_run(7)
    pd.testing.assert_frame_equal(first, second)
    assert not first.equals(_app_run(8)), "a different seed must give a different run"


def _env_run(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    env = BusMergeEnv(governor_disabled=True)
    env.feature_dim = env.state_size = 11
    env.sat_penalty_enabled, env.noise_sigma = True, NOISE
    trace = [env.reset()]
    rng = np.random.default_rng(seed)
    for _ in range(120):
        state, reward, done, _ = env.step((float(rng.uniform(-1, 1)), float(rng.uniform(-1, 1))))
        trace.append(np.append(state, reward))
        if done:
            break
    return np.concatenate(trace)


def test_training_env_is_identical_for_the_same_seed_with_noise_on():
    first, second = _env_run(3), _env_run(3)
    assert np.array_equal(first, second)
    other = _env_run(4)
    assert first.shape != other.shape or not np.array_equal(first, other)
