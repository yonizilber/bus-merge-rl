"""Property-based tests of the safe-speed law (#11), with random gaps, speeds and leader speeds.

The law every follower obeys (busmerge/safe_speed.py) promises the following:
- it never commands braking beyond the physical limit;
- it never commands more than the driver wants;
- when the limit is not reached, the follower does not close more than the gap within one step;
- a follower that starts at or below the safe speed behind a leader that brakes as the law assumes
  (comfortably, to a stop) never runs into it. It can, however, get up to about 0.55 m into its own
  2 m minimum gap (strict `xfail`, BUGS O19).
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from busmerge.rl.merge_constants import MAX_BRAKE_MS2
from busmerge.safe_speed import _bounded_acceleration, safe_speed

DT = 0.1
MIN_GAP_M = 2.0      # every car class keeps 2 m (busmerge.vehicle)
speeds = st.floats(0.0, 20.0)
gaps = st.floats(-5.0, 150.0)
brakes = st.floats(1.5, 3.0)
driver = st.floats(-12.0, 4.0)


@given(v=speeds, a_driver=driver, gap=gaps, v_leader=speeds, b=brakes)
def test_never_brakes_beyond_the_limit_nor_above_the_driver(v, a_driver, gap, v_leader, b):
    a = _bounded_acceleration(v, a_driver, gap, v_leader, b, DT)
    assert a >= -MAX_BRAKE_MS2
    assert a <= a_driver or a == -MAX_BRAKE_MS2


@given(gap=gaps, v_leader=speeds, b=brakes)
def test_safe_speed_is_never_negative_and_grows_with_room(gap, v_leader, b):
    s = safe_speed(gap, v_leader, b, DT)
    assert s >= 0.0
    assert safe_speed(gap + 1.0, v_leader, b, DT) >= s
    assert safe_speed(gap, v_leader + 1.0, b, DT) >= s


@given(v=speeds, a_driver=driver, gap=st.floats(0.0, 150.0), v_leader=speeds, b=brakes)
def test_one_step_never_closes_more_than_the_gap_when_brakes_suffice(v, a_driver, gap, v_leader, b):
    a = _bounded_acceleration(v, a_driver, gap, v_leader, b, DT)
    if a > -MAX_BRAKE_MS2:                       # the physical limit did not bind
        v_next = max(v + a * DT, 0.0)
        assert (v_next - v_leader) * DT <= gap + 1e-9


def _worst_intrusion(v_leader: float, gap: float, fraction: float, b: float, a_driver: float) -> float:
    """A follower starting at ``fraction`` of the safe speed, ``gap`` metres of spare room behind a leader
    that brakes to a stop at ``b`` (as the law assumes). Returns the deepest the follower ever got into
    its minimum gap (0 = never). Vehicles update in sequence, leader first, as in the engine."""
    v = fraction * safe_speed(gap, v_leader, b, DT)
    x_follower, x_leader, worst = 0.0, gap, 0.0           # x_leader = leader rear minus the minimum gap
    for _ in range(600):
        v_leader = max(v_leader - b * DT, 0.0)
        x_leader += v_leader * DT
        a = _bounded_acceleration(v, a_driver, x_leader - x_follower, v_leader, b, DT)
        v = max(v + a * DT, 0.0)
        x_follower += v * DT
        worst = max(worst, x_follower - x_leader)
    return worst


@settings(max_examples=300, deadline=None)
@given(v_leader=st.floats(0.0, 15.0), gap=st.floats(0.0, 80.0), fraction=st.floats(0.0, 1.0),
       b=brakes, a_driver=st.floats(0.0, 2.0))
def test_a_follower_starting_safe_never_touches_a_leader_braking_comfortably(v_leader, gap, fraction, b, a_driver):
    assert _worst_intrusion(v_leader, gap, fraction, b, a_driver) < MIN_GAP_M


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUGS O19: the one-step bound assumes the leader still moves during the follower's "
                          "step, but the leader has already moved; the follower can get up to about 0.55 m into "
                          "its 2 m minimum gap (never into contact)")
def test_a_follower_starting_safe_keeps_its_whole_minimum_gap():
    # The smallest case hypothesis found: equal speeds (1 m/s), no spare room, leader braking at 2 m/s².
    assert _worst_intrusion(1.0, 0.0, 1.0, 2.0, 0.0) <= 1e-9
