"""Checkpoints round-trip exactly and a mismatched one is refused (#23).

A checkpoint that loads into a network of the wrong shape, or a missing file, must never quietly
leave random weights in place where a trained brain is expected (docs/BUGS.md H8, H9). Training's
lenient load (``strict=False``) is allowed to start fresh, and says so.
"""
import numpy as np
import pytest
import torch

from busmerge.config import SimConfig
from busmerge.rl.feature_encoding import infer_state_dim_from_checkpoint
from busmerge.rl.ppo_agent import PPOAgent
from busmerge.simulation import SimulationEngine


@pytest.mark.parametrize("dim", [4, 7, 11])
def test_save_and_load_give_identical_answers(tmp_path, dim):
    torch.manual_seed(dim)
    path = tmp_path / f"brain{dim}.pth"
    original = PPOAgent(state_dim=dim, action_dim=2, filename=str(path))
    original.save()
    loaded = PPOAgent(state_dim=dim, action_dim=2, filename=str(path))
    loaded.load(strict=True)
    x = torch.FloatTensor(np.random.default_rng(dim).normal(size=(50, dim)))
    with torch.no_grad():
        for a, b in zip(original.policy(x), loaded.policy(x)):
            assert torch.equal(a, b)
    assert infer_state_dim_from_checkpoint(str(path)) == dim


def test_a_checkpoint_of_the_wrong_shape_is_refused(tmp_path):
    path = tmp_path / "brain11.pth"
    PPOAgent(state_dim=11, action_dim=2, filename=str(path)).save()
    with pytest.raises(RuntimeError):
        PPOAgent(state_dim=7, action_dim=2, filename=str(path)).load(strict=True)


def test_a_missing_checkpoint_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError):
        PPOAgent(state_dim=11, action_dim=2, filename=str(tmp_path / "nowhere.pth")).load(strict=True)


def test_the_lenient_training_load_starts_fresh_and_says_so(tmp_path, capsys):
    path = tmp_path / "brain11.pth"
    PPOAgent(state_dim=11, action_dim=2, filename=str(path)).save()
    PPOAgent(state_dim=7, action_dim=2, filename=str(path)).load(strict=False)
    assert "shape mismatch" in capsys.readouterr().out


def test_the_app_engine_sizes_the_brain_from_the_checkpoint(tmp_path):
    # The engine reads the feature count from the file, so a 7-feature brain is never run as 11.
    path = tmp_path / "brain7.pth"
    PPOAgent(state_dim=7, action_dim=2, filename=str(path)).save()
    sim = SimulationEngine("B", SimConfig(), brain_path=str(path), governor_disabled=True)
    assert sim.feature_dim == 7
