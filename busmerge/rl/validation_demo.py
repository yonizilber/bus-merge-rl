"""
Side-by-side demo: training gym validation (9/30) vs Streamlit production engine.

Runs the same 10 secret seeds × N episodes as train.py final validation,
then repeats with SimulationEngine so you can see why scores differ.
"""
from __future__ import annotations

import random
from typing import Callable, List, Optional

import numpy as np
import pandas as pd
import torch

from busmerge.config import SimConfig
from busmerge.simulation import SimulationEngine
from busmerge.vehicle import BusState
from busmerge.rl.merge_success import is_production_merge_complete
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


def _gym_record_frame(env, time_s: float) -> list:
    """Snapshot all vehicles for merge-zone GIF (BusMergeEnv layout)."""

    rows = []
    bus = env.bus
    progress = float(env._merge_progress())
    rows.append({
        "time": time_s,
        "id": bus.id,
        "type": "Bus",
        "x": float(bus.position),
        "v": float(bus.velocity),
        "length": float(bus.params.length),
        "width": float(bus.params.width),
        "state": bus.state.name,
        "lateral_offset": float(bus.lateral_offset),
        "total_lat": float(getattr(bus, "total_lateral_offset", bus.lateral_offset)),
        "heading_deg": float(np.degrees(bus.heading_angle)),
        "merge_progress": progress,
        "physical_collision": False,
        "collision_frame": False,
    })
    gap, _, _, _, _, nearest = env._scan_nearest_car()
    for v in env.vehicles:
        car_lat = float(getattr(v, "total_lateral_offset", 0.0))
        fg = float(gap) if nearest is not None and v.id == nearest.id else float("nan")
        phys = bool(nearest is not None and v.id == nearest.id and fg < 0.0)
        rows.append({
            "time": time_s,
            "id": v.id,
            "type": "Car",
            "x": float(v.position),
            "v": float(v.velocity),
            "length": float(v.params.length),
            "width": float(v.params.width),
            "state": "Cruising",
            "lateral_offset": car_lat,
            "total_lat": car_lat,
            "heading_deg": float(np.degrees(getattr(v, "heading_angle", 0.0))),
            "merge_progress": float("nan"),
            "physical_collision": phys,
            "collision_frame": phys,
        })
    return rows


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
    frame_rows: list = []
    if record_frames:
        frame_rows.extend(_gym_record_frame(env, 0.0))

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
        if record_frames:
            frame_rows.extend(_gym_record_frame(env, steps * env.dt))

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
    gym_df = pd.DataFrame(frame_rows) if record_frames and frame_rows else None
    return row, gym_df


def run_streamlit_episode(
    ckpt_path: str,
    seed: int,
    ep: int,
    config: SimConfig,
    governor_disabled: bool = True,
    max_steps: int = 3000,
) -> dict:
    """One SimulationEngine episode — same RNG as training (seed + ep)."""
    random.seed(seed + ep)
    np.random.seed(seed + ep)
    torch.manual_seed(seed + ep)

    engine = SimulationEngine(
        scenario="B",
        config=config,
        brain_path=ckpt_path,
        governor_disabled=governor_disabled,
    )
    engine.noise_sigma = 0.0
    engine.init_scenario()

    outcome = "timeout"
    wait_t = 0.0
    merge_t = None
    saw_wait = False
    max_progress = 0.0

    for _ in range(max_steps):
        engine.step()
        bus = next((v for v in engine.vehicles if hasattr(v, "state")), None)
        if bus is None:
            outcome = "crash"
            break

        if hasattr(bus, "lateral_offset"):
            from busmerge.rl.merge_success import merge_progress_from_lateral
            max_progress = max(max_progress, merge_progress_from_lateral(float(bus.lateral_offset)))

        if bus.state == BusState.WAITING_TO_MERGE:
            saw_wait = True
            if wait_t <= 0.0:
                wait_t = engine.time

        if is_production_merge_complete(
            float(bus.lateral_offset), bus.state, saw_waiting_to_merge=saw_wait
        ):
            if wait_t > 0:
                merge_t = engine.time - wait_t
                outcome = "success"
            break

        if bus.state not in (
            BusState.MOVING, BusState.DECELERATING,
            BusState.IN_BAY, BusState.WAITING_TO_MERGE, BusState.STOPPED_IN_LANE,
        ):
            outcome = "crash"
            break

    df = engine.get_results()
    if not df.empty and "physical_collision" in df.columns and df["physical_collision"].any():
        outcome = "crash"

    return {
        "engine": "streamlit (SimulationEngine)",
        "seed": seed,
        "episode": ep,
        "outcome": outcome,
        "merge_progress": max_progress,
        "steps": int(engine.time / engine.dt),
        "merge_s": round(merge_t, 2) if merge_t is not None else None,
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
    from busmerge.rl.env import BusMergeEnv
    from busmerge.rl.ppo_agent import PPOAgent
    from busmerge.rl.feature_encoding import infer_state_dim_from_checkpoint

    if agent is None or env is None:
        dim = infer_state_dim_from_checkpoint(ckpt_path)
        agent = PPOAgent(state_dim=dim, filename=ckpt_path)
        agent.load()
        env = BusMergeEnv(eval_mode=True, governor_disabled=governor_disabled)
        env.feature_dim = dim
        env.state_size = dim

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
    from busmerge.rl.env import BusMergeEnv
    from busmerge.rl.ppo_agent import PPOAgent
    from busmerge.rl.feature_encoding import infer_state_dim_from_checkpoint

    dim = infer_state_dim_from_checkpoint(ckpt_path)
    agent = PPOAgent(state_dim=dim, filename=ckpt_path)
    agent.load()
    env = BusMergeEnv(eval_mode=True, governor_disabled=governor_disabled)
    env.feature_dim = dim
    env.state_size = dim

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
