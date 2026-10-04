"""
Kinematic bumper limits for cars and buses.

Cars (followers): forward-only — stop, freeze at hold position, creep only when
the leader bumper has advanced (Option A). Never reverse on the road.

Buses merging: may ease backward slowly when blocked by a car ahead.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from busmerge.rl.merge_constants import (
    CAR_STOP_HOLD_GAP_M,
    HOLD_RELEASE_ADVANCE_M,
    BUMPER_APPROACH_FRAME_FRACTION,
    BUMPER_OVERSHOOT_TRIM_M,
)


def max_approach_speed(
    gap: float,
    dt: float,
    *,
    comfortable_brake: float = 2.5,
    frame_fraction: float = BUMPER_APPROACH_FRAME_FRACTION,
) -> float:
    """
    Cap forward speed before integration so the follower does not close the entire
    remaining gap in one frame (which forces velocity → 0 snaps in finalize_*).
    """
    if gap <= 0.0 or dt <= 0.0:
        return 0.0
    frame_cap = (gap * frame_fraction) / dt
    stop_cap = (2.0 * comfortable_brake * gap) ** 0.5
    return max(0.0, min(frame_cap, stop_cap))


def leader_max_follower_front(leader: Dict[str, Any], min_gap: float) -> float:
    """Maximum allowed front-bumper x for a follower behind this leader."""
    if "rear_x" in leader:
        return float(leader["rear_x"]) - float(min_gap)
    return float(leader["position"]) - float(leader["length"]) - float(min_gap)


def apply_monotonic_bumper_limit(follower, max_front: float) -> None:
    """
    Unified overshoot handler for finalize + stop-hold.

    - Micro-overshoot (discrete dt slip, ≤ BUMPER_OVERSHOOT_TRIM_M) → trim flush.
    - Macro-violation (state change, stale mono, bus waking as leader) → stop only.

    TRAINING / DEBUG modes skip position snaps so spongy SAT can judge overlaps.
    """
    mode = getattr(follower, "_physics_mode", "production")
    x = float(follower.position)
    mono = float(getattr(follower, "_monotonic_x", x))
    if x <= max_front + 1e-4:
        return
    if mode in ("debug", "training"):
        # Still stop velocity to prevent runaway, but do not snap position.
        follower.velocity = 0.0
        follower.acceleration = 0.0
        return
    overshoot = x - max_front
    # Micro-overshoot: same-frame dt slip flush. Macro / leader retreat: stop only.
    if overshoot <= BUMPER_OVERSHOOT_TRIM_M and max_front >= mono - 1e-4:
        follower.position = max_front
        follower._monotonic_x = max_front
    follower.velocity = 0.0
    follower.acceleration = 0.0


def car_stop_hold_pre(follower, leader: Optional[Dict[str, Any]]) -> bool:
    """
    Start of physics step. If car is in stop-hold, freeze until leader advances.
    Returns True → skip IDM integration this frame.
    """
    if leader is None:
        follower._hold_x = None
        follower._hold_leader_id = None
        return False

    lid = leader.get("id")
    if lid != getattr(follower, "_hold_leader_id", None):
        follower._hold_x = None
        follower._hold_leader_id = lid
        return False

    hold = getattr(follower, "_hold_x", None)
    if hold is None:
        return False

    # Stale hold from an old bumper line — car has moved forward since.
    if float(hold) < float(follower.position) - 0.05:
        follower._hold_x = None
        return False

    min_gap = float(follower.params.min_gap)
    max_front = leader_max_follower_front(leader, min_gap)

    if max_front > hold + HOLD_RELEASE_ADVANCE_M:
        follower._hold_x = None
        return False

    follower.position = hold
    follower.velocity = 0.0
    follower.acceleration = 0.0
    follower._monotonic_x = hold
    return True


def car_stop_hold_post(follower, leader: Optional[Dict[str, Any]]) -> None:
    """End of physics step — engage hold when car has stopped near bumper (gap ≥ 0)."""
    if leader is None:
        follower._hold_x = None
        follower._hold_leader_id = None
        return

    lid = leader.get("id")
    min_gap = float(follower.params.min_gap)
    max_front = leader_max_follower_front(leader, min_gap)
    gap = max_front - float(follower.position)

    if float(follower.position) > max_front + 1e-4:
        apply_monotonic_bumper_limit(follower, max_front)
        follower._hold_x = float(follower.position)
        follower._hold_leader_id = lid
        return

    if getattr(follower, "_hold_x", None) is not None:
        return

    if 0.0 <= gap <= CAR_STOP_HOLD_GAP_M and float(follower.velocity) < 0.5:
        hold = float(follower.position)
        follower._hold_x = hold
        follower._hold_leader_id = lid
        follower.velocity = 0.0
        follower.acceleration = 0.0
        follower._monotonic_x = hold


def limit_follower_to_leader(
    follower,
    leader: Optional[Dict[str, Any]],
    dt: float,
    *,
    contact_buffer_m: float = 0.20,
    sim_time: float = 0.0,
) -> None:
    """Before position += v·dt: cap forward velocity only.

    PRODUCTION (default) — enforce caps and record physics_override_* telemetry.
    DEBUG / TRAINING     — skip velocity overrides entirely so IDM is sole authority.

    Soft wake: when the follower's applied yield is still ramping (Surprise Filter),
    the bumper may not snap more than a limited Δv per frame — prevents the
    dual-path cliff (IDM mild, bumper −6 m/s in 0.1 s).
    """
    if leader is None or dt <= 0.0:
        follower.physics_override_active = False
        follower.physics_override_reason = ""
        return

    mode = getattr(follower, "_physics_mode", "production")
    if mode in ("debug", "training"):
        follower.physics_override_active = False
        follower.physics_override_reason = ""
        return

    min_gap = float(follower.params.min_gap)
    max_front = leader_max_follower_front(leader, min_gap)
    gap = max_front - float(follower.position)
    lv = max(0.0, float(leader.get("velocity", 0.0)))

    follower.velocity = max(0.0, float(follower.velocity))

    comfort = float(getattr(follower.params, "comfortable_brake", 2.5))
    approach_v = max_approach_speed(gap, dt, comfortable_brake=comfort)

    v_before = float(follower.velocity)
    v_cap = approach_v

    if float(follower.position) >= max_front - 1e-4:
        v_cap = min(v_before, lv, approach_v)
        v_cap = max(0.0, v_cap)
        follower.velocity = _soft_bumper_velocity(follower, v_before, v_cap, dt, comfort)
        follower.acceleration = min(float(follower.acceleration), 0.0)
        _record_override(follower, v_before, gap, v_cap, sim_time, "at_bumper")
        return

    v_cap = min(v_before, approach_v)
    if gap <= contact_buffer_m:
        v_cap = min(v_cap, lv)
        follower.acceleration = min(float(follower.acceleration), 0.0)
    follower.velocity = _soft_bumper_velocity(follower, v_before, v_cap, dt, comfort)
    _record_override(follower, v_before, gap, v_cap, sim_time, "approach_cap")


def _soft_bumper_velocity(follower, v_before: float, v_cap: float, dt: float, comfort: float) -> float:
    """
    Apply bumper velocity cap with a per-frame Δv limit while yield is still slewing.

    When last_applied_yield is near 1.0 the full kinematic cap is allowed.
    When yield is still ramping, Hand of God may only cut speed gradually so
    IDM and bumper stay on the same deceleration curve.
    """
    v_cap = max(0.0, float(v_cap))
    if v_before <= v_cap + 1e-6:
        return v_before
    y = float(getattr(follower, "last_applied_yield", 1.0))
    # Full authority once yield ≥ 0.85; soft otherwise.
    if y >= 0.85:
        return v_cap
    # Max snap from bumper this frame: comfort braking × (1 + 2y), ≥ ~comfort*dt*4
    # At y=0.25, dt=0.1, comfort=2.5 → max_dv ≈ 2.5*0.1*(1+0.5)=0.375... too soft
    # Need ~2 m/s/frame so a 6 m/s cliff takes ~3 frames (~0.3 s), not one.
    max_dv = max(1.5, float(comfort) * max(dt, 0.1) * (2.0 + 4.0 * y))
    return max(v_cap, v_before - max_dv)


def _record_override(follower, v_before: float, gap: float, v_cap: float, sim_time: float, reason_tag: str) -> None:
    """Set physics_override_* on follower only if velocity was actually changed."""
    v_after = float(follower.velocity)
    if abs(v_after - v_before) > 0.05:
        follower.physics_override_active = True
        follower.physics_override_reason = (
            f"{reason_tag}:gap={gap:.2f},v_before={v_before:.2f},v_cap={v_cap:.2f},"
            f"v_after={v_after:.2f}"
        )
        follower.physics_override_frame = sim_time
    else:
        follower.physics_override_active = False
        follower.physics_override_reason = ""


def finalize_follower_bumper(follower, leader: Optional[Dict[str, Any]]) -> None:
    """Trim forward overshoot only; never decrease follower.position."""
    if leader is None:
        enforce_car_forward_only(follower)
        return

    min_gap = float(follower.params.min_gap)
    max_front = leader_max_follower_front(leader, min_gap)
    apply_monotonic_bumper_limit(follower, max_front)
    enforce_car_forward_only(follower)


def enforce_car_forward_only(follower) -> None:
    """Car longitudinal position never decreases."""
    follower.velocity = max(0.0, float(follower.velocity))
    prev = getattr(follower, "_monotonic_x", None)
    x = float(follower.position)
    if prev is not None and x < prev - 1e-6:
        follower.position = prev
        follower.velocity = 0.0
        follower.acceleration = 0.0
    else:
        follower._monotonic_x = x


def bus_blocking_max_front(bus, vehicles: List) -> tuple[Optional[float], float]:
    """
    Furthest bus-front x allowed by cars fully ahead in the lane.

    A car blocks only when its entire body has cleared the bus front bumper
    (rear > bus_front + min_gap). Alongside cars — front past bus front but
    rear still beside the bus — do not block (Bus Alongside Trap fix).
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


