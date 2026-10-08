#!/usr/bin/env python3
"""
Batch benchmark — Streamlit-like conditions, no UI.
σ=0, Scenario B, exp4 brain, dwell=15s.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd


from busmerge.geometry import compute_sat_overlap_area, vehicle_corners
from busmerge.invariants import OVERLAP_MIN_AREA_M2
from busmerge.paths import MODELS_DIR, OUTPUTS_DIR
from busmerge.config import SimConfig
from busmerge.simulation import SimulationEngine

CKPT = str(MODELS_DIR / "ppo_bus_brain_exp4.pth")
DWELL = 15
REPS_PER_CASE = 12
SEED_BASE = 1000

# Grid: inflow ≥ 0.65, cars ≥ 60 (user-requested corners + full sweep)
INFLOWS = [0.65, 0.75, 0.85, 0.99]
CAR_COUNTS = [60, 70, 80, 100]


@dataclass
class RunResult:
    seed: int
    merged: bool
    sat_contact: bool
    phys_collision: bool
    max_progress: float
    merge_s: float | None


def sat_merge_contact(df: pd.DataFrame, t0: float = 35.0, t1: float = 45.0) -> bool:
    """True if the bus polygon overlaps any car polygon between t0 and t1 (same test as the app)."""
    mz = df[(df["time"] >= t0) & (df["time"] <= t1)]
    for _, grp in mz.groupby("time"):
        bus_rows = grp[grp["type"] == "Bus"]
        if bus_rows.empty:
            continue
        b = bus_rows.iloc[0]
        bus_poly = vehicle_corners(b["x"], b["total_lat"], b["length"], b["width"], np.radians(b["heading_deg"]))
        for _, c in grp[grp["type"] == "Car"].iterrows():
            car_poly = vehicle_corners(c["x"], c["total_lat"], c["length"], c["width"], np.radians(c["heading_deg"]))
            if compute_sat_overlap_area(bus_poly, car_poly) > OVERLAP_MIN_AREA_M2:
                return True
    return False


def run_once(inflow: float, n_cars: int, seed: int) -> RunResult:
    np.random.seed(seed)
    random.seed(seed)
    cfg = SimConfig(
        total_cars_to_spawn=n_cars,
        traffic_rate=inflow,
        bus_dwell_time=DWELL,
    )
    sim = SimulationEngine("B", cfg, brain_path=CKPT)
    sim.noise_sigma = 0.0
    sim.init_scenario()

    for _ in range(6000):
        if sim.all_vehicles_finished():
            break
        sim.step()
        if sim.time > 300:
            break

    df = pd.DataFrame(sim.frame_history)
    bus = df[df["type"] == "Bus"].sort_values("time")
    if bus.empty:
        return RunResult(seed, False, False, False, 0.0, None)

    phys = bool(bus["physical_collision"].any()) if "physical_collision" in bus.columns else False
    sat = sat_merge_contact(df)
    max_p = float(bus["merge_progress"].max()) if "merge_progress" in bus.columns else 0.0

    merged = False
    merge_s = None
    if "merge_progress" in bus.columns and (bus["state"] == "WAITING_TO_MERGE").any():
        wait_t = float(bus.loc[bus["state"] == "WAITING_TO_MERGE", "time"].min())
        done = bus[bus["merge_progress"] >= 1.0]
        if not done.empty:
            merged = True
            merge_s = float(done["time"].min()) - wait_t

    return RunResult(seed, merged, sat, phys, max_p, merge_s)


def summarize(case_results: list[RunResult]) -> dict:
    n = len(case_results)
    return {
        "runs": n,
        "merged": sum(r.merged for r in case_results),
        "sat_contact": sum(r.sat_contact for r in case_results),
        "phys_collision": sum(r.phys_collision for r in case_results),
        "stuck": sum((not r.merged) and r.max_progress < 1.0 for r in case_results),
        "sat_seeds": [r.seed for r in case_results if r.sat_contact],
        "phys_seeds": [r.seed for r in case_results if r.phys_collision],
        "fail_seeds": [r.seed for r in case_results if not r.merged],
    }


def main():
    t0 = time.time()
    report: dict = {
        "config": {
            "brain": CKPT,
            "noise_sigma": 0.0,
            "dwell_s": DWELL,
            "reps_per_case": REPS_PER_CASE,
            "inflows": INFLOWS,
            "car_counts": CAR_COUNTS,
        },
        "cases": [],
    }

    print("=" * 72)
    print("STREAMLIT-STYLE TRAFFIC BENCHMARK  (σ=0, governor blocked-lane fix)")
    print(f"  inflows={INFLOWS}  cars={CAR_COUNTS}  reps/case={REPS_PER_CASE}")
    print("=" * 72)

    for inflow in INFLOWS:
        for n_cars in CAR_COUNTS:
            case_key = f"inflow={inflow:.2f}_cars={n_cars}"
            print(f"\n--- {case_key} ({REPS_PER_CASE} seeds) ---", flush=True)
            case_results: list[RunResult] = []
            for rep in range(REPS_PER_CASE):
                seed = SEED_BASE + rep + int(inflow * 100) * 1000 + n_cars * 10
                case_results.append(run_once(inflow, n_cars, seed))
                if (rep + 1) % 4 == 0:
                    s = summarize(case_results)
                    print(
                        f"  ... {rep+1}/{REPS_PER_CASE}  "
                        f"merged={s['merged']}/{rep+1}  SAT={s['sat_contact']}/{rep+1}",
                        flush=True,
                    )

            s = summarize(case_results)
            n = len(case_results)
            row = {
                "case": case_key,
                "inflow": inflow,
                "cars": n_cars,
                **{k: v for k, v in s.items() if k not in ("sat_seeds", "phys_seeds", "fail_seeds")},
                "sat_seeds": s["sat_seeds"],
                "phys_seeds": s["phys_seeds"],
                "fail_seeds": s["fail_seeds"],
            }
            report["cases"].append(row)
            print(
                f"  RESULT  merged {s['merged']}/{n}  "
                f"SAT {s['sat_contact']}/{n}  phys {s['phys_collision']}/{n}  "
                f"stuck {s['stuck']}/{n}",
                flush=True,
            )
            if s["sat_seeds"]:
                print(f"    SAT seeds: {s['sat_seeds']}", flush=True)

    elapsed = time.time() - t0
    report["elapsed_s"] = round(elapsed, 1)

    # totals
    total_runs = sum(c["runs"] for c in report["cases"])
    total_sat = sum(c["sat_contact"] for c in report["cases"])
    total_merged = sum(c["merged"] for c in report["cases"])
    total_phys = sum(c["phys_collision"] for c in report["cases"])

    report["totals"] = {
        "runs": total_runs,
        "merged": total_merged,
        "sat_contact": total_sat,
        "phys_collision": total_phys,
        "sat_rate": round(total_sat / max(1, total_runs), 3),
        "merge_rate": round(total_merged / max(1, total_runs), 3),
    }

    OUTPUTS_DIR.mkdir(exist_ok=True)
    out_path = OUTPUTS_DIR / "bench_streamlit_traffic_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"TOTAL  {total_runs} runs in {elapsed/60:.1f} min")
    print(f"  merged      {total_merged}/{total_runs} ({100*total_merged/total_runs:.1f}%)")
    print(f"  SAT contact {total_sat}/{total_runs} ({100*total_sat/total_runs:.1f}%)")
    print(f"  phys flag   {total_phys}/{total_runs}")
    print(f"Report: {out_path}")
    print("=" * 72)


if __name__ == "__main__":
    main()
