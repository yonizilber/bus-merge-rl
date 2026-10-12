"""Before the first update, the PPO ratio is exactly 1 for every stored sample (#22).

The ratio compares the probability of each stored action now with the probability when it was
sampled. Before any update the two are the same policy, so any ratio other than 1 means the stored
action and its stored log-probability do not belong together. That was the case for every action
beyond the steering limit (docs/BUGS.md P17). The batch is built exactly as training builds it
(`PPOAgent.choose_action`, `store_transition`) and scored with training's own functions
(`train.policy_distribution`, `train.ppo_ratios`).
"""
import numpy as np
import torch

from busmerge.rl.ppo_agent import PPOAgent
from busmerge.rl.train import policy_distribution, ppo_ratios


def _batch(agent: PPOAgent, n: int = 400):
    rng = np.random.default_rng(0)
    for _ in range(n):
        state = rng.normal(0, 1, 11).astype(np.float32)
        action, logprob = agent.choose_action(state)
        agent.store_transition(state, action, logprob, 0.0, state, False)
    states = torch.FloatTensor(np.array([m[0] for m in agent.memory], dtype=np.float32))
    actions = torch.FloatTensor(np.array([m[1] for m in agent.memory], dtype=np.float32))
    old_logprobs = torch.FloatTensor(np.array([m[2] for m in agent.memory], dtype=np.float32)).unsqueeze(1)
    return states, actions, old_logprobs


def test_ppo_ratio_is_one_before_the_first_update_including_beyond_the_action_limit():
    torch.manual_seed(0)
    agent = PPOAgent(state_dim=11, action_dim=2, filename="unused.pth")
    with torch.no_grad():
        agent.policy.actor_mean_head[0].bias.fill_(2.5)    # mean near the limit: many samples beyond it
    states, actions, old_logprobs = _batch(agent)
    assert (actions.abs() > 1.0).any(dim=1).float().mean() > 0.2, "the batch must include beyond-limit actions"
    with torch.no_grad():
        dist, _ = policy_distribution(agent.policy, states)
        ratios = ppo_ratios(dist, actions, old_logprobs)
    assert torch.allclose(ratios, torch.ones_like(ratios), atol=1e-5)


def test_storing_the_clipped_action_would_break_it():
    # The check must be able to fail: the old buffer stored the clipped action with the raw sample's
    # log-probability.
    torch.manual_seed(0)
    agent = PPOAgent(state_dim=11, action_dim=2, filename="unused.pth")
    with torch.no_grad():
        agent.policy.actor_mean_head[0].bias.fill_(2.5)
    states, actions, old_logprobs = _batch(agent)
    with torch.no_grad():
        dist, _ = policy_distribution(agent.policy, states)
        ratios = ppo_ratios(dist, actions.clamp(-1.0, 1.0), old_logprobs)
    assert not torch.allclose(ratios, torch.ones_like(ratios), atol=1e-5)
