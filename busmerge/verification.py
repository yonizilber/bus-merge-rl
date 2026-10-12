"""One verification run per seed, as `scripts/verify_brain.py` reports it.

Every run is the app's own episode (busmerge.evaluation.run_episode) checked by busmerge.invariants
with nothing clamped. The row records the merge outcome judged on the traffic only, the bus's
road-edge anomalies and the stage they happened in, every other physics violation, car edge
crossings (reported only) and the traffic actually present.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor


def run_seeds(brain: str, seeds, traffic_rate: float = 0.4, cars: int = 50, workers: int | None = None) -> list[dict]:
    """Verification rows for ``seeds``, run in parallel processes."""
    workers = workers or max(1, (os.cpu_count() or 2) // 2)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run_seed, [(str(brain), s, traffic_rate, cars) for s in seeds], chunksize=4))


def run_seed(args: tuple[str, int, float, int]) -> dict:
    brain, seed, traffic_rate, cars = args
    import torch
    torch.set_num_threads(1)
    from busmerge.config import SimConfig
    from busmerge.evaluation import APP_DEFAULTS, classify_outcome, merge_timeline, run_episode
    from busmerge.invariants import bus_contact_times, bus_edge_times, check_invariants, edge_masks

    from busmerge.traffic_metrics import traffic_metrics
    cfg = SimConfig(**{**APP_DEFAULTS, "traffic_rate": traffic_rate, "total_cars_to_spawn": cars})
    df = run_episode("B", cfg, brain, governor_disabled=True, seed=seed).get_results()
    outcome, meta = classify_outcome(df)
    inv = check_invariants(df)
    bus = df[df["type"] == "Bus"].set_index("time")["state"]
    off_road, over_centre = bus_edge_times(df)

    # Merge outcome judged without the road edges: what the brain did with the traffic.
    if bus_contact_times(df) or ("physical_collision" in df and df.loc[df["type"] == "Bus", "physical_collision"].any()):
        merge_outcome = "collision"
    elif outcome in ("off_road", "over_centre_line"):
        tl = merge_timeline(df)
        merge_outcome = "merged" if tl else "stuck_waiting"
    else:
        merge_outcome = outcome
    timeline = merge_timeline(df) if merge_outcome == "merged" else None
    # Report only: when the whole bus body is first inside the lane after boarding ends (whatever the
    # "merged" criterion says), and the highest lateral position it reaches while merging.
    merging = df[(df["type"] == "Bus") & (df["state"] == "WAITING_TO_MERGE")]
    in_lane_s, max_lateral = None, None
    if not merging.empty:
        below, _ = _edge_excess_lane(merging)
        if (below <= 0).any():
            in_lane_s = round(float(merging["time"].to_numpy()[(below <= 0).argmax()] - merging["time"].iloc[0]), 1)
        max_lateral = round(float(merging["lateral_offset"].max()), 3)
    cars = df[df["type"] == "Car"]
    car_below, car_above = edge_masks(cars)
    other = {k: n for k, n in inv.counts.items()
             if n and k not in ("overlap", "off_road", "over_centre_line")}   # bus geometry is reported above
    car_overlap = check_invariants(cars).counts["overlap"]
    if car_overlap:
        other["car_car_overlap"] = car_overlap
    return {
        "seed": seed,
        "strict_outcome": outcome,
        "merge_outcome": merge_outcome,
        "merge_total_s": timeline["total_s"] if timeline else None,
        "off_road_stage": _where(df, off_road[0]) if off_road else "",
        "over_centre_stage": str(bus.get(over_centre[0], "")) if over_centre else "",
        "first_off_road_s": off_road[0] if off_road else None,
        "first_over_centre_s": over_centre[0] if over_centre else None,
        "car_off_road": int(car_below.any() or car_above.any()),
        "car_edge": ("kerb" if car_below.any() else "") + ("+" if car_below.any() and car_above.any() else "")
                    + ("centre line" if car_above.any() else ""),
        "car_max_over_centre_m": _max_over_centre(cars) if car_above.any() else 0.0,
        "other_violations": other,
        "first_contact_s": meta.get("first_contact_s"),
        "body_in_lane_s": in_lane_s,
        "traffic": traffic_metrics(df),
        "max_lateral_merging_m": max_lateral,
    }


def _edge_excess_lane(rows):
    """How far each row's body reaches below the lane's kerb (the bay does not count as lane)."""
    import numpy as np
    from busmerge.geometry import KERB_Y, body_corners_xy
    _, ys = body_corners_xy(rows["x"].to_numpy(dtype=float), rows["total_lat"].to_numpy(dtype=float),
                            rows["length"].to_numpy(dtype=float), rows["width"].to_numpy(dtype=float),
                            np.radians(rows["heading_deg"].to_numpy(dtype=float)))
    return KERB_Y - ys.min(axis=1), None


def _where(df, t: float) -> str:
    """Stage of the run at the first off-road frame, with entering/leaving the bay told apart."""
    from busmerge.rl.merge_constants import BAY_FLAT_END_X, BAY_FLAT_START_X
    b = df[(df["type"] == "Bus") & (df["time"] == t)].iloc[0]
    if b["state"] == "DECELERATING" and b["x"] - b["length"] < BAY_FLAT_START_X and b["x"] < BAY_FLAT_START_X + 5:
        return "pulling in: kerb before the bay"
    if b["state"] in ("DECELERATING", "IN_BAY") and b["x"] > BAY_FLAT_END_X:
        return "stopped past the end of the bay"
    return str(b["state"])


def _max_over_centre(cars) -> float:
    from busmerge.invariants import _edge_excess
    return round(float(_edge_excess(cars)[1].max()), 2)
