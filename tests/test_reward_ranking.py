"""The training reward must pay most for merging all the way, and least for not leaving the bay.

Fixed policies in the training env, with the training settings (polygon crash judge, the "core"
reward profile, full traffic mix, perception noise), on the same seeds:
- merge: steer for the lane at once, at 60% gas (ignores traffic, so it sometimes hits a car);
- half way: aim half way out of the bay, which is what v9-v11 learned to do (the reward hack);
- stay: never leave the bay.
"""
import random

import numpy as np
import pytest
import torch

from busmerge.rl.env import BusMergeEnv

POLICIES = {"merge": (1.0, 0.6), "half way": (0.1, 0.45), "stay": (-1.0, 0.0)}
SEEDS = range(8)


def _mean_return(action, commit_steer_weight: float) -> float:
    returns = []
    for seed in SEEDS:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        env = BusMergeEnv(governor_disabled=True)
        env.feature_dim = env.state_size = 11
        env.sat_penalty_enabled, env.spongy_danger_zone_enabled = True, False
        env._warmup_prob = env._zero_road_prob = 0.0
        env.reward_profile, env.noise_sigma, env.shield_penalty_scale = "core", 0.15, 1.0
        env.commit_steer_weight = commit_steer_weight
        env.reset()
        done, total = False, 0.0
        while not done:
            _, reward, done, _ = env.step(action)
            total += reward
        returns.append(total)
    return float(np.mean(returns))


@pytest.mark.parametrize("commit_steer_weight", [8.0, 30.0], ids=["default-reward", "v13-reward"])
def test_reward_ranks_a_full_merge_above_half_way_above_staying(commit_steer_weight):
    r = {name: _mean_return(action, commit_steer_weight) for name, action in POLICIES.items()}
    assert r["merge"] > r["half way"] > r["stay"], r
    # Not a near tie: a full merge must be worth more than the timeout penalty a half-way stop earns.
    assert r["merge"] - r["half way"] > 3000.0, r
