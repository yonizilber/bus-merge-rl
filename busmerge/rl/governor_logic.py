"""
Shared governor + safety shield — single source for training env and simulation.py.

Clear-road bypass: when no trailing threat within GOVERNOR_CLEAR_ROAD_GAP_M, the
governor and shield must not veto merge intent (fixes empty / wide-gap hesitation).
"""

from __future__ import annotations

import numpy as np

from busmerge.rl.merge_constants import (
    GOVERNOR_T_HORIZON,
    GOVERNOR_T_HORIZON_COMMITTED,
    GOVERNOR_MAX_SAFE_DECEL,
    GOVERNOR_STEER_THRESHOLD,
    GOVERNOR_CLEAR_ROAD_GAP_M,
    GOVERNOR_BLOCKED_LANE_PROGRESS,
)


def is_clear_road_for_governor(nearest_car, gap: float) -> bool:
    """True when no car in scan window or gap is comfortably safe."""
    if nearest_car is None:
        return True
    return float(gap) >= GOVERNOR_CLEAR_ROAD_GAP_M


def governor_check(
    steer_intent: float,
    gas_intent: float,
    merge_progress: float,
    gap: float,
    rel_speed: float,
    nearest_car,
    *,
    disabled: bool = False,
) -> tuple[bool, float, float, str]:
    """
    Active Governor v4 with clear-road bypass.

    Returns (pass_through, steer_intent, gas_intent, reason).
    pass_through=False means the governor vetoed / modified the action.
    """
    if disabled:
        return True, steer_intent, gas_intent, "disabled"

    steer_intent = float(np.clip(steer_intent, -1.0, 1.0))
    gas_intent = float(np.clip(gas_intent, -1.0, 1.0))
    progress = float(merge_progress)
    gap = float(gap)

    def _hold(steer: float) -> tuple[bool, float, float, str]:
        """Zero gas; zero merge steer when lane is occupied (gap < 0)."""
        out_steer = 0.0 if gap < 0.0 else steer
        return False, out_steer, 0.0, "governor_hold"

    # G3 — overlap / alongside (gap < 0: car front ahead of bus rear bumper)
    if nearest_car is not None and gap < 0.0:
        if progress < GOVERNOR_BLOCKED_LANE_PROGRESS:
            if steer_intent > 0.0:
                # Block lateral merge into occupied lane — but allow longitudinal gas
                # so the bus can build speed/presence and cars can start yielding.
                return False, 0.0, max(gas_intent, 0.0), "governor_blocked_lane"
            bus_closing = max(0.0, float(rel_speed))
            if bus_closing > 0.0 and progress > 0.05:
                return False, -1.0, 0.0, "governor_frontal_retreat"
            # No steer intent and no closing — allow gas so bus can move forward
            # to escape the overlap zone rather than being frozen indefinitely.
            return False, 0.0, max(gas_intent, 0.0), "governor_frontal_stop"
        bus_closing = max(0.0, float(rel_speed))
        if bus_closing > 0.0:
            if progress > 0.05:
                return False, -1.0, 0.0, "governor_frontal_retreat"
            return False, 0.0, max(gas_intent, 0.0), "governor_frontal_stop"

    # Clear road — skip all trailing-car projection (no phantom 60 m threat)
    if is_clear_road_for_governor(nearest_car, gap):
        return True, steer_intent, gas_intent, ""

    closing_speed = max(0.0, -float(rel_speed))

    # G2 — committed merge escape (progress > 0.5, gap within threat range)
    if progress > 0.5:
        future_gap = gap - closing_speed * GOVERNOR_T_HORIZON_COMMITTED
        if future_gap <= 0.0 or (
            closing_speed > 0.5
            and (closing_speed ** 2) / (2.0 * max(future_gap, 0.1)) > GOVERNOR_MAX_SAFE_DECEL
        ):
            return False, 1.0, 1.0, "governor_escape"
        return True, steer_intent, gas_intent, ""

    # G1 — early merge: only when actively steering into lane
    if steer_intent < GOVERNOR_STEER_THRESHOLD:
        return True, steer_intent, gas_intent, ""

    if gap > 0.0 and closing_speed > 0.5:
        req_decel_now = (closing_speed ** 2) / (2.0 * max(gap, 0.1))
        if req_decel_now > GOVERNOR_MAX_SAFE_DECEL:
            if progress > 0.05:
                return _hold(steer_intent)
            return False, 0.0, gas_intent, "governor_current"

    future_gap = gap - closing_speed * GOVERNOR_T_HORIZON
    if future_gap <= 0.0:
        if progress > 0.05:
            return _hold(steer_intent)
        return False, 0.0, 0.0, "governor_projected_collision"

    if closing_speed > 0.5:
        req_decel_future = (closing_speed ** 2) / (2.0 * max(future_gap, 0.1))
        if req_decel_future > GOVERNOR_MAX_SAFE_DECEL:
            if progress > 0.05:
                return _hold(steer_intent)
            return False, 0.0, gas_intent, "governor_projected"

    return True, steer_intent, gas_intent, ""


