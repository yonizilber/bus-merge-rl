"""
Post-run queue / lane-order analytics.

Detects longitudinal overtakes (space–time line crossings), negative bumper gaps,
and large single-frame position jumps. Used by Streamlit to inspect bypass events.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

_LEADER_ID_RE = re.compile(r"ID\s+(-?\d+)")


def parse_leader_id(leader_info: Any) -> Optional[int]:
    if leader_info is None or (isinstance(leader_info, float) and np.isnan(leader_info)):
        return None
    s = str(leader_info)
    if s in ("Clear Road", "N/A", "", "nan"):
        return None
    m = _LEADER_ID_RE.search(s)
    return int(m.group(1)) if m else None


def merge_end_time(df: pd.DataFrame, bus_id: int = 999) -> Optional[float]:
    """First MOVING frame after the bus has entered WAITING_TO_MERGE (merge complete)."""
    bus = df[(df["id"] == bus_id) & (df["type"] == "Bus")].sort_values("time")
    if bus.empty:
        return None
    saw_wait = False
    for _, row in bus.iterrows():
        st = str(row.get("state", ""))
        if "WAITING_TO_MERGE" in st:
            saw_wait = True
        elif saw_wait and st == "MOVING":
            return float(row["time"])
    return None


def detect_chart_artifact_crossings(
    full_df: pd.DataFrame,
    chart_df: pd.DataFrame,
    *,
    time_tol_s: float = 2.0,
) -> pd.DataFrame:
    """
    Crossings visible in subsampled chart data but absent in full frame history.

    These are visualization chords (20% sampling), not physics overtakes.
    """
    full_ot = detect_longitudinal_overtakes(full_df, post_merge_only=False)
    chart_ot = detect_longitudinal_overtakes(chart_df, post_merge_only=False)
    if chart_ot.empty:
        return pd.DataFrame()
    if full_ot.empty:
        out = chart_ot.copy()
        out["artifact"] = True
        return out

    rows = []
    for _, cr in chart_ot.iterrows():
        p, q, t = int(cr["passer_id"]), int(cr["passed_id"]), float(cr["time"])
        match = full_ot[
            (
                (full_ot["passer_id"] == p) & (full_ot["passed_id"] == q)
                | (full_ot["passer_id"] == q) & (full_ot["passed_id"] == p)
            )
            & (full_ot["time"].sub(t).abs() <= time_tol_s)
        ]
        if match.empty:
            r = cr.to_dict()
            r["artifact"] = True
            rows.append(r)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def detect_position_jumps(
    df: pd.DataFrame,
    *,
    min_dx_m: float = 3.0,
    vehicle_ids: Optional[List[int]] = None,
) -> pd.DataFrame:
    """Single-frame |Δx| spikes (physics teleports)."""
    sub = df.copy()
    if vehicle_ids is not None:
        sub = sub[sub["id"].isin(vehicle_ids)]
    if "dx" not in sub.columns:
        sub = sub.sort_values(["id", "time"])
        sub["dx"] = sub.groupby("id")["x"].diff()
    hits = sub[sub["dx"].abs() >= min_dx_m].copy()
    if hits.empty:
        return hits
    cols = ["time", "id", "type", "x", "dx", "v", "state", "leader_info"]
    return hits[[c for c in cols if c in hits.columns]].sort_values(["time", "id"])


def detect_negative_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """Frames where recorded front_gap < 0 (longitudinal overlap)."""
    if "front_gap" not in df.columns:
        return pd.DataFrame()
    hits = df[(df["type"] == "Car") & df["front_gap"].notna() & (df["front_gap"] < -0.05)].copy()
    if hits.empty:
        return hits
    cols = ["time", "id", "x", "v", "front_gap", "lateral_gap", "leader_info", "state"]
    return hits[[c for c in cols if c in hits.columns]].sort_values(["time", "id"])


def detect_longitudinal_overtakes(
    df: pd.DataFrame,
    *,
    min_sep_m: float = 2.0,
    post_merge_only: bool = True,
    merge_end_t: Optional[float] = None,
    include_bus: bool = True,
) -> pd.DataFrame:
    """
    Car A overtakes car B when A's front x crosses from behind to ahead of B's front x.

    Returns one row per crossing with passer, passed, crossing time/position.
    """
    if merge_end_t is None and post_merge_only:
        merge_end_t = merge_end_time(df)

    types = ["Car", "Bus"] if include_bus else ["Car"]
    veh = df[df["type"].isin(types)].copy()
    if veh.empty:
        return pd.DataFrame()

    ids = sorted(veh["id"].unique())
    rows: List[Dict[str, Any]] = []

    for passer in ids:
        p = veh[veh["id"] == passer].sort_values("time")
        p_min, p_max = float(p["x"].min()), float(p["x"].max())
        for passed in ids:
            if passer == passed:
                continue
            q = veh[veh["id"] == passed].sort_values("time")
            q_min, q_max = float(q["x"].min()), float(q["x"].max())
            if p_max < q_min - min_sep_m or q_max < p_min - min_sep_m:
                continue
            merged = pd.merge(
                p[["time", "x", "v", "type", "state"]],
                q[["time", "x", "v", "type", "state"]],
                on="time",
                suffixes=("_passer", "_passed"),
            )
            if len(merged) < 2:
                continue
            rel = merged["x_passer"] - merged["x_passed"]
            for i in range(1, len(merged)):
                t = float(merged["time"].iloc[i])
                if post_merge_only and merge_end_t is not None and t < merge_end_t:
                    continue
                r0, r1 = float(rel.iloc[i - 1]), float(rel.iloc[i])
                crossed = (r0 < -min_sep_m and r1 > min_sep_m) or (r0 < 0.0 and r1 >= 0.0)
                if crossed:
                    rows.append({
                        "time": t,
                        "x_cross": float(merged["x_passer"].iloc[i]),
                        "passer_id": int(passer),
                        "passed_id": int(passed),
                        "passer_type": str(merged["type_passer"].iloc[i]),
                        "passed_type": str(merged["type_passed"].iloc[i]),
                        "passer_v": float(merged["v_passer"].iloc[i]),
                        "passed_v": float(merged["v_passed"].iloc[i]),
                        "delta_x_before_m": -r0,
                        "post_merge": merge_end_t is not None and t >= merge_end_t,
                    })
                    break

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values(["time", "passer_id", "passed_id"])
    return out.drop_duplicates(subset=["time", "passer_id", "passed_id"], keep="first")


def filter_exempt_overtakes(
    df: pd.DataFrame,
    overtakes: pd.DataFrame,
    *,
    bus_id: int = 999,
) -> pd.DataFrame:
    """
    Drop expected crossings — not simulation bugs.

    - Cars passing a stationary bus in bay / merge (legal).
    - Bus passing cars only flagged when bus was MOVING with queue (handled upstream).
    """
    if overtakes.empty:
        return overtakes
    bus = df[(df["id"] == bus_id) & (df["type"] == "Bus")][
        ["time", "state", "v", "x"]
    ].sort_values("time")
    if bus.empty:
        return overtakes
    bus_by_t = bus.set_index("time")
    keep = []
    for _, row in overtakes.iterrows():
        t = float(row["time"])
        passed = int(row["passed_id"])
        if passed != bus_id:
            keep.append(row)
            continue
        # Nearest bus frame at crossing time
        if t in bus_by_t.index:
            br = bus_by_t.loc[t]
        else:
            idx = (bus["time"] - t).abs().idxmin()
            br = bus.loc[idx]
        st = str(br["state"])
        bv = float(br["v"])
        if (
            ("IN_BAY" in st or "STOPPED" in st or "WAITING_TO_MERGE" in st)
            and bv < 2.0
        ):
            continue  # car legitimately passes stopped / merging bus
        keep.append(row)
    if not keep:
        return pd.DataFrame(columns=overtakes.columns)
    return pd.DataFrame(keep)


def detect_queue_rank_flips(df: pd.DataFrame) -> pd.DataFrame:
    """
    Same-lane order inversions: car ranked behind another at t−Δt is ahead at t.
    """
    cars = df[df["type"] == "Car"].copy()
    if cars.empty:
        return pd.DataFrame()

    rows: List[Dict[str, Any]] = []
    for t in sorted(cars["time"].unique()):
        if t <= 0:
            continue
        now = cars[cars["time"] == t].set_index("id")["x"]
        prev = cars[cars["time"] == t - 0.1].set_index("id")["x"]
        common = now.index.intersection(prev.index)
        if len(common) < 2:
            continue
        for a in common:
            for b in common:
                if a == b:
                    continue
                if prev[a] < prev[b] - 1.0 and now[a] > now[b] + 1.0:
                    rows.append({
                        "time": t,
                        "passer_id": int(a),
                        "passed_id": int(b),
                        "x_passer": float(now[a]),
                        "x_passed": float(now[b]),
                        "flip_gap_m": float(now[a] - now[b]),
                    })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("time")


def event_window(
    df: pd.DataFrame,
    center_t: float,
    vehicle_ids: List[int],
    *,
    half_width_s: float = 3.0,
) -> pd.DataFrame:
    """Slice full frame history around an event for inspection."""
    lo, hi = center_t - half_width_s, center_t + half_width_s
    sub = df[(df["time"] >= lo) & (df["time"] <= hi) & (df["id"].isin(vehicle_ids))]
    cols = [
        "time", "id", "type", "x", "dx", "v", "state", "bus_control",
        "leader_info", "front_gap", "lateral_gap", "total_lat",
        "yield_eff", "physical_collision",
    ]
    return sub[[c for c in cols if c in sub.columns]].sort_values(["time", "id"])


def summarize_queue_anomalies(
    df: pd.DataFrame,
    chart_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Run all detectors; return tables + merge cutoff for UI."""
    merge_t = merge_end_time(df)
    overtakes = detect_longitudinal_overtakes(df, merge_end_t=merge_t)
    overtakes = filter_exempt_overtakes(df, overtakes)
    rank_flips = detect_queue_rank_flips(df)
    neg_gaps = detect_negative_gaps(df)
    jumps = detect_position_jumps(df, min_dx_m=3.0)
    chart_artifacts = (
        detect_chart_artifact_crossings(df, chart_df)
        if chart_df is not None else pd.DataFrame()
    )

    post_ot = overtakes
    if merge_t is not None and not overtakes.empty:
        post_ot = overtakes[overtakes["time"] >= merge_t]

    return {
        "merge_end_t": merge_t,
        "overtakes": overtakes,
        "post_merge_overtakes": post_ot,
        "rank_flips": rank_flips,
        "negative_gaps": neg_gaps,
        "position_jumps": jumps,
        "chart_artifact_crossings": chart_artifacts,
    }
