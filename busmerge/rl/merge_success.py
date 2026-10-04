"""Shared merge-completion criteria for training, smoke test, and Streamlit."""

from busmerge.rl.merge_constants import BAY_DEPTH

# simulation.py transitions WAITING_TO_MERGE → MOVING at this lateral (not progress==1.0).
PRODUCTION_MERGE_LATERAL_THRESHOLD = -0.1


def merge_progress_from_lateral(lateral_offset: float, bay_depth: float = BAY_DEPTH) -> float:
    """0 = in bay, 1 = fully in lane (matches env._merge_progress)."""
    import numpy as np
    return float(np.clip((lateral_offset - bay_depth) / (-bay_depth), 0.0, 1.0))


def is_merge_complete(progress: float, threshold: float = 1.0) -> bool:
    """Training env terminal success — lateral fully in lane (progress >= 1.0)."""
    return progress >= threshold


def is_production_merge_complete(
    lateral_offset: float,
    bus_state,
    *,
    saw_waiting_to_merge: bool,
) -> bool:
    """
    Match simulation.py + Streamlit merge banner.

    The full sim declares merge done when lateral_offset >= -0.1 m (→ MOVING),
    which is only ~97% progress — not 1.0.  Streamlit also accepts MOVING after
    WAITING_TO_MERGE.  Training-only gates that require progress >= 1.0 will
    false-fail production runs.
    """
    from busmerge.vehicle import BusState

    if not saw_waiting_to_merge:
        return False
    if bus_state == BusState.MOVING:
        return True
    if float(lateral_offset) >= PRODUCTION_MERGE_LATERAL_THRESHOLD:
        return True
    return is_merge_complete(merge_progress_from_lateral(lateral_offset))
