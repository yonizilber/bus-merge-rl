"""Shared merge-completion criteria for training, smoke test, and Streamlit."""

from busmerge.rl.merge_constants import BAY_DEPTH

# The merge is complete (WAITING_TO_MERGE → MOVING in simulation.py, "merged" in the evaluation and
# success in training) once the bus centre is this close to the lane centre. At -0.25 m the 2.5 m wide
# bus is wholly inside the 3.5 m lane, 0.25 m clear of the kerb; the lane-keeping controller then
# centres it. It was -0.10 m until 2026-10-10, a margin that only an overshooting controller reached
# quickly (docs/CASE_STUDY_REWARD_HACKING.md); the change was the project owner's decision.
PRODUCTION_MERGE_LATERAL_THRESHOLD = -0.25


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

    The full sim declares merge done when lateral_offset >= PRODUCTION_MERGE_LATERAL_THRESHOLD
    (→ MOVING), which is about 93% progress, not 1.0.  Streamlit also accepts MOVING after
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
