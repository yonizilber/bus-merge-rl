"""Comparing a run with its stored golden trajectory, within a tolerance.

An exact hash of the states differed between two machines on the last bit of one value (the steps, the success, the
reward and the final position were identical), so the goldens store a sample of the trajectory instead and compare it
at ``ATOL``: far below any behaviour change (a car 1 mm or 1 mm/s off), far above the last bit of a float."""
from __future__ import annotations

import math

ATOL = 1e-3


def mismatches(actual, expected, path: str = "", atol: float = ATOL) -> list[str]:
    """Every place where ``actual`` differs from ``expected``: numbers by more than ``atol``, anything else exactly."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        if set(actual) != set(expected):
            return [f"{path}: keys {sorted(actual)} != {sorted(expected)}"]
        return [m for k in expected for m in mismatches(actual[k], expected[k], f"{path}.{k}", atol)]
    if isinstance(expected, list) and isinstance(actual, list):
        if len(actual) != len(expected):
            return [f"{path}: length {len(actual)} != {len(expected)}"]
        return [m for i, (a, e) in enumerate(zip(actual, expected)) for m in mismatches(a, e, f"{path}[{i}]", atol)]
    numbers = (int, float)
    if isinstance(expected, numbers) and isinstance(actual, numbers) and not isinstance(expected, bool):
        return [] if math.isclose(actual, expected, rel_tol=0.0, abs_tol=atol) else [f"{path}: {actual} != {expected}"]
    return [] if actual == expected else [f"{path}: {actual!r} != {expected!r}"]
