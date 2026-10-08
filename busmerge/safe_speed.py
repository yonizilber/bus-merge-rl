"""Strict physics (experimental, behind SimConfig.strict_physics): one safe-speed law, no corrections.

The default follower pipeline keeps cars apart with corrections that are not physics: speed caps that
remove up to 2.4 m/s in one frame, position trims that move a car backwards, and "stop-holds" that
freeze it. Strict physics replaces all of them with a single constraint on the *acceleration*:

    v_safe   = sqrt(v_leader² + 2·b_comf·gap)      # can still stop behind the leader if it brakes too
    v_frame  = v_leader + gap / dt                  # do not close more than the gap within one step
    a_bound  = (min(v_safe, v_frame) − v) / dt
    a        = max(min(a_driver, a_bound), −MAX_BRAKE_MS2)

Speed and position then follow from the acceleration as for any vehicle. If even the hardest physical
braking is not enough, the vehicles overlap and busmerge.invariants records it: a failure is shown,
not hidden. This is the safe-speed idea of the Gipps / Krauss car-following models (the latter is the
default in SUMO), applied to the existing IDM driver.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from busmerge.rl.bumper_kinematics import bus_blocking_max_front, leader_max_follower_front
from busmerge.rl.merge_constants import MAX_BRAKE_MS2


def _bounded_acceleration(v: float, a_driver: float, gap: float, v_leader: float,
                          b_comf: float, dt: float) -> float:
    v = max(v, 0.0)
    v_leader = max(v_leader, 0.0)
    room = max(gap, 0.0)
    v_safe = (v_leader * v_leader + 2.0 * b_comf * room) ** 0.5
    v_frame = v_leader + room / dt
    a_bound = (min(v_safe, v_frame) - v) / dt
    return max(min(a_driver, a_bound), -MAX_BRAKE_MS2)


def follower_acceleration(follower, leader: Optional[Dict[str, Any]], a_driver: float, dt: float) -> float:
    """Driver acceleration limited by the safe-speed law toward ``leader`` (keeps min_gap)."""
    if leader is None or dt <= 0.0:
        return max(a_driver, -MAX_BRAKE_MS2)
    max_front = leader_max_follower_front(leader, float(follower.params.min_gap))
    gap = max_front - float(follower.position)
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
