#!/usr/bin/env python3
"""Run the stop-design experiment (bay vs in-lane stop), or its pilot.

    python scripts/run_stop_experiment.py --pilot              # 20 seeds per cell
    python scripts/run_stop_experiment.py                      # the whole experiment (resumable)
    python scripts/run_stop_experiment.py --spec experiments/stop_design_v1.json --workers 12

The data goes to outputs/experiments/<name>[_pilot]/: runs-*.parquet (one row per run), trips-*.parquet (one row
per vehicle and run) and provenance.json (commit, versions, spec). A run that is already stored is skipped, so an
interrupted experiment continues where it stopped. docs/reference/EXPERIMENT_STOP_DESIGN.md describes every column.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from busmerge.experiments.stop_design import Spec, run_cell, run_key  # noqa: E402
from busmerge.paths import OUTPUTS_DIR  # noqa: E402

FLUSH_EVERY = 200     # runs per stored part


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=REPO).stdout.strip()


def output_dir(spec: Spec, pilot: bool) -> Path:
    return OUTPUTS_DIR / "experiments" / (spec.name + ("_pilot" if pilot else ""))


def stored_keys(out: Path) -> set[str]:
    parts = sorted(out.glob("runs-*.parquet"))
    return set(pd.concat([pd.read_parquet(p, columns=["run"]) for p in parts])["run"]) if parts else set()


def write_provenance(out: Path, spec_path: Path, spec: Spec, pilot: bool, n_runs: int, wall_s: float) -> None:
    import tomllib

    import numpy
    import torch
    package_version = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]
    dirty = _git("status", "--porcelain", "--untracked-files=no")
    (out / "provenance.json").write_text(json.dumps({
        "experiment": spec.name, "pilot": pilot, "spec": str(spec_path.relative_to(REPO)),
        "spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "commit": _git("rev-parse", "--short", "HEAD") + ("+uncommitted" if dirty else ""),
        "simulation_version": package_version, "brain": Path(spec.brain).name, "brain_version": "0.13.0",
        "date": datetime.datetime.now().isoformat(timespec="seconds"), "runs_stored": n_runs,
        "wall_s_this_session": round(wall_s, 1), "python": platform.python_version(),
        "numpy": numpy.__version__, "torch": torch.__version__, "machine": platform.platform(terse=True),
    }, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", type=Path, default=REPO / "experiments" / "stop_design_v1.json")
    ap.add_argument("--pilot", action="store_true", help="only the pilot seeds")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = ap.parse_args()
    spec_path = args.spec if args.spec.is_absolute() else REPO / args.spec
    spec = Spec.load(spec_path)
    out = output_dir(spec, args.pilot)
    out.mkdir(parents=True, exist_ok=True)

    done = stored_keys(out)
    todo = [t for t in spec.tasks(pilot=args.pilot) if run_key(*t) not in done]
    print(f"{spec.name}{' (pilot)' if args.pilot else ''}: {len(done)} runs stored, {len(todo)} to run, "
          f"{args.workers} workers -> {out}", flush=True)
    start, runs, trips = time.time(), [], []
    part = len(list(out.glob("runs-*.parquet")))

    def flush():
        nonlocal part, runs, trips
        if runs:
            pd.DataFrame(runs).to_parquet(out / f"runs-{part:04d}.parquet", index=False)
            pd.DataFrame(trips).to_parquet(out / f"trips-{part:04d}.parquet", index=False)
            part += 1
            runs, trips = [], []

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, (row, rows) in enumerate(pool.map(partial(run_cell, spec=spec), todo, chunksize=4), 1):
            runs.append(row)
            trips.extend(rows)
            if i % FLUSH_EVERY == 0:
                flush()
                rate = i / (time.time() - start)
                print(f"  {i}/{len(todo)} runs, {rate:.1f} runs/s, about {(len(todo) - i) / rate / 60:.0f} min left",
                      flush=True)
    flush()
    write_provenance(out, spec_path, spec, args.pilot, len(stored_keys(out)), time.time() - start)
    print(f"done: {len(stored_keys(out))} runs stored in {out} ({time.time() - start:.0f} s)")


if __name__ == "__main__":
    main()
