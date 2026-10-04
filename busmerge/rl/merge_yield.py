"""
Continuous merge yield factor (Option A — Gemini blend).

Shared by training env (env) and production (simulation.py) via
vehicle._calculate_idm_accel and traffic_leaders.should_ignore_bus_as_leader.

Y_eff combines merge progress, geometric presence, and gap distance.
Only applies to cars BEHIND the bus — never to cars ahead in the lane.
"""

from __future__ import annotations

from typing import Any, List, Tuple

from busmerge.rl.merge_constants import (
    YIELD_VIS_START,
    YIELD_VIS_END,
    YIELD_GAP_IGNORE,
    YIELD_GAP_CLOSE_M,
    YIELD_PRESENCE_START,
    YIELD_PRESENCE_FULL,
    BUS_MERGE_SCAN_AHEAD_M,
    BUS_MERGE_SCAN_BEHIND_M,
)


def yield_progress_factor(progress: float) -> float:
    """Ramp [0, 1] from lateral merge progress."""
    p = float(progress)
    if p <= YIELD_VIS_START:
        return 0.0
    if p >= YIELD_VIS_END:
        return 1.0
    return (p - YIELD_VIS_START) / (YIELD_VIS_END - YIELD_VIS_START)


def yield_presence_factor(presence: float) -> float:
    """Ramp [0, 1] from geometric lane occupancy (bus angled in lane, pf > 0)."""
    pf = float(presence)
    if pf <= YIELD_PRESENCE_START:
        return 0.0
    if pf >= YIELD_PRESENCE_FULL:
        return 1.0
    return (pf - YIELD_PRESENCE_START) / (YIELD_PRESENCE_FULL - YIELD_PRESENCE_START)


def _smoothstep(t: float) -> float:
    t = min(1.0, max(0.0, float(t)))
    return t * t * (3.0 - 2.0 * t)


def yield_distance_factor(gap_m: float) -> float:
    """
    Continuous [0, 1] urgency from longitudinal gap (car front → bus rear).

    No piecewise 0.85 boosts — smoothstep from YIELD_GAP_IGNORE → 0.
    Positive gap = car behind bus.
    """
    g = float(gap_m)
    if g >= YIELD_GAP_IGNORE:
        return 0.0
    if g <= 0.0:
        return 1.0
    # t = 1 at bumper contact, 0 at ignore range — C1-smooth via smoothstep.
    t = (YIELD_GAP_IGNORE - g) / YIELD_GAP_IGNORE
    return _smoothstep(t)


def encroach_yield_floor(gap_m: float) -> float:
    """
    Continuous encroachment soft-floor for *active* merge (WAITING_TO_MERGE).

    Lorentzian × outer fade: strong near bumper, mild at mid-range, ~0 beyond
    ~2×YIELD_GAP_CLOSE_M.  No hard if/else jumps to 0.85 / 1.0.
    """
    g = max(0.0, float(gap_m))
    if g >= YIELD_GAP_IGNORE:
        return 0.0
    tau = float(YIELD_GAP_CLOSE_M)
    lorentz = 1.0 / (1.0 + (g / tau) ** 2)
    outer = max(0.0, 1.0 - g / (2.0 * tau))
    return lorentz * outer


def _blinker_yield(presence: float, gap_m: float) -> float:
    """
    Low continuous yield for IN_BAY virtual blinker — no encroachment floor.

    Scales with blinker presence (0.10 / 0.25) and inverse-sqrt gap urgency,
    faded smoothly to 0 at YIELD_GAP_IGNORE.  Targets:
      presence=0.10 @ 25 m → Y ≈ 0.05–0.15
      presence=0.25 @  6 m → Y ≈ 0.2–0.5
    """
    g = float(gap_m)
    if g >= YIELD_GAP_IGNORE or float(presence) <= 0.0:
        return 0.0
    g_eff = max(g, 0.5)
    fade = max(0.0, (YIELD_GAP_IGNORE - g_eff) / YIELD_GAP_IGNORE)
    # Cap urgency so near-contact does not spike Y→1 (phantom full stop).
    urgency = min(2.0, (float(YIELD_GAP_CLOSE_M) / g_eff) ** 0.5)
    # Mild gain so last-3s blinker (presence=0.25 @ ~6 m) actually bleeds speed,
    # while full-dwell presence=0.10 stays gentle at longer range.
    return min(1.0, float(presence) * 1.4 * urgency * fade)


def bus_gap_to_car_front(bus, car) -> float:
    """Bumper-to-bumper: bus rear to car front (m). Positive when car is behind bus."""
    return float(bus.position) - float(bus.projected_length_along_x()) - float(car.position)


