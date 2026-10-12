"""Nightly gates (#27, #28): the default brain on many unseen seeds. Skipped unless `pytest --nightly`.

The seeds (3000-3399) are used nowhere else: not in training, selection or the published results
(2000-2999). The thresholds were fixed in docs/TEST_STRATEGY.md before these seeds were run. The
summaries are written to outputs/nightly/ (uploaded by .github/workflows/nightly.yml).
"""
import json
import os

import pytest

from busmerge.paths import DEFAULT_BRAIN, OUTPUTS_DIR
from busmerge.results import summarize
from busmerge.verification import run_seeds

pytestmark = pytest.mark.nightly
WORKERS = os.cpu_count() or 2


def _gate(name: str, rows: list[dict]) -> dict:
    s = summarize(rows)
    s["other_violation_runs"] = sum(bool(r["other_violations"]) for r in rows)
    out = OUTPUTS_DIR / "nightly"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(s, indent=1))
    return s


def test_brain_quality_gate():
    # #27: 200 unseen seeds at the app defaults.
    s = _gate("quality", run_seeds(DEFAULT_BRAIN, range(3000, 3200), workers=WORKERS))
    assert s["merged_pct"] >= 95.0, s
    assert s["strict_pct"] >= 85.0, s
    assert s["over_centre_pct"] == 0.0, s
    assert s["other_violation_runs"] == 0, s
    assert s["time_mean_s"] is not None and s["time_mean_s"] <= 15.0, s


@pytest.mark.parametrize("traffic_rate", [0.2, 0.4, 0.6, 0.8])
def test_stress_sweep(traffic_rate):
    # #28: 50 unseen seeds per inflow. Floors from the measured stress table (100 seeds: merged 97-99%,
    # strict 84-90%), lowered by about 1.5 standard errors for 50 seeds.
    s = _gate(f"stress_{traffic_rate}", run_seeds(DEFAULT_BRAIN, range(3200, 3250), traffic_rate, workers=WORKERS))
    assert s["merged_pct"] >= 94.0, s
    assert s["strict_pct"] >= 78.0, s
    assert s["stuck_pct"] == 0.0, s
    assert s["over_centre_pct"] == 0.0, s
    assert s["other_violation_runs"] == 0, s
    assert s["time_mean_s"] is not None and s["time_mean_s"] <= 15.0, s
