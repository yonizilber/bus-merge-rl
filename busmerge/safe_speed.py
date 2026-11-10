"""Longitudinal safety by physics: one safe-speed law, no corrections.

Every follower (cars, the bus back in the lane, the merging bus toward cars fully ahead of it) has
its driver's acceleration limited by

    v_safe   = sqrt(v_leader² + 2·b_comf·gap)      # can still stop behind the leader if it brakes too
    v_frame  = v_leader + gap / dt                  # do not close more than the gap within one step
    a_bound  = (min(v_safe, v_frame) − v) / dt
    a        = max(min(a_driver, a_bound), −MAX_BRAKE_MS2)

where ``gap`` is measured to the leader's rear bumper minus the follower's ``min_gap``. Speed and
position then follow from the acceleration as for any vehicle. If even the hardest physical braking
(9 m/s²) is not enough, the vehicles touch and busmerge.invariants records it: a failure is shown, not
hidden. This is the safe-speed idea of the Gipps and Krauss car-following models (the latter is the
default in SUMO), applied on top of the IDM driver.

It replaced, on 2026-10-10, a set of corrections that kept cars apart by assignment (speed caps that
removed up to 2.4 m/s in one frame, position trims, frozen "stop-holds"); see docs/reference/BUGS.md and the git
tag ``legacy-hand-of-god``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from busmerge.rl.merge_constants import MAX_BRAKE_MS2


def safe_speed(gap: float, v_leader: float, b_comf: float, dt: float) -> float:
    """Highest speed from which the follower can keep ``gap`` ≥ 0 within this step and still stop
    behind a leader that brakes as well (both at ``b_comf``)."""
    v_leader = max(v_leader, 0.0)
    room = max(gap, 0.0)
    return min((v_leader * v_leader + 2.0 * b_comf * room) ** 0.5, v_leader + room / dt)


def _bounded_acceleration(v: float, a_driver: float, gap: float, v_leader: float,
                          b_comf: float, dt: float) -> float:
    a_bound = (safe_speed(gap, v_leader, b_comf, dt) - max(v, 0.0)) / dt
    return max(min(a_driver, a_bound), -MAX_BRAKE_MS2)


def leader_max_follower_front(leader: Dict[str, Any], min_gap: float) -> float:
    """Furthest front-bumper x a follower may reach behind this leader (keeps ``min_gap``)."""
    if "rear_x" in leader:
        return float(leader["rear_x"]) - float(min_gap)
    return float(leader["position"]) - float(leader["length"]) - float(min_gap)


def bus_blocking_max_front(bus, vehicles: List) -> tuple[Optional[float], float]:
    """Furthest bus-front x allowed by the nearest car fully ahead of the bus, and that car's speed.

    Only a car whose whole body is ahead of the bus front blocks it. A car alongside the bus does not:
    that conflict is lateral, and avoiding it is the merge policy's job (contact is a collision).
    """
    min_gap = float(bus.params.min_gap)
    bus_front = float(bus.position)
    max_front = None
    ref_speed = 0.0
    for v in vehicles:
        if v is bus or type(v).__name__ == "Bus":
            continue
        car_rear = float(v.position) - float(v.params.length)
        if car_rear <= bus_front + min_gap:
            continue
        candidate = car_rear - min_gap
        if max_front is None or candidate < max_front:
            max_front = candidate
            ref_speed = float(v.velocity)
    return max_front, ref_speed


def follower_acceleration(follower, leader: Optional[Dict[str, Any]], a_driver: float, dt: float) -> float:
    """Driver acceleration limited by the safe-speed law toward ``leader``."""
    if leader is None or dt <= 0.0:
        return max(a_driver, -MAX_BRAKE_MS2)
    gap = leader_max_follower_front(leader, float(follower.params.min_gap)) - float(follower.position)
    b_comf = float(getattr(follower.params, "comfortable_brake", 2.0))
    return _bounded_acceleration(float(follower.velocity), a_driver, gap,
                                 float(leader.get("velocity", 0.0)), b_comf, dt)


def merging_bus_acceleration(bus, vehicles: List, a_driver: float, dt: float) -> float:
    """Merging bus: the same law toward the nearest car fully ahead of it in the lane."""
    max_front, ref_speed = bus_blocking_max_front(bus, vehicles)
    if max_front is None or dt <= 0.0:
        return max(a_driver, -MAX_BRAKE_MS2)
    b_comf = float(getattr(bus.params, "comfortable_brake", 2.0))
    return _bounded_acceleration(float(bus.velocity), a_driver, max_front - float(bus.position),
                                 ref_speed, b_comf, dt)