def car_is_ahead_of_merging_bus(bus, car) -> bool:
    """
    True when the car front is at or past the bus front bumper.

    The bus is behind this car — it must not be an IDM leader or yield target.
    (Fixes spurious stops like car #3 at x=318 braking for bus at x=310.)
    """
    rear_gap = bus_gap_to_car_front(bus, car)
    bus_len = float(bus.projected_length_along_x())
    return rear_gap <= -bus_len + 0.5


def car_is_behind_merging_bus(bus, car) -> bool:
    """True when the car is behind the bus front and may need to yield."""
    return float(car.position) < float(bus.position) - 0.5


def car_is_alongside_merging_bus(bus, car) -> bool:
    """Car front past bus rear but not past bus front — parallel in 2D."""
    if car_is_ahead_of_merging_bus(bus, car):
        return False
    return bus_gap_to_car_front(bus, car) <= 0.0


def _alongside_encroachment_yield(progress: float, presence: float) -> float:
    """
    Yield when alongside (gap ≤ 0) during WAITING_TO_MERGE — braking only, no bumper leader.

    Once the bus has committed to merge (any real progress or lane presence),
    an alongside car must yield / hold — not treat the road as clear and
    re-accelerate through the merge (CSV regression t≈39–41 s).
    """
    p_fac = yield_progress_factor(progress)
    pf_fac = yield_presence_factor(presence)
    signal = max(p_fac, pf_fac)

    committed = (
        float(progress) > YIELD_VIS_START or float(presence) > YIELD_PRESENCE_START
    )
    if committed:
        # Floor keeps Surprise Filter from decaying to free-road while alongside.
        floor = 0.55 + 0.40 * max(p_fac, pf_fac)
        return min(1.0, max(signal * 0.90, floor))

    return 0.0


def compute_yield_factor(
    progress: float,
    gap_m: float,
    presence: float = 0.0,
    *,
    car_ahead: bool = False,
    is_blinker: bool = False,
    synthetic: bool = False,
) -> float:
    """
    Effective yield in [0, 1]. 0 = treat road as empty; 1 = full IDM vs bus.

    gap_m must be bus_rear − car_front (positive when car is behind bus).
    Negative gap: alongside — yield from P/presence only (not bumper leader).

    is_blinker / synthetic: IN_BAY virtual-blinker path — low continuous Y,
    no encroachment floor (avoids phantom queue behind a parked bus).
    """
    if car_ahead:
        return 0.0

    g = float(gap_m)
    if is_blinker or synthetic:
        if g <= 0.0:
            # Alongside a bay-parked bus: no brake (bus is out of the lane).
            return 0.0
        return _blinker_yield(presence, g)

    if g <= 0.0:
        return _alongside_encroachment_yield(progress, presence)

    y_dist = yield_distance_factor(g)
    signal = max(yield_progress_factor(progress), yield_presence_factor(presence))
    y = signal * y_dist

    # Active merge only: continuous soft-floor (Lorentzian) — no 0.85/1.0 steps.
    # Unscaled so WAITING_TO_MERGE presence floor (~0.15) still produces
    # meaningful close-range braking; blinker path skips this entirely.
    encroaching = float(progress) > YIELD_VIS_START or float(presence) > YIELD_PRESENCE_START
    if encroaching:
        floor = encroach_yield_floor(g)
        if floor > y:
            y = floor

    return min(1.0, y)


def scan_nearest_car_for_merge(bus, vehicles: List) -> Tuple[float, float, float, float, float, Any]:
    """
    Nearest car threat for bus brain / governor (train + Streamlit parity).

    Uses separation along road: car.position − bus.position
      positive → car ahead of bus front
      negative → car behind bus front

    Returns (rear_gap, car_speed, car_accel, car_width, rel_speed, nearest_car)
    where rear_gap = bus_rear − car_front (negative when car is ahead).
    """
    best_sep = 999.0
    nearest_car = None
    bus_len = float(bus.projected_length_along_x())

    for v in vehicles:
        if v is bus or type(v).__name__ == "Bus":
            continue
        sep = float(v.position) - float(bus.position)
        if sep < -BUS_MERGE_SCAN_BEHIND_M or sep > BUS_MERGE_SCAN_AHEAD_M:
            continue
        if abs(sep) < abs(best_sep):
            best_sep = sep
            nearest_car = v

    if nearest_car is None:
        return 999.0, 0.0, 0.0, 1.85, 0.0, None

    rear_gap = float(bus.position) - bus_len - float(nearest_car.position)
    nearest_speed = float(nearest_car.velocity)
    nearest_accel = float(nearest_car.acceleration)
    nearest_width = float(nearest_car.params.width)
    rel_speed = float(bus.velocity) - nearest_speed
    return rear_gap, nearest_speed, nearest_accel, nearest_width, rel_speed, nearest_car
