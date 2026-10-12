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
from busmerge.geometry import BAY_WALL_Y, bay_outline, rect_corners


MERGE_X_MIN, MERGE_X_MAX = 255.0, 345.0   # road span (m) of the merge-zone view
LEAD_IN_S = 2.0                            # the view starts this long before boarding ends


def merge_view_window(df: pd.DataFrame) -> Optional[tuple[float, float]]:
    """Time span of the merge-zone view: from shortly before boarding ends until the whole bus has
    left the view (its rear bumper passes MERGE_X_MAX), or the end of the run if it never does.
    None when the bus never finished boarding. Used by the app's 2D view and by the GIF."""
    bus = df[df["type"] == "Bus"].sort_values("time")
    waiting = bus[bus["state"].astype(str) == "WAITING_TO_MERGE"]
    if waiting.empty:
        return None
    t0 = max(float(bus["time"].min()), float(waiting["time"].min()) - LEAD_IN_S)
    gone = bus[(bus["time"] >= t0) & (bus["x"] - bus["length"] > MERGE_X_MAX)]
    t1 = float(gone["time"].min()) if not gone.empty else float(df["time"].max())
    return t0, t1


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
    merge_x_min, merge_x_max = MERGE_X_MIN, MERGE_X_MAX

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

    window = merge_view_window(df)
    t0, t1 = window if window else (float(mz["time"].min()), float(mz["time"].max()))
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
        ax.add_patch(mpatches.Polygon(bay_outline(), closed=True, facecolor="#444444",
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
        ax.set_ylim(BAY_WALL_Y - 0.4, lane_w / 2 + 0.5)
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
