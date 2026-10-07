"""The physical checker must catch what it claims to, and the app engine must keep the properties it already has."""
import pandas as pd
import pytest

from busmerge.config import SimConfig
from busmerge.evaluation import run_episode
from busmerge.invariants import check_invariants
from tests.brains import GOLDEN_BRAIN


def _log(rows):
    cols = ["time", "id", "type", "x", "v", "length", "width", "total_lat", "heading_deg"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows])


def _car(t, i, x, v, lat=0.0):
    return (t, i, "Car", x, v, 4.5, 1.8, lat, 0.0)


def test_clean_log_has_no_violations():
    rep = check_invariants(_log([_car(0.0, 1, 10.0, 10.0), _car(0.1, 1, 11.0, 10.0), _car(0.2, 1, 12.0, 10.0)]))
    assert rep.total == 0


def test_detects_impossible_braking():
    rep = check_invariants(_log([_car(0.0, 1, 10.0, 10.0), _car(0.1, 1, 10.5, 5.0)]))  # -50 m/s^2
    assert rep.counts["decel_over_limit"] == 1
    assert rep.worst_decel == pytest.approx(-50.0)


def test_detects_backward_motion_and_position_jump():
    rep = check_invariants(_log([_car(0.0, 1, 10.0, 5.0), _car(0.1, 1, 9.0, 5.0), _car(0.2, 1, 12.0, 5.0)]))
    assert rep.counts["backward_motion"] == 1
    assert rep.counts["position_jump"] >= 1


def test_detects_overlap_but_not_a_lateral_gap():
    assert check_invariants(_log([_car(0.0, 1, 100.0, 5.0, lat=0.0), _car(0.0, 2, 98.0, 5.0, lat=0.5)])).counts["overlap"] == 1
    assert check_invariants(_log([_car(0.0, 1, 100.0, 5.0, lat=0.0), _car(0.0, 2, 98.0, 5.0, lat=3.5)])).counts["overlap"] == 0


@pytest.mark.slow
def test_engine_run_has_no_overlap_negative_speed_or_position_jump():
    """Properties the engine already satisfies; hard braking is tracked separately (see docs)."""
    df = run_episode("B", SimConfig(total_cars_to_spawn=50), str(GOLDEN_BRAIN), governor_disabled=True, seed=1000).get_results()
    rep = check_invariants(df)
    for kind in ("overlap", "negative_speed", "position_jump", "accel_over_limit"):
        assert rep.counts[kind] == 0, (kind, rep.examples.get(kind))
