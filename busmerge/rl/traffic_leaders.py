"""
Shared car–leader resolution for training env and Streamlit simulation.

Standard IDM assumes a leader directly ahead in the same lane. A bus merging from a
layby uses a continuous yield factor (merge_yield.compute_yield_factor) so cars
cruise at distance and brake when the bus encroaches or is close ahead.

Safety: cars must never "look through" a merging bus to follow a vehicle further
up the queue. Cars ahead of the bus must never yield to it.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from busmerge.rl.merge_constants import (
    MERGE_YIELD_HEADING_DEG,
    YIELD_GAP_IGNORE,
    BUS_LENGTH,
    YIELD_VIS_START,
    YIELD_PRESENCE_START,
)

from busmerge.rl.merge_yield import (
    compute_yield_factor,
    car_is_ahead_of_merging_bus,
)

from busmerge.vehicle import Bus, BusState


def reset_bus_leader_geometry(bus) -> None:
    """Legacy hook when bus enters WAITING_TO_MERGE (static rear needs no reset)."""
    if bus is not None:
        bus._stable_leader_rear_x = None
        bus._stable_leader_pos = None


def bus_rear_bumper_x(bus) -> float:
    """
    Rear bumper x for car following / max_front — yaw-independent.

    Uses fixed BUS_LENGTH along the road centre-line so trailing cars never see
    max_front jump backward when the bus yaws during merge.
    """
    return float(bus.position) - float(BUS_LENGTH)


def vehicle_leader_state(veh) -> Dict[str, Any]:
    """Leader dict for IDM (position = front bumper, stable rear for buses)."""
    if isinstance(veh, Bus):
        rear_x = bus_rear_bumper_x(veh)
        length = float(veh.position) - rear_x
    else:
        length = float(veh.params.length)
        rear_x = float(veh.position) - length
    presence = getattr(veh, "presence_factor", 1.0) if isinstance(veh, Bus) else 1.0
    return {
        "id": veh.id,
        "position": veh.position,
        "velocity": veh.velocity,
        "length": length,
        "rear_x": rear_x,
        "presence": presence,
    }


def bus_encroachment_level(bus: Bus) -> float:
    """
    Scalar in [0, 1] for telemetry / squeeze hints (not used for leader on/off).
    Combines geometric presence, merge progress, and heading (yaw toward lane).
    """
    if bus is None:
        return 0.0
    progress = float(getattr(bus, "_merge_progress", 0.0))
    presence = float(bus.presence_factor)
    heading_rad = abs(float(getattr(bus, "heading_angle", 0.0)))
    heading_sig = min(heading_rad / math.radians(MERGE_YIELD_HEADING_DEG), 1.0)
    return max(presence, progress * 0.75, heading_sig * 0.20)


def gap_car_front_to_leader_rear(car, leader_veh) -> float:
    """Bumper-to-bumper gap: leader rear to car front."""
    length = leader_veh.params.length
    if isinstance(leader_veh, Bus):
        length = leader_veh.projected_length_along_x()
    return leader_veh.position - length - car.position


def should_ignore_bus_as_leader(bus: Bus, gap_to_car_front: float, car=None) -> bool:
    """
    When True, the car uses the vehicle ahead of the bus (or clear road), not the bus.

    The bus is NOT a formal IDM queue leader while it is still in the bay:
      - IN_BAY (always)
      - DECELERATING with negligible geometric lane occupancy
      - WAITING_TO_MERGE before material lane entry (low progress + low geo presence)

    Cars may still get a soft Y_eff blend (blinker / merge yield) without
    structurally locking onto a stationary bay bus via bumper stop-hold.
    """
    if bus.state == BusState.IN_BAY:
        return True

    geo = float(getattr(bus, "geometric_presence_factor", bus.presence_factor))
    progress = float(getattr(bus, "_merge_progress", 0.0))

    # Deep in bay during approach — clear road for through traffic.
    if bus.state == BusState.DECELERATING and geo <= YIELD_PRESENCE_START:
        return True

    if bus.state != BusState.WAITING_TO_MERGE:
        return False

    # Early WAITING: bus still parked in bay (synthetic presence floor must NOT
    # make it a bumper leader — that caused the all-dwell phantom queue).
    if progress <= YIELD_VIS_START and geo <= YIELD_PRESENCE_START:
        return True

    if car is not None and car_is_ahead_of_merging_bus(bus, car):
        return True
    if gap_to_car_front <= 0.0:
        # Alongside the bus body — cannot follow it as a forward leader.
        return True
    if gap_to_car_front > YIELD_GAP_IGNORE:
        return True
    # Use geometric presence for the yield test (not the synthetic floor).
    ahead = car is not None and car_is_ahead_of_merging_bus(bus, car)
    return compute_yield_factor(progress, gap_to_car_front, geo, car_ahead=ahead) <= 0.0


def resolve_car_leader(
    vehicles: List,
    car_index: int,
    bus: Optional[Bus],
) -> Tuple[Optional[Dict[str, Any]], Optional[Bus]]:
    """
    vehicles: sorted by position descending (front of queue first).
    car_index: index of the car in that list.
    Returns (leader_dict for IDM, bus reference for lateral squeeze / yield blend).
    """
    car = vehicles[car_index]
    if car_index == 0:
        return None, bus

    potential = vehicles[car_index - 1]
    gap = gap_car_front_to_leader_rear(car, potential)

    leader = None
    if isinstance(potential, Bus) and bus is not None:
        if not should_ignore_bus_as_leader(bus, gap, car=car):
            leader = vehicle_leader_state(bus)
        elif car_index > 1:
            alt = vehicles[car_index - 2]
            if alt.position > bus.position:
                leader = None
            else:
                leader = vehicle_leader_state(alt)
    else:
        leader = vehicle_leader_state(potential)

    return leader, bus


def resolve_bus_leader(
    vehicles: List,
    bus_index: int,
) -> Optional[Dict[str, Any]]:
    """
    IDM leader for bus on the main road (MOVING).

    Same sorted-queue rule as cars: vehicle immediately ahead in the chain.
    No merge-yield look-through — that is car-specific during WAITING_TO_MERGE.
    """
    if bus_index <= 0:
        return None
    ahead = vehicles[bus_index - 1]
    return vehicle_leader_state(ahead)
