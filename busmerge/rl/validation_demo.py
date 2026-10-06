"""
Side-by-side demo: training gym validation (9/30) vs Streamlit production engine.

Runs the same 10 held-out seeds × N episodes as train.py final validation,
then repeats with SimulationEngine so you can see why scores differ.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
import pandas as pd
import torch

from busmerge.config import SimConfig
from busmerge.evaluation import classify_outcome, run_episode
from busmerge.rl.validation_constants import (
    TRAINING_VALIDATION_SEEDS,
    DEFAULT_EPISODES_PER_SEED,
)


def _episode_scenario_seeds(seed: int, episodes: int) -> list:
    rng = random.Random(seed)
    return [rng.random() for _ in range(episodes)]


def _outcome_label(success: bool, crash: bool, timeout: bool) -> str:
    if success:
        return "success"
    if crash:
        return "crash"
    if timeout:
        return "timeout"
    return "unknown"


def scenario_name_from_roll(roll: float) -> str:
    """Map eval_mode scenario_roll to label (matches env.reset)."""
    if roll < 0.12:
        return "A heavy jam"
    if roll < 0.30:
        return "B slow city"
    if roll < 0.50:
        return "C mid-merge"
    if roll < 0.65:
        return "D fast flow"
    if roll < 0.82:
        return "E platoon burst"
    if roll >= 0.98:
        return "H dense eval"
    return "F dense urban"


def make_eval_env(ckpt_path: str, feature_dim: int, governor_disabled: bool):
    """Training env configured the way the checkpoint was trained.

    The reward/crash rules depend on the run tag (see rl/train.py): ``exp7sat*`` runs use the
    SAT polygon-overlap crash test, ``exp7satv10*`` additionally the spongy danger zone. An env
    built without these flags judges crashes with the legacy 1-D gap rule and fails every merge.
    """
    from busmerge.rl.env import BusMergeEnv

    name = Path(ckpt_path).name
    env = BusMergeEnv(eval_mode=True, governor_disabled=governor_disabled)
    env.feature_dim = feature_dim
    env.state_size = feature_dim
    env.sat_penalty_enabled = "exp7sat" in name
    env.spongy_danger_zone_enabled = "exp7satv10" in name
    return env


def run_training_episode(
    agent,
    env,
    seed: int,
    ep: int,
    scenario_seeds: list,
    governor_disabled: bool = True,
    max_steps: Optional[int] = None,
    record_frames: bool = False,
) -> tuple:
    """One BusMergeEnv episode — matches train.evaluate_policy."""
    import random as _rnd

    random.seed(seed + ep)
    np.random.seed(seed + ep)
    torch.manual_seed(seed + ep)

    def _set_episode_scenario_seed(reroll_attempt: int = 0):
        if reroll_attempt == 0:
            env._eval_scenario_seed = scenario_seeds[ep]
        else:
            _rs = seed + ep + reroll_attempt * 10000
            _rnd.seed(_rs)
            env._eval_scenario_seed = _rnd.random()

    def _reroll_spawn(attempt: int):
        _rs = seed + ep + attempt * 10000
        random.seed(_rs)
        np.random.seed(_rs)
        _set_episode_scenario_seed(attempt)

    _set_episode_scenario_seed(0)
    state = env.reset_until_clear_spawn(max_retries=20, reroll_callback=_reroll_spawn)

    roll = float(scenario_seeds[ep])
    gap0, _, _, _, _, _ = env._scan_nearest_car()
    if record_frames:
        env.engine.record_frames = True  # the engine's own frame log: same format the app plots

    done = False
    steps = 0
    limit = max_steps if max_steps is not None else env.max_steps
    while not done and steps < limit:
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0)
            action_mean, _, _ = agent.policy(state_tensor)
            action_value = action_mean.squeeze(0).numpy()
        state, _, done, _ = env.step(action_value)
        steps += 1

    progress = float(env._merge_progress())
    if env.last_success:
        outcome = "success"
    elif env.last_crash:
        outcome = "crash"
    elif env.last_timeout:
        outcome = "timeout"
    else:
        outcome = "timeout"

    row = {
        "engine": "training (BusMergeEnv)",
        "seed": seed,
        "episode": ep,
        "outcome": outcome,
        "merge_progress": progress,
        "steps": steps,
        "merge_s": round(steps * env.dt, 2) if outcome == "success" else None,
        "scenario_roll": roll,
        "scenario_name": scenario_name_from_roll(roll),
        "initial_gap_m": round(float(gap0), 2),
        "traffic_note": f"Eval {scenario_name_from_roll(roll)} — bus in bay, cars frozen at reset",
    }
    gym_df = env.engine.get_results() if record_frames else None
    return row, gym_df


def run_streamlit_episode(
    ckpt_path: str,
    seed: int,
    ep: int,
    config: SimConfig,
    governor_disabled: bool = True,
    max_steps: int = 3000,
) -> dict:
    """One SimulationEngine episode, run and judged exactly like the Streamlit app's run button."""
    engine = run_episode(
        "B", config, ckpt_path,
        governor_disabled=governor_disabled,
        seed=seed + ep,  # same RNG seeding as the training-env episode
        max_sim_time=max_steps * 0.1,  # engine dt is 0.1 s
    )
    df = engine.get_results()
    result, meta = classify_outcome(df)
    outcome = {"merged": "success", "collision": "crash"}.get(result, "timeout")
    if result == "merged":
        max_progress = 1.0
    else:
        max_progress = float(meta.get("max_progress", 0.0))

    return {
        "engine": "streamlit (SimulationEngine)",
        "seed": seed,
        "episode": ep,
        "outcome": outcome,
        "merge_progress": max_progress,
        "steps": int(engine.time / engine.dt),
        "merge_s": round(meta["merge_s"], 2) if result == "merged" else None,
        "traffic_note": f"Continuous spawn @ {config.traffic_rate}/s, max {config.total_cars_to_spawn} cars",
    }, df


