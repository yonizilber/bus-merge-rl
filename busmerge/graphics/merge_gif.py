"""Build merge-zone animated GIF from SimulationEngine frame history."""
from __future__ import annotations

import io
from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from PIL import Image

from busmerge.config import SimConfig
from busmerge.geometry import rect_corners


def build_merge_gif(
    df: pd.DataFrame,
    config: SimConfig,
    *,
    fps: int = 5,
    max_frames: int = 120,
) -> Optional[bytes]:
    """Return GIF bytes for merge window, or None if no merge-zone data."""
    if df is None or df.empty:
        return None

    lane_w = 3.5
    bus_stop_x = float(config.bus_stop_position)
    merge_x_min, merge_x_max = 255.0, 345.0
    bay_outer_y = -lane_w - lane_w / 2
    lane_inner_y = -lane_w / 2
    bay_flat_x0 = bus_stop_x - 15.0
    bay_flat_x1 = bus_stop_x + 15.0
    entry_taper_x0 = bay_flat_x0 - 20.0
    exit_taper_x1 = bay_flat_x1 + 15.0

    mz = df[(df["x"] >= merge_x_min - 5) & (df["x"] <= merge_x_max + 5)].copy()
    if mz.empty:
        return None

    def lateral_y(row):
        tl = row.get("total_lat", row.get("lateral_offset", 0.0))
        return float(tl) if not pd.isna(tl) else 0.0

    mz["y_centre"] = mz.apply(lateral_y, axis=1)
    mz["half_w"] = mz["width"] / 2.0
    mz["half_l"] = mz["length"] / 2.0
    mz["x_centre"] = mz["x"] - mz["half_l"]  # x is the front bumper (physics convention)
    mz["heading"] = mz["heading_deg"].fillna(0.0) if "heading_deg" in mz.columns else 0.0

    bus_m = mz[(mz["type"] == "Bus") & (mz["state"] == "WAITING_TO_MERGE")]
    bus_mov = bus_m[bus_m["v"] > 0.1] if not bus_m.empty else bus_m
    if not bus_mov.empty:
        t0 = float(bus_mov["time"].min()) - 2.0
    elif not bus_m.empty:
        t0 = float(bus_m["time"].min())
    else:
        t0 = float(mz["time"].min())
    t0 = max(float(mz["time"].min()), t0)
    bus_exit = mz[(mz["type"] == "Bus") & (mz["x_centre"] > merge_x_max)]
    t1 = float(bus_exit["time"].min()) if not bus_exit.empty else float(mz["time"].max())
    times = [t for t in sorted(mz["time"].unique()) if t0 <= t <= t1]
    if len(times) > max_frames:
        step = max(1, len(times) // max_frames)
        times = times[::step]
    if not times:
        return None

    def draw_bay(ax):
        ax.axhspan(-lane_w / 2, lane_w / 2, color="#555555", zorder=0)
        ax.axhline(lane_w / 2, color="white", ls="--", lw=1.5, zorder=1)
        ax.axhline(-lane_w / 2, color="white", ls="-", lw=2.0, zorder=1)
        bay_poly = np.array([
            [entry_taper_x0, lane_inner_y],
            [bay_flat_x0, bay_outer_y],
            [bay_flat_x1, bay_outer_y],
            [exit_taper_x1, lane_inner_y],
            [exit_taper_x1, -lane_w / 2],
            [entry_taper_x0, -lane_w / 2],
        ])
        ax.add_patch(mpatches.Polygon(bay_poly, closed=True, facecolor="#444444",
                                      edgecolor="white", linewidth=0.8, zorder=0))
        ax.axvline(bus_stop_x, color="yellow", ls=":", lw=1.2, alpha=0.7, zorder=1)

    pil_frames = []
    for t_val in times:
        frame = mz[mz["time"] == t_val]
        fig, ax = plt.subplots(figsize=(12, 4))
        draw_bay(ax)
        for _, row in frame.iterrows():
            angle = float(row["heading"]) if not pd.isna(row["heading"]) else 0.0
            if row["type"] == "Bus":
                color = "#e74c3c"
            elif row.get("collision_frame") or row.get("physical_collision"):
                color = "#FF8C00"
            else:
                color = "#3498db"
            corners = rect_corners(row["x_centre"], row["y_centre"], row["half_l"], row["half_w"], np.radians(angle))
            ax.add_patch(mpatches.Polygon(corners, closed=True, facecolor=color,
                                          edgecolor="white", linewidth=1.2, zorder=5))
            label = f"BUS\n{row.get('v', 0):.1f}" if row["type"] == "Bus" else f"{int(row['id'])}\n{row.get('v', 0):.1f}"
            ax.text(row["x_centre"], row["y_centre"], label, color="white", ha="center", va="center",
                    fontsize=7, zorder=6)
        ax.set_xlim(merge_x_min, merge_x_max)
        ax.set_ylim(bay_outer_y - 0.4, lane_w / 2 + 0.5)
        ax.set_title(f"Merge zone  t = {t_val:.1f} s", fontsize=11)
        ax.set_aspect("equal")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=90, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        pil_frames.append(Image.open(buf).convert("RGBA"))

    if not pil_frames:
        return None
    out = io.BytesIO()
    pil_frames[0].save(
        out, format="GIF", save_all=True, append_images=pil_frames[1:],
        duration=int(1000 / max(fps, 1)), loop=0,
    )
    return out.getvalue()
