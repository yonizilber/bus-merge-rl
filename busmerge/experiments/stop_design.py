"""The stop-design experiment: a bus stop in a bay (scenario B) against a stop in the lane (scenario A).

One run is one (scenario, traffic rate, dwell time, seed). The cars come from an arrival schedule drawn from the
seed (``SimConfig.arrival_seed``), so the two scenarios of a seed see exactly the same cars, and a car that finds
the entry blocked waits instead of being lost. Every vehicle's trip is recorded by the engine (``trip_log``).

The unit of comparison is person-time: Σ occupancy × (exit time − scheduled arrival time). Occupancy is applied at
analysis time (``person_time``), so one set of runs serves every car and bus occupancy.

docs/reference/EXPERIMENT_STOP_DESIGN.md describes the design and every column.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

STOPPED_SPEED_MS = 0.5        # a vehicle slower than this counts as stopped (trip log and queue)
QUEUE_REACH_M = 300.0         # how far behind the bus the queue is looked for


@dataclass(frozen=True)
class Spec:
    """An experiment specification, as stored in experiments/<name>.json."""
    name: str
    brain: str
    scenarios: tuple
    traffic_rates: tuple
    dwell_times: tuple
    seed_start: int
    seed_count: int
    pilot_seeds: int
    arrival_window_s: float
    max_sim_time_s: float

    @classmethod
    def load(cls, path: Path) -> "Spec":
        from busmerge.paths import REPO_ROOT
        d = json.loads(Path(path).read_text())
        brain = Path(d["brain"])
        return cls(name=d["name"], brain=str(brain if brain.is_absolute() else REPO_ROOT / brain),
                   scenarios=tuple(d["scenarios"]),
                   traffic_rates=tuple(d["traffic_rates"]), dwell_times=tuple(d["dwell_times_s"]),
                   seed_start=d["seeds"]["start"], seed_count=d["seeds"]["count"], pilot_seeds=d["pilot_seeds"],
                   arrival_window_s=d["arrival_window_s"], max_sim_time_s=d["max_sim_time_s"])

    def tasks(self, pilot: bool = False) -> list[tuple]:
        """Every (scenario, traffic rate, dwell time, seed) of the experiment, or of its pilot."""
        n = self.pilot_seeds if pilot else self.seed_count
        return [(sc, rate, dwell, seed) for seed in range(self.seed_start, self.seed_start + n)
                for rate in self.traffic_rates for dwell in self.dwell_times for sc in self.scenarios]


def run_key(scenario: str, rate: float, dwell: float, seed: int) -> str:
    return f"{scenario}|{rate:g}|{dwell:g}|{seed}"


def trip_rows(sim, key: str) -> list[dict]:
    """One row per vehicle from the engine's trip log; a vehicle that never left the road is censored."""
    rows = []
    for vid, t in sorted(sim.trip_log.items()):
        exit_t = t["exit_t"]
        rows.append({
            "run": key, "vehicle_id": vid, "type": t["type"], "class": t["class"],
            "scheduled_t": round(t["scheduled_t"], 3), "entered_t": round(t["entered_t"], 3),
            "exit_t": None if exit_t is None else round(exit_t, 3),
            "travel_time_s": None if exit_t is None else round(exit_t - t["scheduled_t"], 3),
            "entry_wait_s": round(t["entered_t"] - t["scheduled_t"], 3),
            "stopped_s": round(t["stopped_s"], 3),
            "free_flow_s": round(sim.road_length / t["desired_speed"], 3),
            "censored": exit_t is None,
        })
    return rows


def queue_metrics(df: pd.DataFrame) -> dict:
    """The queue behind the bus while it stands at the stop: most stopped cars, and how far back it reached."""
    bus = df[df["type"] == "Bus"]
    stop = bus[bus["state"].isin(["IN_BAY", "STOPPED_IN_LANE"])]
    if stop.empty:
        return {"queue_max_cars": 0, "queue_max_m": 0.0}
    t0, t1 = float(stop["time"].min()), float(stop["time"].max()) + 5.0
    rear = float(stop["x"].iloc[0] - stop["length"].iloc[0])
    cars = df[(df["type"] == "Car") & (df["time"] >= t0) & (df["time"] <= t1)
              & (df["x"] < rear) & (df["x"] > rear - QUEUE_REACH_M) & (df["v"] < STOPPED_SPEED_MS)]
    if cars.empty:
        return {"queue_max_cars": 0, "queue_max_m": 0.0}
    per_t = cars.groupby("time")
    return {"queue_max_cars": int(per_t.size().max()),
            "queue_max_m": round(float(rear - cars["x"].min() + cars.loc[cars["x"].idxmin(), "length"]), 1)}


