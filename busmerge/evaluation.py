"""Single definition of "run an episode" and "what was the outcome".

The Streamlit app, the production smoke test and any ad-hoc evaluation must all go
through these two functions, so that a number reported in one place means exactly the
same thing in another.
"""
from __future__ import annotations

import random
from typing import Optional

import numpy as np
import pandas as pd
import torch

from busmerge.config import SimConfig
from busmerge.rl.merge_success import PRODUCTION_MERGE_LATERAL_THRESHOLD
from busmerge.simulation import SimulationEngine

MAX_SIM_TIME_S = 300.0


def run_episode(
    scenario: str,
    config: SimConfig,
    brain_path: Optional[str],
    *,
    governor_disabled: bool,
    noise_sigma: float = 0.0,
    seed: Optional[int] = None,
    max_sim_time: float = MAX_SIM_TIME_S,
    on_progress=None,
) -> SimulationEngine:
    """Run one full simulation exactly as the Streamlit "Run Simulation" button does.

    The episode ends when every vehicle has finished or ``max_sim_time`` is reached.
    ``seed=None`` leaves the global RNGs untouched (the app's interactive behaviour).
    """
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)

    sim = SimulationEngine(
        scenario=scenario,
        config=config,
        brain_path=brain_path,
        governor_disabled=governor_disabled,
    )
    sim.noise_sigma = noise_sigma
    sim.init_scenario()

    frame_count = 0
    while not sim.all_vehicles_finished():
        sim.step()
        frame_count += 1
        if frame_count * sim.dt >= max_sim_time:
            break
        if on_progress is not None and frame_count % 10 == 0:
            on_progress(sim)
    return sim


def classify_outcome(df: pd.DataFrame) -> tuple[str, dict]:
    """Classify a finished run from its frame log.

    Outcomes: ``merged``, ``collision``, ``stuck_waiting``, ``never_waited``, ``no_bus``.

    * The merge starts at the first WAITING_TO_MERGE frame.
    * The merge is complete at the first later frame where the bus is MOVING or its
      lateral offset reached the production threshold (the same rule the simulation
      itself uses to leave WAITING_TO_MERGE).
    * A collision is any frame in which the *bus* physically overlaps its leader.
    """
    bus = df[df["type"] == "Bus"].sort_values("time") if not df.empty else df
    if bus.empty:
        return "no_bus", {}
    if "physical_collision" in bus.columns and bus["physical_collision"].any():
        return "collision", {}

    states = bus["state"].astype(str)
    waiting = states == "WAITING_TO_MERGE"
    if not waiting.any():
        return "never_waited", {}
    wait_t = float(bus.loc[waiting, "time"].min())

    after = bus[bus["time"] >= wait_t]
    done = (after["state"].astype(str) == "MOVING") | (
        after["lateral_offset"] >= PRODUCTION_MERGE_LATERAL_THRESHOLD
    )
    if done.any():
        done_t = float(after.loc[done, "time"].min())
        return "merged", {"merge_s": done_t - wait_t, "wait_before_merge_s": wait_t}

    meta = {"wait_s": float(bus["time"].max()) - wait_t}
    if "merge_progress" in after.columns:
        meta["max_progress"] = float(after["merge_progress"].max())
    return "stuck_waiting", meta


def count_car_collisions(df: pd.DataFrame) -> int:
    """Number of car frames with a physical overlap (reported, not counted as a brain failure)."""
    if df.empty or "physical_collision" not in df.columns:
        return 0
    return int(df[df["type"] != "Bus"]["physical_collision"].sum())


# Phase names, in the order they occur after boarding ends (WAITING_TO_MERGE begins).
TIMELINE_PHASES = (
    ("hesitation_s", "Boarding done → bus starts to move"),
    ("leaving_bay_s", "Starts moving → bus edge enters the travel lane"),
    ("entering_lane_s", "Edge in lane → merge counted complete (MOVING)"),
    ("settling_s", "MOVING → fully centred in lane (progress ≥ 0.995)"),
)
_MOVING_SPEED_MS = 0.2
_FULL_PROGRESS = 0.995


def merge_timeline(df: pd.DataFrame) -> Optional[dict]:
    """Break the time from end-of-boarding to fully-merged into phases.

    Boarding ends when the bus enters WAITING_TO_MERGE (the dwell timer expired), so
    ``total_s`` is exactly the delay the bus suffers after its passengers are on board.
    Returns ``None`` if the bus never reached WAITING_TO_MERGE or never finished merging.

    ``standstill_s`` is the time the bus sat (almost) still while WAITING_TO_MERGE; a
    hesitant agent shows it as a large value even if the final manoeuvre is quick.
    """
    bus = df[df["type"] == "Bus"].sort_values("time")
    if bus.empty:
        return None
    waiting = bus[bus["state"].astype(str) == "WAITING_TO_MERGE"]
    if waiting.empty:
        return None
    t0 = float(waiting["time"].iloc[0])
    after = bus[bus["time"] >= t0]

    from busmerge.rl.merge_constants import BAY_DEPTH, LANE_WIDTH

    def first_time(mask) -> Optional[float]:
        hit = after.loc[mask, "time"]
        return float(hit.iloc[0]) if len(hit) else None

    t_move = first_time((after["v"] > _MOVING_SPEED_MS) | (after["lateral_offset"] > BAY_DEPTH + 0.05))
    edge_in_lane = after["lateral_offset"] + after["width"] / 2.0 > -LANE_WIDTH / 2.0
    t_lane = first_time(edge_in_lane)
    t_moving = first_time(
        (after["state"].astype(str) == "MOVING") | (after["lateral_offset"] >= PRODUCTION_MERGE_LATERAL_THRESHOLD)
    )
    t_full = first_time(after["merge_progress"] >= _FULL_PROGRESS)
    marks = [t0, t_move, t_lane, t_moving, t_full]
    if any(m is None for m in marks):
        return None
    # Enforce a monotone timeline (e.g. progress can reach 0.995 marginally before the MOVING flip).
    for i in range(1, len(marks)):
        marks[i] = max(marks[i], marks[i - 1])

    dt = float(after["time"].diff().median() or 0.1)
    waiting_after = after[after["state"].astype(str) == "WAITING_TO_MERGE"]
    standstill = float((waiting_after["v"] <= _MOVING_SPEED_MS).sum()) * dt
    out = {name: round(marks[i + 1] - marks[i], 3) for i, (name, _) in enumerate(TIMELINE_PHASES)}
    out["total_s"] = round(marks[-1] - marks[0], 3)
    out["standstill_s"] = round(standstill, 3)
    out["boarding_ended_at_s"] = round(t0, 3)
    return out
