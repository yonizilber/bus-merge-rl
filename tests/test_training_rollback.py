"""Training never throws its learning away by restoring weights that were never better (BUGS P18).

The fine-tune recipe copies the starting brain to the run's `_best` file. Under the old rule, a run
whose evaluations had no success was reset to that copy every few evaluations, so it could never
learn its way out of 0 successes.
"""
import pytest

import busmerge.rl.train as training
from busmerge.rl.ppo_agent import PPOAgent


@pytest.mark.parametrize("windows,patience,best_successes,expected", [
    (10, 3, 0, False),    # never succeeded: there is no better checkpoint to go back to
    (3, 3, 26, True),     # the best checkpoint evaluated with successes: restore it after `patience`
    (2, 3, 26, False),    # not before `patience` evaluations without improvement
    (10, 0, 26, False),   # patience 0 disables rollback
])
def test_rollback_rule(windows, patience, best_successes, expected):
    assert training.rollback_due(windows, patience, best_successes) is expected


def _train_from_a_copied_start(tmp_path, monkeypatch, capsys) -> str:
    monkeypatch.setattr(training, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(training, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(training, "ENV_FLAGS", dict(training.ENV_FLAGS))
    PPOAgent(state_dim=11, action_dim=2, filename=str(tmp_path / "ppo_bus_brain_exp7satci_best.pth")).save()
    training.train(epochs=2, batch_size=128, eval_episodes=1, eval_interval=1, skip_baseline_eval=True,
                   run_tag="exp7satci", curriculum_phase1_end=0, curriculum_phase2_end=0, traffic_first=True,
                   feature_dim=11, governor_disabled=True, seed=0, rollback_patience=1)
    out = capsys.readouterr().out
    assert "Loaded best-eval policy" in out and "Succ: 0/" in out, "precondition: started from the copy, no success"
    return out


def test_a_run_that_never_succeeds_is_not_reset_to_its_starting_weights(tmp_path, monkeypatch, capsys):
    assert "Rollback triggered" not in _train_from_a_copied_start(tmp_path, monkeypatch, capsys)


def test_the_old_rule_would_have_reset_it(tmp_path, monkeypatch, capsys):
    # The test above must be able to fail: with the old rule (patience only) the same run is reset.
    monkeypatch.setattr(training, "rollback_due", lambda windows, patience, best: patience > 0 and windows >= patience)
    assert "Rollback triggered" in _train_from_a_copied_start(tmp_path, monkeypatch, capsys)
