#!/usr/bin/env python3
"""Evaluate checkpoints under exactly the conditions of the Streamlit "Run Simulation" button.

Uses busmerge.evaluation (the same run_episode / classify_outcome the app uses), the app's
default sidebar settings, and fixed seeds so results are reproducible.

    python scripts/evaluate_brains.py --seeds 30 --out outputs/brain_eval.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from busmerge.config import PhysicsMode
from busmerge.evaluation import evaluate_brain
from busmerge.paths import MODELS_DIR, OUTPUTS_DIR

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--noise", type=float, nargs="*", default=[0.0])
    ap.add_argument("--physics-mode", choices=[m.value for m in PhysicsMode], default="production")
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
            r = evaluate_brain(brain, args.seeds, sigma, args.traffic_rate, args.cars, args.physics_mode)
            r["wall_s"] = round(time.time() - t0, 1)
            results.append(r)
            print(json.dumps(r), flush=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
