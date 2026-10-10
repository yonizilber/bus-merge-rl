"""Two training epochs run end to end, change the weights, and produce a brain the app engine can drive.

Nothing in the training loop was exercised by a test before: the PPO buffer bug and the rollback bug
(docs/BUGS.md P17, P18) were found only when a fine-tune failed. Every file training writes (the
checkpoints and its log) goes to a temporary folder.
"""
import random

import numpy as np
import torch

import busmerge.rl.train as training
from busmerge.config import SimConfig
from busmerge.simulation import SimulationEngine
from busmerge.vehicle import BusState


def test_two_training_epochs_run_end_to_end_and_the_app_drives_the_result(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(training, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(training, "ENV_FLAGS", dict(training.ENV_FLAGS))   # train() updates it in place

    initial = {}
    original_init = training.PPOAgent.__init__

    def remember_initial_weights(agent, *args, **kwargs):
        original_init(agent, *args, **kwargs)
        initial.update({k: v.detach().clone() for k, v in agent.policy.state_dict().items()})

    monkeypatch.setattr(training.PPOAgent, "__init__", remember_initial_weights)

    training.train(epochs=2, batch_size=256, eval_episodes=1, eval_interval=0, skip_baseline_eval=True,
                   no_bootstrap=True, run_tag="exp7satci", curriculum_phase1_end=0, curriculum_phase2_end=0,
                   traffic_first=True, feature_dim=11, governor_disabled=True, seed=0, rollback_patience=0)

    checkpoint = tmp_path / "ppo_bus_brain_exp7satci.pth"
    assert checkpoint.exists()
    trained = torch.load(checkpoint)
    assert any(not torch.equal(trained[k], initial[k]) for k in initial), "the weights did not change"

    # The app engine loads the checkpoint and drives the merge with it.
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    sim = SimulationEngine("B", SimConfig(traffic_rate=0.0, total_cars_to_spawn=0), brain_path=str(checkpoint),
                           governor_disabled=True)
    sim.init_scenario()
    bus = next(v for v in sim.vehicles if v.id == 999)
    while bus.state != BusState.WAITING_TO_MERGE and sim.time < 120.0:
        sim.step()
    for _ in range(50):
        sim.step()
    assert sim.last_decision is not None
    assert np.isfinite([sim.last_decision["raw_steer"], sim.last_decision["raw_gas"]]).all()
