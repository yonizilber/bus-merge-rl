"""
Ghost Tail Matrix Test
======================
Stress-tests the Bus.presence_factor polygon math across the full
parameter space of bus heading angles and lateral offsets.

A car at x=50 m/s travelling at 15 m/s follows a bus at x=100.
For every (angle, offset) combination one physics step is run and
presence_factor is evaluated.  Only combinations where
presence_factor > 0.05 are printed — these are the cases where the
IDM car will "see" the bus tail and begin to brake.

Run with:
    python test_ghost_tail.py
"""

import sys
import numpy as np
from busmerge.vehicle import Bus, Vehicle, BusState, CAR_PARAMS, VehicleParams

# ── Parameters ──────────────────────────────────────────────────────────────
BUS_ANGLES_DEG  = np.arange(-25.0, 25.1, 2.5)   # -25 … +25 step 2.5
BUS_OFFSETS     = np.arange(-3.5,  0.1,  0.5)   # -3.5 … 0.0 step 0.5
CAR_SPEED       = 15.0   # m/s
CAR_X           = 50.0   # m  (behind the bus)
BUS_X           = 100.0  # m
DT              = 0.1    # s

PRESENCE_THRESHOLD = 0.05   # only print rows above this

# Column widths for aligned output
W_ANG = 9   # bus angle deg
W_OFF = 8   # bus offset m
W_PF  = 9   # presence_factor
W_MXY = 9   # max_corner_y
W_CAR = 10  # car accel after 1 step


def run():
    print()
    print("=" * 70)
    print("  GHOST TAIL MATRIX TEST  —  presence_factor > 0.05 only")
    print(f"  Bus at x={BUS_X} m  |  Car at x={CAR_X} m, v={CAR_SPEED} m/s")
    print(f"  Bus angles: {BUS_ANGLES_DEG[0]:.1f}° … {BUS_ANGLES_DEG[-1]:.1f}°  "
          f"step 2.5°   ({len(BUS_ANGLES_DEG)} values)")
    print(f"  Bus offsets: {BUS_OFFSETS[0]:.1f} … {BUS_OFFSETS[-1]:.1f} m  "
          f"step 0.5 m   ({len(BUS_OFFSETS)} values)")
    print(f"  Total cells: {len(BUS_ANGLES_DEG) * len(BUS_OFFSETS)}")
    print("=" * 70)
    header = (
        f"{'BusAngle':>{W_ANG}} {'BusOffset':>{W_OFF}} {'Presence':>{W_PF}} "
        f"{'MaxCornerY':>{W_MXY}} {'CarAccel':>{W_CAR}}"
    )
    print(header)
    print("-" * 70)

    hit_count  = 0
    zero_count = 0

    for angle_deg in BUS_ANGLES_DEG:
        for offset in BUS_OFFSETS:
            # -- Spawn bus ------------------------------------------------
            bus = Bus(v_id=999, position=BUS_X, velocity=0.0, params=CAR_PARAMS)
            bus.state          = BusState.IN_BAY
            bus.lateral_offset = float(offset)
            bus.heading_angle  = float(np.radians(angle_deg))
            bus.steer_angle    = 0.0
            bus.velocity       = 0.0
            bus.lat_target     = float(offset)

            # -- Compute presence_factor ----------------------------------
            pf = bus.presence_factor

            # Also report the maximum y-corner for transparency
            theta  = bus.heading_angle
            c, s   = np.cos(theta), np.sin(theta)
            half_l = bus.params.length / 2.0
            half_w = bus.params.width  / 2.0
            lo     = bus.lateral_offset
            corners_y = np.array([
                lo + half_l * s + half_w * c,
                lo + half_l * s - half_w * c,
                lo - half_l * s + half_w * c,
                lo - half_l * s - half_w * c,
            ])
            max_corner_y = float(np.max(corners_y))

            # -- Spawn car and run one physics step -----------------------
            car = Vehicle(v_id=1, position=CAR_X, velocity=CAR_SPEED,
                          params=CAR_PARAMS)
            car.lateral_offset = 0.0

            # The car's IDM leader is a mock derived from bus presence
            mock_leader = {
                'id':       999,
                'position': BUS_X,
                'velocity': bus.velocity,
                'length':   bus.params.length,
                'presence': pf,
            }
            accel_before = car.acceleration
            car.update_physics(DT, leader=mock_leader, bus=bus)
            car_accel = car.acceleration

            if pf > PRESENCE_THRESHOLD:
                hit_count += 1
                print(
                    f"{angle_deg:>{W_ANG}.1f}° "
                    f"{offset:>{W_OFF}.2f} m "
                    f"{pf:>{W_PF}.4f} "
                    f"{max_corner_y:>{W_MXY}.4f} m "
                    f"{car_accel:>{W_CAR}.4f} m/s²"
                )
            else:
                zero_count += 1

    print("-" * 70)
    print(f"  Rows printed (presence > {PRESENCE_THRESHOLD}): {hit_count}")
    print(f"  Silent rows (presence ≤ {PRESENCE_THRESHOLD}): {zero_count}")
    print()

    # ── Sanity checks ─────────────────────────────────────────────────────
    fail = False

    # 1. Bus perfectly centred in lane: width=2.5m, lane=3.5m → overlap=2.5/3.5=0.714
    bus0 = Bus(v_id=0, position=BUS_X, velocity=0.0, params=CAR_PARAMS)
    bus0.state = BusState.MOVING     # not IN_BAY
    bus0.lateral_offset = 0.0
    bus0.heading_angle  = 0.0
    pf_centre = bus0.presence_factor
    expected_centre = round(bus0.params.width / 3.5, 4)   # 2.5/3.5 ≈ 0.714
    if abs(pf_centre - expected_centre) > 0.01:
        print(f"[FAIL] Bus centred in lane should give ≈{expected_centre} (got {pf_centre:.4f})")
        fail = True
    else:
        print(f"[PASS] Bus centred in lane  → presence = {pf_centre:.4f} (≈ {expected_centre})")

    # 2. Bus fully in bay, heading=0 must NOT block lane
    bus1 = Bus(v_id=1, position=BUS_X, velocity=0.0, params=CAR_PARAMS)
    bus1.state = BusState.IN_BAY
    bus1.lateral_offset = -3.5
    bus1.heading_angle  = 0.0
    pf_bay = bus1.presence_factor
    if pf_bay > 0.05:
        print(f"[FAIL] Bus parked straight in bay should NOT block lane (got {pf_bay:.4f})")
        fail = True
    else:
        print(f"[PASS] Bus straight in bay  → presence = {pf_bay:.4f} (≤ 0.05)")

    # 3. Bus in bay at -15° (tail swing) must show nonzero presence
    bus2 = Bus(v_id=2, position=BUS_X, velocity=0.0, params=CAR_PARAMS)
    bus2.state = BusState.IN_BAY
    bus2.lateral_offset = -3.5
    bus2.heading_angle  = np.radians(-15.0)
    pf_tail = bus2.presence_factor
    if pf_tail <= 0.0:
        print(f"[FAIL] Bus in bay at -15° should show tail presence (got {pf_tail:.4f})")
        fail = True
    else:
        print(f"[PASS] Bus in bay at -15°   → presence = {pf_tail:.4f} (tail detected)")

    print()
    if fail:
        print("SOME SANITY CHECKS FAILED — see above")
        sys.exit(1)
    else:
        print("ALL SANITY CHECKS PASSED")


if __name__ == "__main__":
    run()
