"""Training must start from poses the app can produce, and PPO must learn from the actions it sampled."""
import random

import numpy as np
import pytest
import torch

from busmerge.geometry import bus_stop_range, road_edge_excess
from busmerge.rl.env import BusMergeEnv
from busmerge.rl.ppo_agent import PPOAgent


def test_training_start_poses_are_on_the_road_and_cover_the_stop_range():
    env = BusMergeEnv()
    lo, hi = bus_stop_range(11.0)
    xs = []
    for seed in range(200):
        random.seed(seed)
        np.random.seed(seed)
        env.reset()
        b = env.bus
        below, above = road_edge_excess(b.position, b.lateral_offset, b.params.length, b.params.width,
                                        b.heading_angle)
        assert below[0] <= 0.0 and above[0] <= 0.0
        xs.append(b.position)
    assert lo <= min(xs) < lo + 1.0 and hi - 1.0 < max(xs) <= hi


def test_ppo_stores_the_sampled_action_with_its_own_log_probability():
    torch.manual_seed(0)
    agent = PPOAgent(state_dim=11, action_dim=2, filename="unused.pth")
    with torch.no_grad():
        agent.policy.actor_mean_head[0].bias.fill_(3.0)   # tanh(3) ≈ 0.995: about half the samples exceed 1
    state = np.zeros(11, dtype=np.float32)
    beyond = 0
    for _ in range(200):
        action, logprob = agent.choose_action(state)
        with torch.no_grad():
            mean, std, _ = agent.policy(torch.FloatTensor(state).unsqueeze(0))
        expected = torch.distributions.Normal(mean, std).log_prob(torch.FloatTensor(action).unsqueeze(0)).sum()
        assert logprob == pytest.approx(float(expected), abs=1e-5)
        beyond += bool(np.abs(action).max() > 1.0)
    assert beyond > 0   # raw samples are kept; only the vehicle's command is clipped
