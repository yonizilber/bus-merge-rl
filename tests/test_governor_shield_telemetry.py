#!/usr/bin/env python3
"""Telemetry visibility: expose governor_reason / shield_condition in frame_history so
Streamlit can actually show WHY the bus's gas/steer got overridden on a given frame.

Before this: simulation.py computed governor_reason and shield_condition as local
variables inside _handle_bus_logic() and threw them away every frame -- there was no
way, even in principle, to see a governor/shield decision in the app. This is not one
of the 4 planned bugs; it's a follow-up requested after Bug 1's fix so future
runtime-behavior bugs in this area are visible in the UI, not just provable via a
standalone script.

Reuses the exact governor-hold scenario from test_governor_hold_shield_conflict.py.
"""
import sys


import torch

from busmerge.config import SimConfig
from busmerge.simulation import SimulationEngine
from busmerge.vehicle import Bus, BusState, Vehicle, CAR_PARAMS


def _build_hold_scenario_engine():
    eng = SimulationEngine(scenario="B", config=SimConfig(), governor_disabled=False)
    eng.brain.policy = lambda state_tensor: (torch.tensor([[0.6, 0.6]]), None, None)
    bus = Bus(999, 300.0, 2.0, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -2.275   # -> merge_progress ~0.35
    bus.heading_angle = 0.0
    car = Vehicle(4, 288.60, 5.0, CAR_PARAMS)   # rear_gap ~0.40, rel_speed ~-3.0
    eng.vehicles = [bus, car]
    return eng, bus, car


def _bus_rows(frame_history):
    return [r for r in frame_history if r['type'] == 'Bus']


def test_frame_history_has_governor_shield_columns():
    """MUST FAIL TODAY (KeyError -- columns don't exist yet), PASS AFTER FIX."""
    eng, bus, car = _build_hold_scenario_engine()
    eng.step()
    bus_rows = _bus_rows(eng.frame_history)
    assert bus_rows, "no Bus row recorded in frame_history"
    row = bus_rows[-1]
    assert row['governor_reason'] == 'governor_hold', (
        f"expected governor_reason='governor_hold', got {row['governor_reason']!r}"
    )
    assert row['shield_condition'] in ('emergency_stop', 'emergency_forward'), (
        f"unexpected shield_condition={row['shield_condition']!r}"
    )
    print(f"  PASS  frame_history_has_governor_shield_columns  "
          f"governor_reason={row['governor_reason']!r}  shield_condition={row['shield_condition']!r}")


def test_governor_shield_columns_reflect_bug1_fix():
    """With Bug 1 fixed, this exact scenario's shield_condition must be 'emergency_stop',
    not the old 'emergency_forward' lunge -- ties the telemetry directly to the fix."""
    eng, bus, car = _build_hold_scenario_engine()
    eng.step()
    row = _bus_rows(eng.frame_history)[-1]
    assert row['shield_condition'] == 'emergency_stop', (
        f"expected the post-Bug-1-fix outcome 'emergency_stop', got {row['shield_condition']!r} "
        "-- either Bug 1 regressed, or this telemetry is reading the wrong value"
    )
    print(f"  PASS  governor_shield_columns_reflect_bug1_fix  shield_condition={row['shield_condition']!r}")


def test_columns_empty_when_not_waiting_to_merge():
    """A bus in a non-WAITING_TO_MERGE state must show empty strings, not a stale
    leftover value from a previous WAITING_TO_MERGE frame."""
    eng, bus, car = _build_hold_scenario_engine()
    eng.step()
    assert _bus_rows(eng.frame_history)[-1]['governor_reason'] == 'governor_hold'

    bus.state = BusState.MOVING
    bus.velocity = 5.0
    eng.step()
    row = _bus_rows(eng.frame_history)[-1]
    assert row['governor_reason'] == '', f"stale governor_reason leaked: {row['governor_reason']!r}"
    assert row['shield_condition'] == '', f"stale shield_condition leaked: {row['shield_condition']!r}"
    print("  PASS  columns_empty_when_not_waiting_to_merge")


def test_car_rows_always_empty():
    """Non-bus vehicles must never populate these bus-specific columns."""
    eng, bus, car = _build_hold_scenario_engine()
    eng.step()
    car_rows = [r for r in eng.frame_history if r['type'] == 'Car']
    assert car_rows, "no Car row recorded"
    for row in car_rows:
        assert row['governor_reason'] == '' and row['shield_condition'] == ''
    print(f"  PASS  car_rows_always_empty  ({len(car_rows)} car row(s) checked)")


if __name__ == "__main__":
    print("=" * 60)
    print("GOVERNOR/SHIELD TELEMETRY VISIBILITY")
    print("=" * 60)
    tests = [
        test_frame_history_has_governor_shield_columns,
        test_governor_shield_columns_reflect_bug1_fix,
        test_columns_empty_when_not_waiting_to_merge,
        test_car_rows_always_empty,
    ]
    failures = []
    for fn in tests:
        try:
            fn()
        except (AssertionError, KeyError) as e:
            failures.append((fn.__name__, repr(e)))
            print(f"  FAIL  {fn.__name__}: {e!r}")
    print("=" * 60)
    if failures:
        print(f"{len(failures)}/{len(tests)} FAILED")
        sys.exit(1)
    print("ALL PASSED")
