#!/usr/bin/env python3
"""One committed summary of both stop-design experiments, for every page that quotes them.

    python scripts/summarize_stop_experiments.py            # writes results/experiments/stop_design/combined.json
    python scripts/summarize_stop_experiments.py --figures  # also redraws docs/media/stop_design_break_even_bus.{en,he}.png

Reads the raw runs (outputs/experiments/stop_design_v1: dwell 10 to 45 s, 300 seeds; stop_design_v2: dwell 0 to 6 s,
150 seeds; outputs/ is not committed) and keeps what is needed to rebuild the paired person-time difference for ANY
occupancies, without the raw data:

    ΔPT = pax_bus · a + pax_car · b,   a = ΔT_bus (bay − lane, s),   b = ΔT_cars (bay − lane, s, summed over cars)

For every traffic rate and every pairing of a lane dwell time with a bay dwell time (the same seed gives the same cars
in both designs): [n, mean a, mean b, var a, var b, cov ab]. For the cells with the same dwell time in both designs it
also keeps the queue, the merge, the driver's contacts and kerb clipping, and a and b without the seeds whose bay run
ended in contact. The occupancies are not in this file: they are the reader's choice, applied on the pages.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import analyze_stop_experiment as an  # noqa: E402
from busmerge.experiments.stop_design import paired_difference  # noqa: E402

OUTPUTS = REPO / "outputs" / "experiments"
EXPERIMENTS = ("stop_design_v1", "stop_design_v2")
GEOMETRY = REPO / "results" / "experiments" / "stop_design_v2" / "stop_geometry.json"
OUT = REPO / "results" / "experiments" / "stop_design" / "combined.json"
MEDIA = REPO / "docs" / "media"
RATES = (0.1, 0.2, 0.3, 0.4, 0.5)


def load_runs() -> tuple[pd.DataFrame, list[dict]]:
    runs, provenance = [], []
    for name in EXPERIMENTS:
        r, _ = an.load(OUTPUTS / name)
        runs.append(r)
        p = json.loads((OUTPUTS / name / "provenance.json").read_text(encoding="utf-8"))
        provenance.append({k: p[k] for k in ("experiment", "commit", "brain_version", "date", "runs_stored")})
    return pd.concat(runs, ignore_index=True), provenance


def _ab(m: pd.DataFrame) -> pd.DataFrame:
    return m.assign(a=m["bus_travel_time_s_b"] - m["bus_travel_time_s_a"], b=m["cars_travel_time_s_b"] - m["cars_travel_time_s_a"])


def pairing_table(runs: pd.DataFrame, dwells: list[int]) -> dict:
    """{rate: {dwell_lane: {dwell_bay: [n, mean a, mean b, var a, var b, cov ab]}}} over the common seeds."""
    table: dict = {}
    for lane in dwells:
        for bay in dwells:
            m = _ab(paired_difference(runs, 1.0, 1.0, dwell_lane=lane, dwell_bay=bay))
            for rate, g in m.groupby("traffic_rate"):
                cov = np.cov(g["a"], g["b"], ddof=1)
                table.setdefault(f"{rate:g}", {}).setdefault(str(lane), {})[str(bay)] = [
                    int(len(g)), round(float(g["a"].mean()), 4), round(float(g["b"].mean()), 4),
                    round(float(cov[0, 0]), 4), round(float(cov[1, 1]), 4), round(float(cov[0, 1]), 4)]
    return table


def cell_details(runs: pd.DataFrame, dwells: list[int]) -> dict:
    """{rate: {dwell: {...}}} for the same dwell time in both designs."""
    m = _ab(paired_difference(runs, 1.0, 1.0))
    out: dict = {}
    for (rate, dwell), g in m.groupby(["traffic_rate", "dwell_s"]):
        a = runs[(runs.scenario == "A") & (runs.traffic_rate == rate) & (runs.dwell_s == dwell)]
        b = runs[(runs.scenario == "B") & (runs.traffic_rate == rate) & (runs.dwell_s == dwell)]
        clean = g[~g["bus_contact_b"].astype(bool)]
        out.setdefault(f"{rate:g}", {})[str(int(dwell))] = {
            "pairs": int(len(g)), "cars_per_run": round(float(g["n_cars_a"].mean()), 1),
            "lane_queue_max_cars_mean": round(float(a["queue_max_cars"].mean()), 1),
            "lane_queue_max_cars_max": int(a["queue_max_cars"].max()),
            "lane_entry_wait_max_s_mean": round(float(a["max_entry_wait_s"].mean()), 1),
            "bay_merge_time_s_mean": round(float(b["merge_time_s"].mean()), 1),
            "bay_contact_runs": int(b["bus_contact"].sum()), "bay_off_road_runs": int(b["bus_off_road"].sum()),
            "bay_runs": int(len(b)), "censored_runs": int(a["censored"].sum() + b["censored"].sum()),
            "a_without_contact": round(float(clean["a"].mean()), 4), "b_without_contact": round(float(clean["b"].mean()), 4),
        }
    return out


def figure(data: dict, lang: str) -> Path:
    """The bus load below which the bay wins, against the dwell time, one line per traffic rate (car occupancy 1.35)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams["font.family"] = "DejaVu Sans"
    shape = an._t(lang)
    he = lang == "he"
    pc, cap = 1.35, 100
    dwells = data["dwells"]
    fig, ax = plt.subplots(figsize=(8.5, 6.2))
    fig.subplots_adjust(bottom=0.30, top=0.92)
    colours = plt.cm.viridis(np.linspace(0.05, 0.85, len(RATES)))
    for rate, col in zip(RATES, colours):
        ys = []
        for d in dwells:
            _, a, b, *_ = data["pairs"][f"{rate:g}"][str(d)][str(d)]
            ys.append(min(-pc * b / a, cap) if a > 0 and b < 0 else 0.0)
        label = f"{rate:g} " + ("מכוניות לשנייה" if he else "cars/s")
        ax.plot(dwells, ys, marker="o", color=col, label=shape(label))
    ax.set_xlim(0, max(dwells))
    ax.set_ylim(0, cap)
    ax.set_xlabel(shape("זמן העצירה בשניות, זהה בשני התכנונים" if he else "dwell time (s), the same in both designs"))
    ax.set_ylabel(shape("נוסעים באוטובוס בנקודת האיזון" if he else "bus passengers at the tipping point"))
    ax.set_title(shape("מתחת לקו המפרץ עדיף, מעליו הנתיב" if he else "Below a line the bay wins; above it, the lane"))
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    caption = (
        "כמה נוסעים צריכים להיות באוטובוס כדי שהנתיב ינצח, לפי זמן העצירה ועוצמת התנועה, עם 1.35 אנשים במכונית, "
        "אמצע הטווח הישראלי. כל קו הוא עוצמת תנועה אחת, וכל נקודה היא ממוצע על זוגות הרצות עם אותן מכוניות. "
        "כשבאוטובוס פחות נוסעים מהקו המפרץ מעביר אנשים מהר יותר, וכשיותר הנתיב. קו על אפס: הנתיב עדיף בכל מספר "
        "נוסעים, כי המפרץ מאט גם את המכוניות. הנקודה נחתכת ב-100. עם 1.2 או 1.5 אנשים במכונית כל ערך קטן או גדל ב-11 אחוז."
        if he else
        "How many passengers the bus must carry for the in-lane stop to win, by dwell time and traffic inflow, with 1.35 "
        "people per car (the middle of the Israeli range). Each line is one inflow; each point is a mean over paired runs "
        "with the same cars. With fewer passengers than the line, the bay moves people faster; with more, the lane does. "
        "A line at zero: the lane wins at any bus load, because the bay slows the cars as well. Points are capped at 100. "
        "With 1.2 or 1.5 people per car every value shrinks or grows by 11%.")
    an._caption(fig, caption, lang, width=112)
    out = MEDIA / f"stop_design_break_even_bus.{lang}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--figures", action="store_true", help="also redraw the figure in docs/media (both languages)")
    args = ap.parse_args()
    runs, provenance = load_runs()
    dwells = sorted(int(d) for d in runs["dwell_s"].unique())
    g = json.loads(GEOMETRY.read_text(encoding="utf-8"))
    lane_q = runs[runs.scenario == "A"].groupby(["traffic_rate", "dwell_s"])["queue_max_cars"].mean()
    data = {
        "about": "Paired differences, bay minus lane, of both stop-design experiments. Written by "
                 "scripts/summarize_stop_experiments.py from outputs/experiments/stop_design_v1 and stop_design_v2.",
        "provenance": provenance, "runs": int(len(runs)), "rates": list(RATES), "dwells": dwells,
        "pairs": pairing_table(runs, dwells), "cells": cell_details(runs, dwells),
        "lane_queue_cars": {f"{r:g}": {str(d): round(float(lane_q[(r, d)]), 1) for d in dwells} for r in RATES},
        "geometry": {"entry_s": g["arrival_time_from_braking_s"]["bay_minus_lane_mean"], "seeds": g["seeds"],
                     "dev_lane_m": g["distance_from_stop_pole_m"]["lane_mean"], "dev_bay_m": g["distance_from_stop_pole_m"]["bay_mean"],
                     "gap_lane_m": g["gap_between_bus_side_and_pavement_edge_m"]["lane_mean"],
                     "gap_bay_m": g["gap_between_bus_side_and_pavement_edge_m"]["bay_mean"]},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=None, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"written {OUT.relative_to(REPO)} ({OUT.stat().st_size // 1024} KB): {data['runs']:,} runs, dwell levels {dwells}")
    if args.figures:
        for lang in ("en", "he"):
            print("written", figure(data, lang).relative_to(REPO))


if __name__ == "__main__":
    main()
