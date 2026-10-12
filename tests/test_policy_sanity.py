"""The shipped brains behave sanely on unusual inputs (#7).

Observations are built by the production observation builder from real vehicles, in situations
the brain rarely meets: an empty road, a car alongside at zero gap, a fast car close behind, a stopped
car just ahead, the bus already in the lane, a turned bus, a standing or fast bus. The tests check the
following:
- the observation is finite;
- the brain's answer is finite and deterministic (same input, same output);
- the mean is inside the action range and the exploration width within its bounds.
Wildly out-of-range feature vectors must still give finite answers.
"""
import numpy as np
import pytest
import torch

from busmerge.paths import MODELS_DIR
from busmerge.rl.feature_encoding import infer_state_dim_from_checkpoint
from busmerge.rl.observation import build_observation
from busmerge.rl.ppo_agent import PPOAgent
from busmerge.vehicle import CAR_PARAMS, Bus, BusState, Vehicle, sample_vehicle_params

BRAINS = ["ppo_bus_brain_v13.pth", "ppo_bus_brain_v11_engine.pth", "ppo_bus_brain_exp7satv9_best.pth"]


def _scene(bus_lat=-3.5, bus_v=0.0, heading_deg=0.0, cars=()):
    np.random.seed(0)
    bus = Bus(999, 305.0, bus_v, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset, bus.heading_angle = bus_lat, np.radians(heading_deg)
    vehicles = [bus]
    for i, (dx, v) in enumerate(cars):
        _, p = sample_vehicle_params("Mid")
        vehicles.append(Vehicle(i + 1, bus.position + dx, v, p))
    return bus, vehicles


SCENES = {
    "empty road": _scene(),
    "car alongside, zero gap, standing": _scene(cars=[(-5.0, 0.0)]),
    "fast car just behind": _scene(cars=[(-14.0, 25.0)]),
    "stopped car just ahead": _scene(cars=[(7.0, 0.0)]),
    "bus already in the lane": _scene(bus_lat=0.0, bus_v=8.0, cars=[(-20.0, 10.0)]),
    "bus turned 10 degrees": _scene(bus_lat=-2.0, bus_v=3.0, heading_deg=10.0, cars=[(-30.0, 12.0)]),
    "bus fast in the bay": _scene(bus_v=15.0, cars=[(30.0, 2.0)]),
}


def _policy(name: str) -> PPOAgent:
    path = MODELS_DIR / name
    agent = PPOAgent(state_dim=infer_state_dim_from_checkpoint(str(path)), action_dim=2, filename=str(path))
    agent.load(strict=True)
    agent.policy.eval()
    return agent


@pytest.mark.parametrize("brain", BRAINS)
@pytest.mark.parametrize("scene", list(SCENES))
def test_brain_answers_unusual_situations_sanely(brain, scene):
    agent = _policy(brain)
    bus, vehicles = SCENES[scene]
    state = build_observation(bus, vehicles, bus.velocity, 0.1, agent.policy.actor_trunk[0].in_features).state
    assert np.isfinite(state).all(), state
    x = torch.FloatTensor(state).unsqueeze(0)
    with torch.no_grad():
        mean, std, value = agent.policy(x)
        mean2, std2, value2 = agent.policy(x)
    assert torch.equal(mean, mean2) and torch.equal(std, std2) and torch.equal(value, value2)
    assert torch.isfinite(mean).all() and torch.isfinite(value).all()
    assert (mean.abs() < 1.0).all()                        # tanh head: inside the action range
    assert ((std >= 0.049) & (std <= 1.65)).all()          # exploration width within its clamp


@pytest.mark.parametrize("brain", BRAINS)
def test_brain_gives_finite_answers_for_wildly_out_of_range_inputs(brain):
    agent = _policy(brain)
    dim = agent.policy.actor_trunk[0].in_features
    x = torch.FloatTensor(np.random.default_rng(7).uniform(-1e4, 1e4, size=(200, dim)))
    with torch.no_grad():
        mean, std, value = agent.policy(x)
    assert torch.isfinite(mean).all() and torch.isfinite(std).all() and torch.isfinite(value).all()
    assert (mean.abs() <= 1.0).all()
