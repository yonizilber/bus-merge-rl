#!/usr/bin/env python3
"""Squeeze hysteresis — no Reacting/Squeezing flutter at borderline urgency."""

import numpy as np


from busmerge.vehicle import Vehicle, Bus, BusState, CAR_PARAMS


def test_squeeze_hysteresis_no_flutter():
    """Borderline urgency must not toggle is_squeezing every frame."""
    car = Vehicle(5, 290.0, 5.0, CAR_PARAMS)
    bus = Bus(999, 305.0, 0.5, CAR_PARAMS)
    bus.state = BusState.WAITING_TO_MERGE
    bus.lateral_offset = -1.0
    bus.heading_angle = np.radians(12.0)
    bus._merge_progress = 0.7

    leader = {
        "id": 4,
        "position": 292.5,
        "velocity": 5.0,
        "length": 4.5,
        "presence": 0.55,
        "rear_x": 288.0,
    }
    toggles = 0
    prev = car.is_squeezing
    for _ in range(80):
        car._calculate_idm_accel(leader, bus=bus)
        if car.is_squeezing != prev:
            toggles += 1
            prev = car.is_squeezing
    assert toggles <= 2, f"is_squeezing flutter: {toggles} toggles in 80 frames"
    print(f"  PASS  squeeze_hysteresis  toggles={toggles}")


if __name__ == "__main__":
    print("=" * 60)
    print("SQUEEZE HYSTERESIS")
    print("=" * 60)
    test_squeeze_hysteresis_no_flutter()
    print("ALL PASSED")