def run_cell(task: tuple, spec: Spec) -> tuple[dict, list[dict]]:
    """Run one (scenario, rate, dwell, seed): a summary row and the trip rows."""
    import torch
    torch.set_num_threads(1)
    from busmerge.config import SimConfig
    from busmerge.evaluation import APP_DEFAULTS, classify_outcome, merge_timeline, run_episode
    from busmerge.invariants import bus_contact_times, bus_edge_times, check_invariants

    scenario, rate, dwell, seed = task
    key = run_key(scenario, rate, dwell, seed)
    cfg = SimConfig(**{**APP_DEFAULTS, "traffic_rate": rate, "bus_dwell_time": dwell, "arrival_seed": seed,
                       "arrival_window_s": spec.arrival_window_s})
    sim = run_episode(scenario, cfg, spec.brain, governor_disabled=True, seed=seed,
                      max_sim_time=spec.max_sim_time_s)
    df = sim.get_results()
    trips = trip_rows(sim, key)
    bus = next(t for t in trips if t["type"] == "Bus")
    cars = [t for t in trips if t["type"] == "Car"]
    outcome, _ = classify_outcome(df) if scenario == "B" else ("in_lane", {})
    timeline = merge_timeline(df) if scenario == "B" else None
    off_road, over_centre = bus_edge_times(df) if scenario == "B" else ([], [])
    counts = check_invariants(df).counts
    row = {
        "run": key, "scenario": scenario, "traffic_rate": rate, "dwell_s": dwell, "seed": seed,
        "n_cars": len(cars), "sim_time_s": round(sim.time, 1),
        "censored": any(t["censored"] for t in trips),
        "bus_travel_time_s": bus["travel_time_s"], "bus_stopped_s": bus["stopped_s"],
        "cars_travel_time_s": round(sum(t["travel_time_s"] or 0.0 for t in cars), 3),
        "cars_entry_wait_s": round(sum(t["entry_wait_s"] for t in cars), 3),
        "max_entry_wait_s": max((t["entry_wait_s"] for t in cars), default=0.0),
        "merge_time_s": None if timeline is None else round(timeline["total_s"], 2),
        "outcome": outcome,
        "bus_contact": bool(bus_contact_times(df)),
        "bus_off_road": bool(off_road), "bus_over_centre": bool(over_centre),
        "violations": json.dumps({k: n for k, n in counts.items() if n}, sort_keys=True),
        **queue_metrics(df),
    }
    return row, trips


def person_time(runs: pd.DataFrame, pax_car: float, pax_bus: float) -> pd.Series:
    """Person-time of each run (person-seconds): occupancy × travel time, summed over the bus and the cars."""
    return pax_bus * runs["bus_travel_time_s"] + pax_car * runs["cars_travel_time_s"]


def paired_difference(runs: pd.DataFrame, pax_car: float, pax_bus: float,
                      dwell_lane: float | None = None, dwell_bay: float | None = None) -> pd.DataFrame:
    """ΔPT = PT(bay, B) − PT(lane, A) per (traffic rate, seed). Negative: the bay moves people faster.

    By default each dwell time is compared with itself; ``dwell_lane`` and ``dwell_bay`` pair different ones (for
    example a shorter, more precise stop in the lane)."""
    r = runs.assign(pt=person_time(runs, pax_car, pax_bus))
    a = r[r["scenario"] == "A"]
    b = r[r["scenario"] == "B"]
    if dwell_lane is not None:
        a = a[a["dwell_s"] == dwell_lane]
    if dwell_bay is not None:
        b = b[b["dwell_s"] == dwell_bay]
    on = ["traffic_rate", "seed"] + ([] if dwell_lane is not None or dwell_bay is not None else ["dwell_s"])
    m = b.merge(a, on=on, suffixes=("_b", "_a"))
    m["delta_pt"] = m["pt_b"] - m["pt_a"]
    m["delta_bus_pt"] = pax_bus * (m["bus_travel_time_s_b"] - m["bus_travel_time_s_a"])
    m["delta_car_pt"] = pax_car * (m["cars_travel_time_s_b"] - m["cars_travel_time_s_a"])
    return m