def apply_safety_shield(
    steer_intent: float,
    gas_intent: float,
    merge_progress: float,
    gap: float,
    rel_speed: float,
    nearest_speed: float,
    nearest_car,
    nearest_width: float = 1.85,
    governor_reason: str = "",
    *,
    dt: float = 0.1,
) -> tuple[float, float, str]:
    """
    Reactive shield (training + production).  Returns (steer, gas, condition_tag).
    Skipped entirely on clear road.
    """
    steer_intent = float(steer_intent)
    gas_intent = float(gas_intent)
    progress = float(merge_progress)

    if governor_reason == "governor_escape":
        return 1.0, 1.0, "governor_escape_override"

    if is_clear_road_for_governor(nearest_car, gap):
        return steer_intent, gas_intent, ""

    adaptive_min_gap = 4.0 + max(0.0, float(nearest_width) - 1.80) * 2.2
    condition = ""

    _governor_held = (governor_reason == "governor_hold")

    if steer_intent > 0 and gap > -5.0:
        next_gap = gap + rel_speed * dt
        if gap >= 0.0 and next_gap <= 0.0 and rel_speed < 0.0:
            return 0.0, 0.0, "emergency_stop"
        if 0.0 <= gap < 0.50:
            if progress >= 0.30 and not _governor_held:
                return 1.0, max(gas_intent, 0.5), "emergency_forward"
            if nearest_speed >= 2.0:
                return 0.0, 0.0, "emergency_stop"
            return 0.1, 0.1, "emergency_stop"
        if progress > 0.65 and 0.0 <= gap < 1.20 and rel_speed > 0.2 and not _governor_held:
            return 1.0, max(gas_intent, 0.7), "late_overlap"
        if progress > 0.75 and 0.0 <= gap < 2.5 and rel_speed > 1.5 and not _governor_held:
            return 1.0, max(gas_intent, 0.7), "late_overlap"
        if 0.0 <= gap < adaptive_min_gap and rel_speed > 1.2:
            gap_opening_safely = (
                (gap > 1.4 and progress > 0.40 and rel_speed < 3.5)
                or (gap > 2.5 and progress < 0.30 and rel_speed < 2.5)
            )
            if not gap_opening_safely:
                risk = float(np.clip(
                    (adaptive_min_gap - gap) / max(adaptive_min_gap, 1e-3), 0.0, 1.0))
                steer_intent *= (1.0 - 0.85 * risk)
                condition = "adaptive_gap"
        elif steer_intent > 0.65 and 0.0 <= gap < (adaptive_min_gap + 6.0) and rel_speed > 2.5:
            steer_intent *= 0.35
            condition = "high_pressure"

    if gap < 0.0 and progress > 0.60 and rel_speed <= 0.0 and not _governor_held:
        steer_intent = max(steer_intent, 0.5)
        gas_intent = max(gas_intent, 0.5)
        condition = condition or "late_push_through"

    return steer_intent, gas_intent, condition
