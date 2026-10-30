#!/usr/bin/env python3
"""Analyse the stop-design experiment: is a bus stop in a bay (B) or in the lane (A) better for people?

    python scripts/analyze_stop_experiment.py --pilot          # the pilot's data
    python scripts/analyze_stop_experiment.py                  # the whole experiment
    python scripts/analyze_stop_experiment.py --pax-car 1.4 --pax-bus 35
    python scripts/analyze_stop_experiment.py --publish        # also write results/experiments/<name>/summary.json

Reads outputs/experiments/<name>[_pilot]/ (written by scripts/run_stop_experiment.py) and writes, next to the data,
analysis/: cells.csv (one row per traffic rate and dwell time), dwell_pairs.csv (a lane stop with a different dwell
time than the bay), report.md and figures/. Every figure carries its own caption.

The measure is the paired difference of person-time, ΔPT = PT(bay) − PT(lane), per seed: the same cars in both
designs, so the difference is not blurred by different traffic. Negative ΔPT: the bay moves people faster.
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

from busmerge.experiments.stop_design import Spec, paired_difference  # noqa: E402
from busmerge.paths import OUTPUTS_DIR  # noqa: E402

BOOTSTRAP = 2000
CAP_PAX_CAR = 3.0          # the break-even map's colour scale: realistic car occupancies
RNG = np.random.default_rng(12345)          # the bootstrap's own seed: the analysis is reproducible


def load(out: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    runs = pd.concat([pd.read_parquet(p) for p in sorted(out.glob("runs-*.parquet"))], ignore_index=True)
    trips = pd.concat([pd.read_parquet(p) for p in sorted(out.glob("trips-*.parquet"))], ignore_index=True)
    return runs, trips


def bootstrap_ci(values: np.ndarray, stat=np.mean) -> tuple[float, float]:
    """95% percentile-bootstrap interval of ``stat`` over the seeds."""
    if len(values) < 2:
        return float("nan"), float("nan")
    idx = RNG.integers(0, len(values), size=(BOOTSTRAP, len(values)))
    boots = stat(values[idx], axis=1)
    return float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def break_even_pax_car(d_bus: np.ndarray, d_cars: np.ndarray, pax_bus: float) -> float:
    """Car occupancy at which the mean ΔPT is 0, given the bus occupancy: the bay costs the bus (ΔT_bus > 0) and
    saves the cars (ΔT_cars < 0), or the other way round. NaN when both differences have the same sign."""
    mb, mc = float(np.mean(d_bus)), float(np.mean(d_cars))
    if mc == 0 or mb * mc >= 0:
        return float("nan")
    return -pax_bus * mb / mc


def cell_table(runs: pd.DataFrame, pax_car: float, pax_bus: float) -> pd.DataFrame:
    pairs = paired_difference(runs, pax_car, pax_bus)
    rows = []
    for (rate, dwell), g in pairs.groupby(["traffic_rate", "dwell_s"]):
        d = g["delta_pt"].to_numpy()
        lo, hi = bootstrap_ci(d)
        a = runs[(runs["scenario"] == "A") & (runs["traffic_rate"] == rate) & (runs["dwell_s"] == dwell)]
        b = runs[(runs["scenario"] == "B") & (runs["traffic_rate"] == rate) & (runs["dwell_s"] == dwell)]
        d_bus = (g["bus_travel_time_s_b"] - g["bus_travel_time_s_a"]).to_numpy()
        d_cars = (g["cars_travel_time_s_b"] - g["cars_travel_time_s_a"]).to_numpy()
        rows.append({
            "traffic_rate": rate, "dwell_s": dwell, "pairs": len(g), "cars_per_run": round(float(g["n_cars_a"].mean()), 1),
            "delta_pt_mean": round(float(d.mean()), 1), "delta_pt_ci_low": round(lo, 1), "delta_pt_ci_high": round(hi, 1),
            "bay_better_share": round(float((d < 0).mean()), 3),
            "delta_bus_time_s": round(float(d_bus.mean()), 2), "delta_cars_time_s": round(float(d_cars.mean()), 1),
            "break_even_pax_car": round(break_even_pax_car(d_bus, d_cars, pax_bus), 2),
            "lane_queue_max_cars": round(float(a["queue_max_cars"].mean()), 1),
            "lane_entry_wait_max_s": round(float(a["max_entry_wait_s"].mean()), 1),
            "bay_merge_time_s": round(float(b["merge_time_s"].mean()), 1),
            "bay_contact_pct": round(100 * float(b["bus_contact"].mean()), 1),
            "bay_off_road_pct": round(100 * float(b["bus_off_road"].mean()), 1),
            "censored_runs": int(a["censored"].sum() + b["censored"].sum()),
        })
    return pd.DataFrame(rows)


def dwell_pair_table(runs: pd.DataFrame, pax_car: float, pax_bus: float) -> pd.DataFrame:
    """Every combination of a dwell time in the lane and a (longer or equal) dwell time in the bay."""
    rows = []
    dwells = sorted(runs["dwell_s"].unique())
    for dl in dwells:
        for db in dwells:
            if db < dl:
                continue
            pairs = paired_difference(runs, pax_car, pax_bus, dwell_lane=dl, dwell_bay=db)
            for rate, g in pairs.groupby("traffic_rate"):
                d = g["delta_pt"].to_numpy()
                lo, hi = bootstrap_ci(d)
                rows.append({"traffic_rate": rate, "dwell_lane_s": dl, "dwell_bay_s": db, "pairs": len(g),
                             "delta_pt_mean": round(float(d.mean()), 1), "delta_pt_ci_low": round(lo, 1),
                             "delta_pt_ci_high": round(hi, 1), "bay_better_share": round(float((d < 0).mean()), 3)})
    return pd.DataFrame(rows)


def markdown_table(df: pd.DataFrame) -> str:
    """A Markdown table without extra dependencies."""
    head = "| " + " | ".join(df.columns) + " |"
    lines = [head, "|" + "---|" * len(df.columns)]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join("–" if (isinstance(v, float) and np.isnan(v)) else f"{v:g}"
                                       if isinstance(v, float) else str(v) for v in row) + " |")
    return "\n".join(lines)


def _caption(fig, text: str) -> None:
    fig.text(0.01, 0.01, text, ha="left", va="bottom", fontsize=8.5, wrap=True)


def figures(cells: pd.DataFrame, out: Path, pax_car: float, pax_bus: float, label: str) -> list[tuple[str, str]]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    out.mkdir(parents=True, exist_ok=True)
    made = []

    fig, ax = plt.subplots(figsize=(8.5, 5.6))
    fig.subplots_adjust(bottom=0.27)
    for dwell, g in cells.groupby("dwell_s"):
        g = g.sort_values("traffic_rate")
        ax.plot(g["traffic_rate"], g["delta_pt_mean"] / 60, marker="o", label=f"dwell {dwell:g} s")
        ax.fill_between(g["traffic_rate"], g["delta_pt_ci_low"] / 60, g["delta_pt_ci_high"] / 60, alpha=0.15)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlabel("requested traffic inflow (cars/s)")
    ax.set_ylabel("ΔPT = PT(bay) − PT(lane)  (person-minutes per run)")
    ax.set_title(f"Bay minus in-lane stop, person-time ({label})")
    ax.legend(fontsize=8)
    caption = (f"Mean paired difference of person-time per run (bay − lane, same cars and seed), with its 95% bootstrap "
               f"interval as a band, for each dwell time (the same in both designs). Occupancy: {pax_car:g} people per "
               f"car, {pax_bus:g} on the bus. Below zero the bay moves people faster; above zero the in-lane stop does.")
    _caption(fig, caption)
    fig.savefig(out / "delta_pt_vs_rate.png", dpi=130)
    plt.close(fig)
    made.append(("delta_pt_vs_rate.png", caption))

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.8))
    fig.subplots_adjust(bottom=0.3, wspace=0.3)
    for dwell, g in cells.groupby("dwell_s"):
        g = g.sort_values("traffic_rate")
        axes[0].plot(g["traffic_rate"], g["delta_bus_time_s"], marker="o", label=f"dwell {dwell:g} s")
        axes[1].plot(g["traffic_rate"], g["delta_cars_time_s"] / 60, marker="o", label=f"dwell {dwell:g} s")
    for ax, title, unit in ((axes[0], "The bus: T(bay) − T(lane)", "s"),
                            (axes[1], "All cars together: T(bay) − T(lane)", "vehicle-minutes")):
        ax.axhline(0, color="black", lw=0.8)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("requested traffic inflow (cars/s)")
        ax.set_ylabel(unit)
    axes[0].legend(fontsize=7)
    caption = ("The two parts of the difference, before weighting by occupancy, as means over seeds. Left: how much "
               "longer the bus's trip is with a bay (the merge). Right: the summed trip times of all cars, bay minus "
               "lane (negative: the cars gain from the bay because they do not queue behind the stopped bus).")
    _caption(fig, caption)
    fig.savefig(out / "components.png", dpi=130)
    plt.close(fig)
    made.append(("components.png", caption))

    piv = cells.pivot(index="dwell_s", columns="traffic_rate", values="break_even_pax_car")
    d_bus = cells.pivot(index="dwell_s", columns="traffic_rate", values="delta_bus_time_s").to_numpy(dtype=float)
    vals = piv.to_numpy(dtype=float)
    shown = np.clip(vals, 0.0, CAP_PAX_CAR)          # the colour scale covers realistic occupancies only
    fig, ax = plt.subplots(figsize=(8, 5.4))
    fig.subplots_adjust(bottom=0.3)
    cmap = matplotlib.colormaps["viridis"].copy()
    cmap.set_bad("#d9d9d9")
    im = ax.imshow(np.ma.masked_invalid(shown), cmap=cmap, vmin=0.0, vmax=CAP_PAX_CAR, aspect="auto", origin="lower")
    ax.set_xticks(range(len(piv.columns)), [f"{c:g}" for c in piv.columns])
    ax.set_yticks(range(len(piv.index)), [f"{i:g}" for i in piv.index])
    for (i, j), v in np.ndenumerate(vals):
        if np.isnan(v):
            text = "lane\nalways" if d_bus[i, j] > 0 else "bay\nalways"
        else:
            text = f">{CAP_PAX_CAR:g}" if v > CAP_PAX_CAR else f"{v:.2f}"
        ax.text(j, i, text, ha="center", va="center", fontsize=8.5,
                color="black" if np.isnan(v) or v > 0.6 * CAP_PAX_CAR else "white")
    ax.set_xlabel("requested traffic inflow (cars/s)")
    ax.set_ylabel("dwell time (s)")
    ax.set_title(f"Break-even car occupancy (bus carries {pax_bus:g})")
    fig.colorbar(im, ax=ax, label=f"people per car (scale capped at {CAP_PAX_CAR:g})")
    caption = ("The car occupancy at which the bay and the in-lane stop tie on mean person-time, given the bus's "
               "occupancy. With more people per car than this, the bay is better (the cars' gain outweighs the bus's "
               f"loss); with fewer, the in-lane stop is. Cars carry about 1.2 on average, so values above {CAP_PAX_CAR:g} "
               "mean the lane stop wins in practice. 'lane always' (grey): the bay costs both the bus and the cars, "
               "so the in-lane stop is better at any occupancy.")
    _caption(fig, caption)
    fig.savefig(out / "break_even_pax_car.png", dpi=130)
    plt.close(fig)
    made.append(("break_even_pax_car.png", caption))
    return made


def checks(runs: pd.DataFrame) -> list[str]:
    """Data checks reported before any result: censoring, physics violations, the bay's outcomes."""
    lines = [f"- Runs: {len(runs)} ({(runs['scenario'] == 'A').sum()} in lane, {(runs['scenario'] == 'B').sum()} bay)."]
    lines.append(f"- Censored runs (a vehicle still on the road at the time cap): {int(runs['censored'].sum())}.")
    v = runs["violations"].map(json.loads)
    kinds: dict = {}
    for d, sc in zip(v, runs["scenario"]):
        for k, n in d.items():
            kinds.setdefault((sc, k), 0)
            kinds[(sc, k)] += 1
    lines.append("- Runs with a physics violation, by kind: " +
                 (", ".join(f"{sc} {k}: {n}" for (sc, k), n in sorted(kinds.items())) or "none") + ".")
    b = runs[runs["scenario"] == "B"]
    lines.append("- Bay outcomes: " + ", ".join(f"{k} {n}" for k, n in b["outcome"].value_counts().items()) + ".")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", type=Path, default=REPO / "experiments" / "stop_design_v1.json")
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--pax-car", type=float, default=1.2)
    ap.add_argument("--pax-bus", type=float, default=50.0)
    ap.add_argument("--publish", action="store_true", help="write results/experiments/<name>/summary.json")
    args = ap.parse_args()
    spec = Spec.load(args.spec if args.spec.is_absolute() else REPO / args.spec)
    data = OUTPUTS_DIR / "experiments" / (spec.name + ("_pilot" if args.pilot else ""))
    runs, _ = load(data)
    out = data / "analysis"
    out.mkdir(exist_ok=True)

    cells = cell_table(runs, args.pax_car, args.pax_bus)
    cells.to_csv(out / "cells.csv", index=False)
    pairs = dwell_pair_table(runs, args.pax_car, args.pax_bus)
    pairs.to_csv(out / "dwell_pairs.csv", index=False)
    label = "pilot" if args.pilot else spec.name
    made = figures(cells, out / "figures", args.pax_car, args.pax_bus, label)
    provenance = json.loads((data / "provenance.json").read_text())

    show = ["traffic_rate", "dwell_s", "pairs", "cars_per_run", "delta_pt_mean", "delta_pt_ci_low", "delta_pt_ci_high",
            "bay_better_share", "delta_bus_time_s", "delta_cars_time_s", "break_even_pax_car",
            "lane_queue_max_cars", "bay_merge_time_s", "bay_contact_pct"]
    report = [f"# Stop-design experiment: {label}", "",
              f"Data: `{data.relative_to(REPO)}`, commit `{provenance['commit']}`, brain {provenance['brain_version']}, "
              f"{provenance['date']}. Occupancy: {args.pax_car:g} per car, {args.pax_bus:g} on the bus.", "",
              "**This is data, not a conclusion.**" + (" The pilot sets the number of seeds for the full run." if args.pilot else ""),
              "", "## Data checks", "", *checks(runs), "", "## Per cell (bay − lane, same dwell time)", "",
              "ΔPT in person-seconds per run; CI: 95% bootstrap over seeds; *bay better share*: the share of seeds in "
              "which the bay's person-time is lower; *break-even*: car occupancy at which the designs tie.", "",
              markdown_table(cells[show]), ""]
    for name, caption in made:
        report += [f"![{name}](figures/{name})", "", f"*{caption}*", ""]
    (out / "report.md").write_text("\n".join(report))

    if args.publish and not args.pilot:
        target = REPO / "results" / "experiments" / spec.name
        target.mkdir(parents=True, exist_ok=True)
        (target / "summary.json").write_text(json.dumps({
            "provenance": provenance, "pax_car": args.pax_car, "pax_bus": args.pax_bus,
            "cells": cells.to_dict(orient="records")}, indent=1))
    print(out / "report.md")


if __name__ == "__main__":
    main()
