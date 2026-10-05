#!/usr/bin/env python3
"""Evaluate checkpoints under exactly the conditions of the Streamlit "Run Simulation" button.

Uses busmerge.evaluation (the same run_episode / classify_outcome the app uses), the app's
default sidebar settings, and fixed seeds so results are reproducible.

    python scripts/evaluate_brains.py --seeds 30 --out outputs/brain_eval.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from busmerge.config import PhysicsMode, SimConfig
from busmerge.evaluation import TIMELINE_PHASES, classify_outcome, count_car_collisions, merge_timeline, run_episode
from busmerge.paths import MODELS_DIR, OUTPUTS_DIR

# Streamlit sidebar defaults (streamlit_app.py): scenario B, 0.4 cars/s, 50 cars,
# 15 s dwell, 1.2 / 50 passengers, PRODUCTION physics, governor off.
APP_DEFAULTS = dict(
    total_cars_to_spawn=50, traffic_rate=0.4, bus_dwell_time=15,
    pax_per_car=1.2, pax_per_bus=50.0, physics_mode=PhysicsMode.PRODUCTION,
)


def _stats(values: list[float]) -> dict:
    if not values:
        return {"mean": None, "p95": None, "max": None}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    return {"mean": round(statistics.mean(values), 2), "p95": round(p95, 2), "max": round(ordered[-1], 2)}


def evaluate(brain: Path, seeds: int, noise_sigma: float, traffic_rate: float, cars: int, scenario: str = "B") -> dict:
    outcomes, car_coll = [], 0
    phases: dict[str, list[float]] = {name: [] for name, _ in TIMELINE_PHASES}
    phases.update(total_s=[], standstill_s=[])
    for seed in range(seeds):
        cfg = SimConfig(**{**APP_DEFAULTS, "traffic_rate": traffic_rate, "total_cars_to_spawn": cars})
        sim = run_episode(scenario, cfg, str(brain), governor_disabled=True, noise_sigma=noise_sigma, seed=seed)
        df = sim.get_results()
        outcome, _ = classify_outcome(df)
        outcomes.append(outcome)
        car_coll += count_car_collisions(df)
        timeline = merge_timeline(df) if outcome == "merged" else None
        if timeline:
            for key in phases:
                phases[key].append(timeline[key])
    return {
        "brain": brain.name, "noise_sigma": noise_sigma, "traffic_rate": traffic_rate, "cars": cars,
        "seeds": len(outcomes),
        **{k: outcomes.count(k) for k in ("merged", "collision", "stuck_waiting", "never_waited")},
        "car_collision_frames": car_coll,
        "after_boarding": {k: _stats(v) for k, v in phases.items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--noise", type=float, nargs="*", default=[0.0])
    ap.add_argument("--traffic-rate", type=float, default=0.4)
    ap.add_argument("--cars", type=int, default=50)
    ap.add_argument("--brains", nargs="*", default=None, help="file names in models/ (default: all)")
    ap.add_argument("--out", default=str(OUTPUTS_DIR / "brain_eval.json"))
    args = ap.parse_args()

    brains = sorted(MODELS_DIR / b for b in args.brains) if args.brains else sorted(MODELS_DIR.glob("*.pth"))
    results = []
    for brain in brains:
        for sigma in args.noise:
            t0 = time.time()
            r = evaluate(brain, args.seeds, sigma, args.traffic_rate, args.cars)
            r["wall_s"] = round(time.time() - t0, 1)
            results.append(r)
            print(json.dumps(r), flush=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
