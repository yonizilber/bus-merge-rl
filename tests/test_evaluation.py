"""The app, the smoke test and the validation demo must judge episodes identically."""
import pandas as pd
import pytest

from busmerge.config import SimConfig
from busmerge.evaluation import TIMELINE_PHASES, classify_outcome, merge_timeline, run_episode
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
def episode_df():
    cfg = SimConfig(total_cars_to_spawn=20)
    return run_episode("B", cfg, str(GOLDEN_BRAIN), governor_disabled=True, seed=0).get_results()


def test_timeline_phases_add_up_to_total(episode_df):
    tl = merge_timeline(episode_df)
    assert tl is not None
    assert sum(tl[key] for key, _ in TIMELINE_PHASES) == pytest.approx(tl["total_s"], abs=1e-6)
    assert tl["total_s"] > 0


def test_validation_demo_judges_streamlit_episode_like_the_app():
    from busmerge.rl.validation_demo import run_streamlit_episode

    cfg = SimConfig(total_cars_to_spawn=20)
    row, df = run_streamlit_episode(str(GOLDEN_BRAIN), seed=0, ep=0, config=cfg)
    outcome, meta = classify_outcome(df)
    assert outcome == "merged"
    assert row["outcome"] == "success"
    assert row["merge_s"] == pytest.approx(meta["merge_s"], abs=0.01)


def test_stop_frame_is_not_reported_as_accel_paradox():
    """The frame in which a car comes to rest (speed floored at 0, accel already reset) is not a
    second physics path; only frames where the bumper cap overrides the IDM may be flagged."""
    cfg = SimConfig(total_cars_to_spawn=50, traffic_rate=0.4)
    ft = run_episode("B", cfg, str(GOLDEN_BRAIN), governor_disabled=True, seed=1).get_follower_trace()
    stop_frames = ft[(ft["v"] < 0.05) & (ft["car_dv"] < 0.0)]
    assert len(stop_frames) > 0, "scenario no longer contains a braking-to-rest follower"
    assert not stop_frames["accel_paradox"].any()
