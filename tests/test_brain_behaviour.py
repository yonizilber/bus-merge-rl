"""The default brain (v13) in forced situations, in the app engine.

Two tests are strict `xfail`: they document known limitations (docs/reference/BUGS.md O2, O12) with a
situation that reproduces them, and turn red the day the behaviour changes, for better or worse.
"""
import pytest

from busmerge.geometry import bus_stop_range
from busmerge.invariants import bus_contact_times, bus_edge_times
from busmerge.paths import MODELS_DIR
from tests.scenarios import lateral_while_car_alongside, merge_time, run_merge_scenario, stalled

V13 = MODELS_DIR / "ppo_bus_brain_v13.pth"
V11 = MODELS_DIR / "ppo_bus_brain_v11_engine.pth"   # learned to stop half way (case study)
IN_BAY_M = -3.0          # bus centre at or below this: still in the bay
STOP_RANGE = bus_stop_range(11.0)       # (297, 307)


@pytest.mark.parametrize("stop_x", [float(x) for x in range(int(STOP_RANGE[0]), int(STOP_RANGE[1]) + 1)])
def test_empty_road_merge_completes_without_a_half_way_stall(stop_x):
    # Every metre of the stop range (#2): merged within 15 s, no stall, on the road, no contact.
    df, t0 = run_merge_scenario(V13, stop_x)
    t = merge_time(df, t0)
    assert t is not None and t <= 15.0, f"merge took {t} s"
    assert not stalled(df, t0)
    off_road, over_centre = bus_edge_times(df)
    assert not off_road and not over_centre
    assert not bus_contact_times(df)


def test_stall_check_catches_the_v11_reward_hack():
    # The test above must be able to fail: v11 asks for a target half way out and stays there.
    df, t0 = run_merge_scenario(V11, 302.0)
    assert stalled(df, t0)
    assert merge_time(df, t0) is None


@pytest.mark.parametrize("car", [(2.0, 4.0), (-2.0, 9.0)], ids=["car_just_ahead_4ms", "car_passing_fast_9ms"])
def test_bus_waits_in_the_bay_while_a_car_is_alongside(car):
    df, t0 = run_merge_scenario(V13, 302.0, cars=[car])
    assert lateral_while_car_alongside(df, t0) <= IN_BAY_M
    assert not bus_contact_times(df)
    assert merge_time(df, t0) is not None


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUGS O2: v13 pulls out while a car is alongside (2.2% of runs); "
                          "this placement reproduces it (0.85 m² contact)")
def test_car_alongside_the_bay_is_never_touched():
    # Stop at the far end of the bay; a car 6 m behind the bus front at 6 m/s, i.e. alongside it.
    df, t0 = run_merge_scenario(V13, 307.0, cars=[(-6.0, 6.0)])
    assert not bus_contact_times(df)
    assert lateral_while_car_alongside(df, t0) <= IN_BAY_M


def test_exit_from_the_far_end_of_the_bay_on_an_empty_road_stays_on_the_road():
    df, t0 = run_merge_scenario(V13, 307.0)
    off_road, _ = bus_edge_times(df)
    assert not off_road


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUGS O12: from the far end of the bay, after letting a car pass, v13 steers out too "
                          "slowly and the exit-taper kerb corner cuts into its side (8.7% of runs); "
                          "0.10-0.14 m deep here")
@pytest.mark.parametrize("car", [(-20.0, 12.0), (-6.0, 4.0)], ids=["car_20m_behind_12ms", "car_6m_behind_4ms"])
def test_exit_from_the_far_end_after_a_car_passes_stays_off_the_kerb(car):
    df, t0 = run_merge_scenario(V13, 307.0, cars=[car])
    off_road, _ = bus_edge_times(df)
    assert not off_road
