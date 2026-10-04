#!/usr/bin/env python3
"""Governor clear-road bypass — gap >= 50 m or no car must not veto merge."""


from busmerge.rl.governor_logic import governor_check, apply_safety_shield, is_clear_road_for_governor
from busmerge.rl.merge_constants import GOVERNOR_CLEAR_ROAD_GAP_M


class _FakeCar:
    pass


def test_clear_road_no_car():
    ok, s, g, r = governor_check(0.8, 0.7, 0.1, 60.0, 0.0, None)
    assert ok and s == 0.8 and g == 0.7 and r == ""
    print("  PASS  no_car_passes")


def test_wide_gap_no_veto():
    car = _FakeCar()
    ok, s, g, r = governor_check(1.0, 0.9, 0.15, 55.0, -8.0, car)
    assert ok, f"wide gap vetoed: {r}"
    assert s == 1.0 and g == 0.9
    print(f"  PASS  gap={55}m passes (threshold={GOVERNOR_CLEAR_ROAD_GAP_M}m)")


def test_close_gap_can_veto():
    car = _FakeCar()
    ok, s, g, r = governor_check(1.0, 0.9, 0.08, 5.0, -12.0, car)
    assert not ok or g == 0.0, "close fast car should hold or veto gas"
    print(f"  PASS  close_gap intervenes reason={r!r} gas={g:.2f}")


def test_shield_skipped_on_clear_road():
    car = _FakeCar()
    s, g, cond = apply_safety_shield(0.9, 0.8, 0.2, 50.0, -5.0, 10.0, car, 1.85)
    assert s == 0.9 and g == 0.8 and cond == ""
    print("  PASS  shield_skipped_clear_road")


def test_is_clear_helper():
    assert is_clear_road_for_governor(None, 999.0)
    assert is_clear_road_for_governor(_FakeCar(), GOVERNOR_CLEAR_ROAD_GAP_M)
    assert not is_clear_road_for_governor(_FakeCar(), 20.0)
    print("  PASS  is_clear_road_for_governor")


def test_blocked_lane_zeros_merge_steer():
    """Alongside car (gap<0) at low progress — must not steer into occupied lane."""
    car = _FakeCar()
    ok, s, g, r = governor_check(0.50, -0.10, 0.08, -9.6, -1.5, car)
    assert not ok and s == 0.0 and g == 0.0 and r == "governor_blocked_lane"
    print("  PASS  blocked_lane_no_merge_steer")


def test_hold_zeros_steer_when_gap_negative():
    car = _FakeCar()
    ok, s, g, r = governor_check(0.50, 0.5, 0.20, -3.0, -8.0, car)
    assert not ok and s == 0.0 and g == 0.5 and r == "governor_blocked_lane"
    print("  PASS  hold_zeros_steer_when_blocked")


def test_committed_overlap_bus_faster_retreats():
    car = _FakeCar()
    ok, s, g, r = governor_check(0.8, 0.7, 0.90, -2.0, 2.0, car)
    assert not ok and s == -1.0 and g == 0.0 and r == "governor_frontal_retreat"
    print("  PASS  committed_overlap_retreat")


if __name__ == "__main__":
    print("=" * 60)
    print("GOVERNOR CLEAR-ROAD BYPASS")
    print("=" * 60)
    for fn in (
        test_clear_road_no_car,
        test_wide_gap_no_veto,
        test_close_gap_can_veto,
        test_shield_skipped_on_clear_road,
        test_is_clear_helper,
        test_blocked_lane_zeros_merge_steer,
        test_hold_zeros_steer_when_gap_negative,
        test_committed_overlap_bus_faster_retreats,
    ):
        fn()
    print("=" * 60)
    print("ALL GOVERNOR TESTS PASSED")
