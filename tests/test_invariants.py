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


@pytest.mark.slow
def test_bus_stops_in_the_bay_physically():
    """Fix A: the bus brakes within the physical limit, stops parallel to the kerb inside the bay,
    and the merge starts from the pose it stopped in (no reset)."""
    df = run_episode("B", SimConfig(total_cars_to_spawn=50), str(GOLDEN_BRAIN), governor_disabled=True, seed=1000).get_results()
    bus = df[df["type"] == "Bus"].sort_values("time").reset_index(drop=True)
    accel = bus["v"].diff() / bus["time"].diff()
    assert accel.min() >= -9.5
    in_bay = bus[bus["state"] == "IN_BAY"]
    assert len(in_bay) > 0
    assert abs(in_bay["heading_deg"].iloc[0]) <= 2.0
    first_wait = bus.index[bus["state"] == "WAITING_TO_MERGE"][0]
    assert abs(bus.loc[first_wait, "lateral_offset"] - bus.loc[first_wait - 1, "lateral_offset"]) < 0.01
    assert abs(bus.loc[first_wait, "heading_deg"] - bus.loc[first_wait - 1, "heading_deg"]) < 0.5


@pytest.mark.slow
def test_cars_enter_the_road_without_impossible_braking():
    """Fix B: no car needs braking beyond the physical limit in its first metres on the road."""
    df = run_episode("B", SimConfig(total_cars_to_spawn=50, traffic_rate=0.8), str(GOLDEN_BRAIN),
                     governor_disabled=True, seed=1000).get_results()
    cars = df[df["type"] == "Car"].sort_values(["id", "time"])
    g = cars.groupby("id")
    accel = g["v"].diff() / g["time"].diff()
    assert (accel[cars["x"] < 30.0].dropna() >= -9.5).all()


def test_traffic_metrics_count_flow_and_density():
    from busmerge.traffic_metrics import traffic_metrics

    rows = []
    for k in range(20):                       # two cars crossing x = 300 one minute apart
        t = k * 6.0
        rows.append((t, 1, "Car", 290.0 + t, 1.0, 4.5, 1.8, 0.0, 0.0))
        rows.append((t, 2, "Car", 230.0 + t, 1.0, 4.5, 1.8, 0.0, 0.0))
    m = traffic_metrics(_log(rows).assign(state="Cruising"))
    assert m["flow_veh_per_min"] == pytest.approx(1.0)


def _bus(t, x, lat, heading=0.0):
    return (t, 999, "Bus", x, 0.0, 11.0, 2.5, lat, heading)


def test_bus_parked_inside_the_bay_is_on_the_road():
    rep = check_invariants(_log([_bus(0.0, 305.0, -3.5)]))
    assert rep.counts["off_road"] == 0 and rep.counts["over_centre_line"] == 0


def test_bus_below_the_kerb_before_the_bay_is_off_road():
    # x = 260 is before the entry taper: the kerb is at -1.75, a bus centred at -1.0 reaches -2.25
    rep = check_invariants(_log([_bus(0.0, 260.0, -1.0)]))
    assert rep.counts["off_road"] == 1


def test_bus_stopped_past_the_end_of_the_bay_is_off_road():
    # Front at 320: past the flat section the kerb rises again (exit taper), the bus at bay depth hits it
    rep = check_invariants(_log([_bus(0.0, 320.0, -3.5)]))
    assert rep.counts["off_road"] == 1


def test_corner_over_the_centre_line_is_reported():
    rep = check_invariants(_log([_bus(0.0, 340.0, 0.3, heading=18.0)]))
    assert rep.counts["over_centre_line"] == 1


def test_heading_beyond_60_degrees_is_reported():
    rep = check_invariants(_log([_car(0.0, 1, 100.0, 5.0)[:8] + (65.0,)]))
    assert rep.counts["extreme_heading"] == 1


def test_bus_side_over_the_kerb_corner_is_off_road():
    # Nose down 5° across the start of the entry taper (x = 265): all four body corners are on the
    # road, but the kerb corner lies about 0.3 m inside the body side.
    from busmerge.invariants import _corners_xy, _kerb_corner_depth
    from busmerge.geometry import road_lower_edge
    log = _log([_bus(0.0, 270.5, -0.8, heading=-5.0)])
    xs, ys = _corners_xy(log)
    assert (ys >= road_lower_edge(xs)).all()
    assert _kerb_corner_depth(log)[0] == pytest.approx(0.3, abs=0.05)
    assert check_invariants(log).counts["off_road"] == 1
