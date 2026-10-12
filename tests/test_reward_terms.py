"""Each term of the training reward, one at a time (#18).

The reward (`BusMergeEnv._reward_and_terminal`, "core" profile used for v13) is evaluated on a
prepared env. The nearest-car scan and the contact area are fixed, and only the condition of the term
under test changes. The difference in reward must be exactly the term's formula. A reward edit that
changes what the brain is paid for therefore fails here, by name.
"""
import copy
import random

import numpy as np
import pytest
import torch

from busmerge.rl.env import COMMITTED_PROGRESS, BusMergeEnv
from busmerge.rl.merge_constants import BAY_DEPTH

DT = 0.1


@pytest.fixture(scope="module")
def base():
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    env = BusMergeEnv(governor_disabled=True)
    env.feature_dim = env.state_size = 11
    env.sat_penalty_enabled, env.spongy_danger_zone_enabled = True, False
    env.reward_profile, env.shield_penalty_scale, env.noise_sigma = "core", 1.0, 0.0
    env.reset()
    return env


def _reward(base, *, lateral=BAY_DEPTH, lateral_velocity=0.0, bus_speed=0.0, gap=999.0, rel_speed=0.0,
            steer=0.0, contact_m2=0.0, step=1, passive_steps=0, commit_weight=8.0):
    env = copy.deepcopy(base)
    env.bus.lateral_offset, env.bus.lateral_velocity, env.bus.velocity = lateral, lateral_velocity, bus_speed
    env._prev_progress_rv = env._merge_progress()           # no change of progress this step
    env._scan_nearest_car = lambda: (gap, 10.0, 0.0, 1.8, rel_speed, None)
    env._bus_contact_area = lambda: contact_m2
    env._governor_raw_steer, env.last_governor_reason = steer, ""
    env.current_step, env._passive_steps, env.commit_steer_weight = step, passive_steps, commit_weight
    cmd = {"raw_steer_agent": steer, "raw_gas_agent": 0.0, "raw_steer": steer, "intervened": False,
           "intervention_strength": 0.0, "steer_intent": steer, "gas_intent": 0.0}
    _, reward, done, _ = env._reward_and_terminal(cmd)
    return reward, done


def test_time_penalty_every_step(base):
    assert _reward(base) == (-1.0, False)


def test_lateral_progress_pays_55_per_lane_width_halved_when_the_gap_is_tight(base):
    v = 0.5
    full = _reward(base, lateral_velocity=v)[0] - _reward(base)[0]
    assert full == pytest.approx(v * DT / -BAY_DEPTH * 55.0)
    tight = _reward(base, lateral_velocity=v, gap=1.0)[0] - _reward(base, gap=1.0)[0]
    assert tight == pytest.approx(0.5 * full)


def test_closing_risk_penalty(base):
    # Within 12 m and closing faster than 0.5 m/s: -25 x (12 - gap)/12 x min(rel_speed/8, 1).
    term = _reward(base, gap=6.0, rel_speed=4.0)[0] - _reward(base, gap=6.0)[0]
    assert term == pytest.approx(-25.0 * 0.5 * 0.5)
    assert _reward(base, gap=13.0, rel_speed=4.0)[0] == _reward(base, gap=13.0)[0]


@pytest.mark.parametrize("gap,scale", [(999.0, 1.0), (16.0, 0.5), (6.0, 0.0)])
def test_safe_steer_term_in_the_bay_and_once_out_of_it(base, gap, scale):
    in_bay = _reward(base, gap=gap, steer=0.5)[0] - _reward(base, gap=gap)[0]
    assert in_bay == pytest.approx(8.0 * 0.5 * scale)
    out = BAY_DEPTH * (1.0 - COMMITTED_PROGRESS) + 0.3          # 0.3 m past the committed progress
    out_of_bay = (_reward(base, lateral=out, gap=gap, steer=0.5, commit_weight=30.0)[0]
                  - _reward(base, lateral=out, gap=gap, commit_weight=30.0)[0])
    assert out_of_bay == pytest.approx(30.0 * 0.5 * scale)


def test_patience_reward_for_holding_still_while_the_lane_is_blocked(base):
    assert _reward(base, gap=-1.0)[0] - _reward(base)[0] == pytest.approx(0.5)


def test_contact_is_a_terminal_crash_scaled_by_progress(base):
    reward, done = _reward(base, contact_m2=0.5)
    assert done and reward == pytest.approx(-1.0 - 2500.0)
    lateral = -1.25                                             # progress 0.643
    reward, done = _reward(base, lateral=lateral, contact_m2=0.5)
    progress = (lateral - BAY_DEPTH) / -BAY_DEPTH
    assert done and reward == pytest.approx(-1.0 - 2500.0 - 1000.0 * min(progress / 0.75, 1.0))
    assert _reward(base, contact_m2=0.005) == (-1.0, False)      # below the gate's 0.01 m² threshold


def test_success_pays_5000_at_the_merge_threshold_and_contact_beats_it(base):
    reward, done = _reward(base, lateral=-0.2)
    assert done and reward == pytest.approx(-1.0 + 5000.0)
    reward, done = _reward(base, lateral=-0.2, contact_m2=0.5)
    assert done and reward < -2000.0


def test_timeout_penalty_grows_with_passivity(base):
    max_steps = base.max_steps
    reward, done = _reward(base, lateral=-1.0, step=max_steps)            # out of the bay: never passive
    assert done and reward == pytest.approx(-1.0 - 3500.0)
    reward, done = _reward(base, step=max_steps, passive_steps=max_steps - 1)   # idle the whole episode
    assert done and reward == pytest.approx(-1.0 - 3500.0 - 6000.0)
