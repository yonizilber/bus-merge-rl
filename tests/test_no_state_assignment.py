"""Speed and pose change only through the physics (#16).

A vehicle's speed, position, heading, steering angle and lateral motion may be written only where a
vehicle is created, by the physics update (`Vehicle.update_physics`, `Vehicle.apply_steering`), and
by the training env when it places the bus for a new episode. Anywhere else, an assignment is a
correction that the physics did not produce ("Hand of God", docs/BUGS.md P7). Acceleration is not on
the list: it is the driver's command, and the physics bounds it.

- The strict `xfail` documents the leftovers that still exist.
- The second test pins them exactly, so a new assignment fails CI even while the first test is
  expected to fail, and removing one reminds whoever did it to update the list.
"""
import ast

import pytest

from busmerge.paths import REPO_ROOT

STATE = {"position", "velocity", "heading_angle", "lateral_offset", "steer_angle", "lateral_velocity"}
ALLOWED = {("busmerge/vehicle.py", "__init__"), ("busmerge/vehicle.py", "update_physics"),
           ("busmerge/vehicle.py", "apply_steering"), ("busmerge/rl/env.py", "reset")}
KNOWN_LEFTOVERS = {
    # The stopped bus is held at 0 every frame while boarding.
    ("busmerge/simulation.py", "step", "velocity"),
    # Arrival in the bay or the in-lane stop sets the remaining speed (<= 0.05 m/s) to 0 (BUGS O5).
    ("busmerge/simulation.py", "_handle_bus_logic", "velocity"),
    # Scenario A (the in-lane stop baseline) resets the bus pose on arrival and at the end of boarding (BUGS O7).
    ("busmerge/simulation.py", "_handle_bus_logic", "lateral_offset"),
    ("busmerge/simulation.py", "_handle_bus_logic", "heading_angle"),
    ("busmerge/simulation.py", "_handle_bus_logic", "steer_angle"),
    ("busmerge/simulation.py", "_handle_bus_logic", "lateral_velocity"),
}


def _assignments_outside_the_physics() -> set[tuple[str, str, str]]:
    """(module, function, attribute) of every write to vehicle state in the simulation code."""
    found = set()
    for path in [*(REPO_ROOT / "busmerge").rglob("*.py"), REPO_ROOT / "streamlit_app.py"]:
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(), filename=rel)
        owner = {}
        for func in ast.walk(tree):
            if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(func):
                    owner[id(node)] = func.name          # innermost function wins (walked last)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            else:
                continue
            for target in targets:
                for t in (target.elts if isinstance(target, ast.Tuple) else [target]):
                    if isinstance(t, ast.Attribute) and t.attr in STATE:
                        func = owner.get(id(node), "<module>")
                        if (rel, func) not in ALLOWED:
                            found.add((rel, func, t.attr))
    return found


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUGS O5, O7: the stopped bus's speed is set to 0 on arrival and while boarding; "
                          "scenario A resets the bus pose")
def test_no_state_is_assigned_outside_the_physics():
    assert _assignments_outside_the_physics() == set()


def test_the_only_assignments_outside_the_physics_are_the_known_leftovers():
    assert _assignments_outside_the_physics() == KNOWN_LEFTOVERS
