"""Regression guard for the training environment: a fixed policy on fixed seeds must reproduce
the stored observations and rewards (every 10 steps, compared within ``tests.golden_compare.ATOL``; steps, done and
success exactly). Regenerate with ``python -m tests.test_env_golden --update`` only when a behaviour change is
intended."""
import json
import random
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

from busmerge.rl.env import BusMergeEnv
from tests.brains import GOLDEN_BRAIN
from busmerge.rl.feature_encoding import infer_state_dim_from_checkpoint
from busmerge.rl.ppo_agent import PPOAgent
from tests.golden_compare import mismatches

GOLDEN_FILE = Path(__file__).parent / "golden" / "env_golden.json"
SEEDS = [0, 1, 2, 3]
MAX_STEPS = 600
SAMPLE_EVERY = 10


def run_env_case(seed: int, env_factory=BusMergeEnv) -> dict:
    ckpt = str(GOLDEN_BRAIN)
    dim = infer_state_dim_from_checkpoint(ckpt)
    agent = PPOAgent(state_dim=dim, filename=ckpt)
    agent.load(strict=True)
    env = env_factory(eval_mode=True, governor_disabled=True)
    env.feature_dim = dim
    env.state_size = dim
    env.sat_penalty_enabled = True
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    state = env.reset()
    samples = []
    total, steps, done = 0.0, 0, False
    while not done and steps < MAX_STEPS:
        with torch.no_grad():
            mean, _, _ = agent.policy(torch.FloatTensor(state).unsqueeze(0))
        state, reward, done, _ = env.step(mean.squeeze(0).numpy())
        total += float(reward)
        steps += 1
        if steps % SAMPLE_EVERY == 0 or done:
            samples.append([steps, round(total, 4)] + [round(float(x), 6) for x in np.asarray(state, dtype=np.float64)])
    return {"steps": steps, "done": bool(done), "success": bool(env.last_success),
            "total_reward": round(total, 3), "samples": samples}


@pytest.mark.parametrize("seed", SEEDS)
def test_env_matches_golden(seed):
    expected = json.loads(GOLDEN_FILE.read_text())[str(seed)]
    diff = mismatches(run_env_case(seed), expected)
    assert not diff, diff[:10]


if __name__ == "__main__" and "--update" in sys.argv:
    GOLDEN_FILE.write_text(json.dumps({str(s): run_env_case(s) for s in SEEDS}, indent=1, sort_keys=True) + "\n")
    print(f"Wrote {GOLDEN_FILE}")