def apply_bus_monotonic_bumper_limit(bus, max_front: float) -> None:
    """
    Bus overshoot handler — mirror of car apply_monotonic_bumper_limit (Fix B).

    Micro-overshoot (≤ BUMPER_OVERSHOOT_TRIM_M): trim flush to max_front.
    Macro violation: stop only; never teleport backward on the road.
    """
    x = float(bus.position)
    if x <= max_front + 1e-4:
        return
    overshoot = x - max_front
    if overshoot <= BUMPER_OVERSHOOT_TRIM_M:
        bus.position = max_front
    bus.velocity = 0.0
    bus.acceleration = 0.0


def enforce_bus_forward_only(bus) -> None:
    """Bus longitudinal position never decreases during merge bumper enforcement."""
    bus.velocity = max(0.0, float(bus.velocity))
    prev = getattr(bus, "_monotonic_x", None)
    x = float(bus.position)
    if prev is not None and x < prev - 1e-6:
        bus.position = prev
        bus.velocity = 0.0
        bus.acceleration = 0.0
    else:
        bus._monotonic_x = x


def limit_bus_to_cars_ahead(
    bus,
    vehicles: List,
    dt: float,
    *,
    allow_retreat: bool = True,
) -> None:
    """Cap bus velocity before integration so the bus front cannot pass cars ahead."""
    if dt <= 0.0:
        return
    max_front, ref_speed = bus_blocking_max_front(bus, vehicles)
    if max_front is None:
        return

    gap = max_front - float(bus.position)
    if gap < 0.0:
        apply_bus_monotonic_bumper_limit(bus, max_front)
        if allow_retreat:
            retreat = max(gap, -2.0 * dt)
            new_x = float(bus.position) + retreat
            mono = float(getattr(bus, "_monotonic_x", bus.position))
            if new_x >= mono - 1e-6:
                bus.position = new_x
        enforce_bus_forward_only(bus)
        return
    if gap <= 0.15:
        apply_bus_monotonic_bumper_limit(bus, max_front)
        # Cap bus velocity DOWN to ref_speed — never snap it UP from 0 to traffic speed.
        # A stopped bay bus must never inherit a passing car's speed here.
        bus.velocity = min(float(bus.velocity), max(0.0, ref_speed))
        enforce_bus_forward_only(bus)
        return

    comfort = float(getattr(bus.params, "comfortable_brake", 2.5))
    approach_v = max_approach_speed(gap, dt, comfortable_brake=comfort)
    if float(bus.velocity) > approach_v:
        # Cap to max(ref_speed, approach_v) — never snap UP to ref_speed.
        bus.velocity = min(float(bus.velocity), max(ref_speed, approach_v))
        bus.acceleration = min(float(bus.acceleration), 0.0)


def finalize_bus_bumper(bus, vehicles: List) -> None:
    """Trim micro-overshoot only; never macro-teleport bus backward (Fix B)."""
    max_front, ref_speed = bus_blocking_max_front(bus, vehicles)
    if max_front is None:
        enforce_bus_forward_only(bus)
        return
    apply_bus_monotonic_bumper_limit(bus, max_front)
    # Wake-up: only inherit car speed when the bus is MOVING in the traffic lane
    # and genuinely stopped at a close bumper (gap < 1 m).
    # NEVER snap velocity for a bay-waiting bus (WAITING_TO_MERGE / IN_BAY) —
    # that caused the 0 m/s → traffic-speed teleport in a single frame.
    _bus_state_name = getattr(getattr(bus, "state", None), "name", "")
    _gap = max_front - float(bus.position)
    if (float(bus.velocity) == 0.0
            and _bus_state_name == "MOVING"
            and _gap < 1.0):
        bus.velocity = max(0.0, ref_speed)
    enforce_bus_forward_only(bus)
