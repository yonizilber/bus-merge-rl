"""The training environment moves the world exactly as the app engine does (#24).

`BusMergeEnv` builds a training scenario and hands every physics step to `SimulationEngine`
(docs/reference/BUGS.md P1: two physics implementations used to drift apart). The test lets the env and an
independent copy of its engine take the same actions from the same state and random-number state.
After every step, every vehicle must be bit-identical in both: position, speed, acceleration, lateral
position, heading, steering angle and lane drift. Anything the env did to the physics outside the
engine step would break it. The engine the env builds must also use the app's physics settings.
"""
import copy
import random

import numpy as np
import pytest
import torch

from busmerge.config import SimConfig
from busmerge.evaluation import APP_DEFAULTS
from busmerge.rl.env import BusMergeEnv

FIELDS = ("position", "velocity", "acceleration", "lateral_offset", "heading_angle", "steer_angle", "lane_drift")


def _actions(rng: np.random.Generator, n: int):
    """Waiting, a hesitant start, then a full merge, with noise: every part of the controller is used."""
    for k in range(n):
        steer = -1.0 if k < 20 else (0.2 if k < 40 else 1.0)
        # float32, as a policy outputs them (the env reads actions as float32)
        yield tuple(float(np.float32(x)) for x in (np.clip(steer + rng.normal(0, 0.2), -1, 1),
                                                    np.clip(0.5 + rng.normal(0, 0.3), -1, 1)))


def _state(engine) -> dict:
    return {v.id: tuple(float(getattr(v, f)) for f in FIELDS) for v in engine.vehicles}


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_training_env_steps_the_world_exactly_like_the_app_engine(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    env = BusMergeEnv(governor_disabled=True)
    env.feature_dim = env.state_size = 11
    env.sat_penalty_enabled = True
    env.noise_sigma = 0.15            # the env's own perception noise must not touch the physics
    env.reset()
    app = copy.deepcopy(env.engine)   # independent world, same vehicles and settings

    steps = 0
    for action in _actions(np.random.default_rng(seed), 150):
        rng_state = (random.getstate(), np.random.get_state())
        _, _, done, _ = env.step(action)
        random.setstate(rng_state[0])
        np.random.set_state(rng_state[1])
        app.external_action = action
        app.step()
        steps += 1
        assert _state(env.engine) == _state(app), f"seed {seed}: worlds differ after step {steps}"
        if done:
            break
    assert steps >= 20


def test_training_engine_uses_the_app_physics_settings():
    env = BusMergeEnv(governor_disabled=True)
    env.reset()
    app_cfg = SimConfig(**APP_DEFAULTS)
    # Arrivals and boarding differ on purpose: the env builds its traffic and starts after boarding.
    for field in ("road_length", "bus_stop_position", "speed_limit_car", "speed_limit_bus"):
        assert getattr(env.engine.cfg, field) == getattr(app_cfg, field), field
    assert env.engine.dt == env.dt == 0.1
    assert env.engine.governor_disabled is True


def test_the_check_sees_a_tiny_drift(monkeypatch):
    # The parity test must be able to fail: an env that nudges the bus by 1e-9 m/s outside the engine.
    original = BusMergeEnv._control_and_tick

    def drifting(self, steer, gas):
        out = original(self, steer, gas)
        self.bus.velocity += 1e-9
        return out

    monkeypatch.setattr(BusMergeEnv, "_control_and_tick", drifting)
    with pytest.raises(AssertionError, match="worlds differ"):
        test_training_env_steps_the_world_exactly_like_the_app_engine(0)
