"""Single definition of "run an episode" and "what was the outcome".

The Streamlit app, the production smoke test and any ad-hoc evaluation must all go
through these two functions, so that a number reported in one place means exactly the
same thing in another.
"""
from __future__ import annotations

import random
import statistics
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import torch

from busmerge.config import SimConfig
from busmerge.invariants import bus_contact_times, bus_edge_times, check_invariants
from busmerge.traffic_metrics import traffic_metrics
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

    Outcomes: ``merged``, ``collision``, ``off_road``, ``over_centre_line``, ``stuck_waiting``,
    ``never_waited``, ``no_bus``.

    * The merge starts at the first WAITING_TO_MERGE frame.
    * The merge is complete at the first later frame where the bus is MOVING or its
      lateral offset reached the production threshold (the same rule the simulation
      itself uses to leave WAITING_TO_MERGE).
    * A collision is any frame in which the bus body touches a car body (exact rotated
      polygons, busmerge.invariants), including a side contact while pulling out, not only
      running into the vehicle ahead.
    * Off road: any corner of the bus body below the kerb or the bay wall (busmerge.geometry), e.g.
      cutting the kerb or stopping past the bay. Over the centre line: a corner in the opposing lane.
      Both are failures, never a merge.
    """
    bus = df[df["type"] == "Bus"].sort_values("time") if not df.empty else df
    if bus.empty:
        return "no_bus", {}
    if "physical_collision" in bus.columns and bus["physical_collision"].any():
        return "collision", {}
    contact = bus_contact_times(df)
    if contact:
        return "collision", {"first_contact_s": contact[0], "contact_frames": len(contact)}
    off_road, over_centre = bus_edge_times(df)
    if off_road:
        return "off_road", {"first_off_road_s": off_road[0], "off_road_frames": len(off_road)}
    if over_centre:
        return "over_centre_line", {"first_over_centre_s": over_centre[0], "frames": len(over_centre)}

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
        return "merged", {"merge_s": done_t - wait_t, "boarding_ended_at_s": wait_t}

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


# Streamlit sidebar defaults (streamlit_app.py): scenario B, 0.4 cars/s, 50 cars,
# 15 s dwell, 1.35 / 20 passengers (the explorer's Israeli starting values), governor off.
APP_DEFAULTS = dict(
    total_cars_to_spawn=50, traffic_rate=0.4, bus_dwell_time=15,
    pax_per_car=1.35, pax_per_bus=20.0,
)


def _stats(values: list[float]) -> dict:
    if not values:
        return {"mean": None, "p95": None, "max": None}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    return {"mean": round(statistics.mean(values), 2), "p95": round(p95, 2), "max": round(ordered[-1], 2)}


def evaluate_brain(brain: Path, seeds: int, noise_sigma: float, traffic_rate: float, cars: int,
                   scenario: str = "B", seed_start: int = 0) -> dict:
    """Run ``seeds`` fixed-seed episodes of the app's Run button and summarise them."""
    outcomes, car_coll = [], 0
    violation_runs: dict[str, int] = {}
    violation_examples: dict[str, dict] = {}
    reported_runs: dict[str, int] = {}
    worst_decel = 0.0
    traffic: list[dict] = []
    phases: dict[str, list[float]] = {name: [] for name, _ in TIMELINE_PHASES}
    phases.update(total_s=[], standstill_s=[])
    for seed in range(seed_start, seed_start + seeds):
        cfg = SimConfig(**{**APP_DEFAULTS, "traffic_rate": traffic_rate, "total_cars_to_spawn": cars})
        sim = run_episode(scenario, cfg, str(brain), governor_disabled=True, noise_sigma=noise_sigma, seed=seed)
        df = sim.get_results()
        outcome, _ = classify_outcome(df)
        outcomes.append(outcome)
        car_coll += count_car_collisions(df)
        inv = check_invariants(df)
        traffic.append(traffic_metrics(df))
        worst_decel = min(worst_decel, inv.worst_decel)
        for kind, n in inv.counts.items():
            violation_runs[kind] = violation_runs.get(kind, 0) + (n > 0)
            if n and kind not in violation_examples:
                violation_examples[kind] = {"seed": seed, **inv.examples[kind]}
        for kind, n in inv.notes.items():
            reported_runs[kind] = reported_runs.get(kind, 0) + (n > 0)
        timeline = merge_timeline(df) if outcome == "merged" else None
        if timeline:
            for key in phases:
                phases[key].append(timeline[key])
    return {
        "brain": brain.name, "noise_sigma": noise_sigma, "traffic_rate": traffic_rate, "cars": cars,
        "seeds": len(outcomes),
        **{k: outcomes.count(k) for k in ("merged", "collision", "off_road", "over_centre_line", "stuck_waiting", "never_waited")},
        "car_collision_frames": car_coll,
        "after_boarding": {k: _stats(v) for k, v in phases.items()},
        # Physics checks (busmerge.invariants): number of runs with at least one violation of each kind.
        "physics_violation_runs": violation_runs,
        "physics_violation_examples": violation_examples,
        # Reported, not failed: runs in which a car crossed the centre line or the kerb.
        "reported_runs": reported_runs,
        "worst_decel_ms2": round(worst_decel, 2),
        # Traffic around the brain (busmerge.traffic_metrics), to show a change did not thin the traffic.
        "traffic": {k: round(float(np.nanmean([m[k] for m in traffic])), 2) for k in traffic[0]} if traffic else {},
    }
