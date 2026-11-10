"""The bay geometry and the merge threshold are defined once.

The bay used to be drawn in three places with different tapers, and the merge threshold existed both
in `merge_success.py` and as a literal in the engine (docs/reference/BUGS.md P15). This test parses every
module and fails on a new copy:
- a number equal to a bay x coordinate (the taper and flat-section ends);
- a number compared with something named "lateral" that equals the merge threshold or its old value.
Only the modules that define these values may contain them.
"""
import ast

from busmerge.geometry import bay_outline
from busmerge.paths import REPO_ROOT
from busmerge.rl.merge_success import PRODUCTION_MERGE_LATERAL_THRESHOLD

DEFINING_MODULES = {"busmerge/geometry.py", "busmerge/rl/merge_constants.py", "busmerge/rl/merge_success.py"}
BAY_X = {float(x) for x in bay_outline()[:, 0]}                        # 265, 285, 315, 330
THRESHOLDS = {PRODUCTION_MERGE_LATERAL_THRESHOLD, -0.1}                # current and pre-2026-10-10 value


def _sources():
    files = [*(REPO_ROOT / "busmerge").rglob("*.py"), *(REPO_ROOT / "scripts").rglob("*.py"),
             REPO_ROOT / "streamlit_app.py"]
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel not in DEFINING_MODULES:
            yield rel, ast.parse(path.read_text(), filename=rel)


def _number(node):
    """The value of a numeric literal, including a negated one (``-0.1`` is a UnaryOp in the AST)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _number(node.operand)
        return None if inner is None else -inner
    return None


def _mentions_lateral(node) -> bool:
    return any("lateral" in (getattr(n, "id", "") or getattr(n, "attr", "") or "").lower()
               for n in ast.walk(node) if isinstance(n, (ast.Name, ast.Attribute)))


def test_bay_coordinates_are_defined_once():
    found = [f"{rel}:{node.lineno} {_number(node)}" for rel, tree in _sources() for node in ast.walk(tree)
             if isinstance(node, ast.Constant) and _number(node) in BAY_X]
    assert not found, "bay coordinate copied; use busmerge.geometry / merge_constants:\n" + "\n".join(found)


def test_merge_threshold_is_defined_once():
    found = []
    for rel, tree in _sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and _mentions_lateral(node):
                for operand in (node.left, *node.comparators):
                    if _number(operand) is not None and any(abs(_number(operand) - t) < 1e-9 for t in THRESHOLDS):
                        found.append(f"{rel}:{node.lineno}")
    assert not found, "merge threshold copied; use merge_success.PRODUCTION_MERGE_LATERAL_THRESHOLD:\n" + "\n".join(found)


def test_the_scan_sees_a_copy():
    # The checks above must be able to fail.
    tree = ast.parse("if bus.lateral_offset >= -0.25:\n    pass\nflat_end = 315.0\n")
    assert any(isinstance(n, ast.Compare) and _mentions_lateral(n) and _number(n.comparators[0]) == -0.25
               for n in ast.walk(tree))
    assert any(isinstance(n, ast.Constant) and _number(n) in BAY_X for n in ast.walk(tree))
