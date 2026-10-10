"""The app, the smoke test and the validation demo must judge episodes identically."""
import random

import numpy as np
import pandas as pd
import pytest

from busmerge.config import SimConfig
from busmerge.evaluation import MAX_SIM_TIME_S, TIMELINE_PHASES, classify_outcome, merge_timeline, run_episode
from busmerge.simulation import SimulationEngine
from tests.brains import GOLDEN_BRAIN


def _bus_frames(rows):
    cols = ["time", "type", "state", "lateral_offset", "merge_progress", "v", "width", "physical_collision"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows])


def test_bus_starting_in_lane_does_not_count_as_merged_early():
    """Regression: the bus starts in the lane (progress 1.0); that must not end the merge at t<0."""
    df = _bus_frames([
        (0.0, "Bus", "MOVING", 0.0, 1.0, 10.0, 2.5, False),
        (10.0, "Bus", "IN_BAY", -3.5, 0.0, 0.0, 2.5, False),
        (20.0, "Bus", "WAITING_TO_MERGE", -3.5, 0.0, 0.0, 2.5, False),
        (24.0, "Bus", "MOVING", -0.05, 0.98, 5.0, 2.5, False),
    ])
    outcome, meta = classify_outcome(df)
    assert outcome == "merged"
    assert meta["merge_s"] == pytest.approx(4.0)


def test_collision_overrides_merge():
    df = _bus_frames([
        (20.0, "Bus", "WAITING_TO_MERGE", -3.5, 0.0, 0.0, 2.5, True),
        (24.0, "Bus", "MOVING", -0.05, 0.98, 5.0, 2.5, False),
    ])
    assert classify_outcome(df)[0] == "collision"


@pytest.fixture(scope="module")
def scripted_merge_df():
    """A merge that does not depend on any brain: steer for the lane centre at constant throttle."""
    random.seed(0)
    np.random.seed(0)
    sim = SimulationEngine(scenario="B", config=SimConfig(total_cars_to_spawn=20), governor_disabled=True,
                           load_brain=False)
    sim.external_action = (1.0, 0.6)
    sim.init_scenario()
    while not sim.all_vehicles_finished() and sim.time < MAX_SIM_TIME_S:
        sim.step()
    return sim.get_results()


def test_timeline_phases_add_up_to_total(scripted_merge_df):
    tl = merge_timeline(scripted_merge_df)
    assert tl is not None
    assert sum(tl[key] for key, _ in TIMELINE_PHASES) == pytest.approx(tl["total_s"], abs=1e-6)
    assert tl["total_s"] > 0


def test_validation_demo_judges_streamlit_episode_like_the_app():
    from busmerge.rl.validation_demo import run_streamlit_episode

    cfg = SimConfig(total_cars_to_spawn=20)
    row, df = run_streamlit_episode(str(GOLDEN_BRAIN), seed=0, ep=0, config=cfg)
    outcome, meta = classify_outcome(df)
    expected = {"merged": "success", "collision": "crash"}.get(outcome, outcome if outcome in ("off_road", "over_centre_line") else "timeout")
    assert row["outcome"] == expected
    if outcome == "merged":
        assert row["merge_s"] == pytest.approx(meta["merge_s"], abs=0.01)


def test_stop_frame_is_not_reported_as_accel_paradox():
    """The frame in which a car comes to rest (speed floored at 0, accel already reset) is not a
    second physics path; only frames where the bumper cap overrides the IDM may be flagged."""
    cfg = SimConfig(total_cars_to_spawn=50, traffic_rate=0.4)
    ft = run_episode("B", cfg, str(GOLDEN_BRAIN), governor_disabled=True, seed=1).get_follower_trace()
    stop_frames = ft[(ft["v"] < 0.05) & (ft["car_dv"] < 0.0)]
    assert len(stop_frames) > 0, "scenario no longer contains a braking-to-rest follower"
    assert not stop_frames["accel_paradox"].any()


def test_side_contact_with_a_car_counts_as_collision():
    """The bus touching a car alongside it is a collision even if it never ran into the car ahead."""
    rows = [
        (20.0, 999, "Bus", "WAITING_TO_MERGE", 300.0, 0.0, 11.0, 2.5, -1.5, 0.3, 0.0, -1.5, False),
        (20.0, 7, "Car", "Cruising", 298.0, 2.0, 4.5, 1.8, 0.0, 0.0, 0.0, 0.0, False),
        (24.0, 999, "Bus", "MOVING", 310.0, 5.0, 11.0, 2.5, -0.05, 0.98, 0.0, -0.05, False),
    ]
    cols = ["time", "id", "type", "state", "x", "v", "length", "width", "lateral_offset", "merge_progress",
            "heading_deg", "total_lat", "physical_collision"]
    df = pd.DataFrame([dict(zip(cols, r)) for r in rows])
    outcome, meta = classify_outcome(df)
    assert outcome == "collision"
    assert meta["first_contact_s"] == pytest.approx(20.0)