def run_episode_pair(
    ckpt_path: str,
    seed: int,
    ep: int,
    episodes_per_seed: int,
    streamlit_config: SimConfig,
    governor_disabled: bool = True,
    agent=None,
    env=None,
):
    """Run one validation seed×episode in training gym + Streamlit; returns rows and GIF df."""
    from busmerge.rl.ppo_agent import PPOAgent
    from busmerge.rl.feature_encoding import infer_state_dim_from_checkpoint

    if agent is None or env is None:
        dim = infer_state_dim_from_checkpoint(ckpt_path)
        agent = PPOAgent(state_dim=dim, filename=ckpt_path)
        agent.load(strict=True)
        env = make_eval_env(ckpt_path, dim, governor_disabled)

    scenario_seeds = _episode_scenario_seeds(seed, episodes_per_seed)
    train_row, gym_df = run_training_episode(
        agent, env, seed, ep, scenario_seeds, governor_disabled=governor_disabled,
        record_frames=True,
    )
    stream_row, stream_df = run_streamlit_episode(
        ckpt_path, seed, ep, streamlit_config, governor_disabled=governor_disabled,
    )
    return train_row, stream_row, stream_df, gym_df, agent, env


def run_validation_comparison(
    ckpt_path: str,
    *,
    seeds: tuple = TRAINING_VALIDATION_SEEDS,
    episodes_per_seed: int = DEFAULT_EPISODES_PER_SEED,
    governor_disabled: bool = True,
    streamlit_config: Optional[SimConfig] = None,
    include_streamlit: bool = True,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> pd.DataFrame:
    """
    Run full validation matrix. Returns long-form DataFrame (one row per episode).
    """
    from busmerge.rl.ppo_agent import PPOAgent
    from busmerge.rl.feature_encoding import infer_state_dim_from_checkpoint

    dim = infer_state_dim_from_checkpoint(ckpt_path)
    agent = PPOAgent(state_dim=dim, filename=ckpt_path)
    agent.load(strict=True)
    env = make_eval_env(ckpt_path, dim, governor_disabled)

    if streamlit_config is None:
        streamlit_config = SimConfig(
            total_cars_to_spawn=50,
            traffic_rate=0.4,
            bus_dwell_time=15.0,
        )

    rows: List[dict] = []
    total = len(seeds) * episodes_per_seed * (2 if include_streamlit else 1)
    done = 0

    for seed in seeds:
        scenario_seeds = _episode_scenario_seeds(seed, episodes_per_seed)
        for ep in range(episodes_per_seed):
            if progress_callback:
                progress_callback(done, total, f"Training seed {seed} ep {ep}")
            rows.append(run_training_episode(
                agent, env, seed, ep, scenario_seeds, governor_disabled=governor_disabled,
            )[0])
            done += 1

            if include_streamlit:
                if progress_callback:
                    progress_callback(done, total, f"Streamlit seed {seed} ep {ep}")
                stream_row, _ = run_streamlit_episode(
                    ckpt_path, seed, ep, streamlit_config, governor_disabled=governor_disabled,
                )
                rows.append(stream_row)
                done += 1

    return pd.DataFrame(rows)


def summarize_comparison(df: pd.DataFrame) -> dict:
    """Aggregate success counts per engine."""
    if df is None or df.empty:
        return {}
    out = {}
    for engine, grp in df.groupby("engine"):
        n = len(grp)
        succ = int((grp["outcome"] == "success").sum())
        crash = int((grp["outcome"] == "crash").sum())
        to = int((grp["outcome"] == "timeout").sum())
        out[engine] = {
            "successes": succ,
            "total": n,
            "crashes": crash,
            "timeouts": to,
            "score": f"{succ}/{n}",
        }
    return out
