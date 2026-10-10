"""The Streamlit app, run headlessly as a user would: it loads without an exception, offers exactly the
brains that exist with the default first, and for a fixed seed shows the same outcome as the
evaluation harness, together with the physics-check banner.
"""
import ast

import pytest
from streamlit.testing.v1 import AppTest

from busmerge import results
from busmerge.paths import DEFAULT_BRAIN, MODELS_DIR, REPO_ROOT

APP = REPO_ROOT / "streamlit_app.py"
# Outcome of classify_outcome -> (banner kind, start of its text)
BANNERS = {
    "merged": ("success", "Bus merged in"),
    "collision": ("error", "Physical collision"),
    "off_road": ("error", "Bus left the road"),
    "over_centre_line": ("error", "Bus crossed the centre line"),
    "stuck_waiting": ("error", "Bus never completed the merge"),
    "never_waited": ("warning", "Bus never entered WAITING_TO_MERGE"),
}


def _brain_files_listed_in_the_app() -> list[str]:
    """File names in the app's _BRAIN_OPTIONS (each entry's path is str(MODELS_DIR / "<file>"))."""
    tree = ast.parse(APP.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_BRAIN_OPTIONS" for t in node.targets):
            return [c.value for c in ast.walk(node.value)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.endswith(".pth")]
    raise AssertionError("_BRAIN_OPTIONS not found in the app")


def _app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=600)


def test_app_loads_and_offers_exactly_the_brains_that_exist():
    at = _app().run()
    assert not at.exception, [e.value for e in at.exception]
    picker = next(s for s in at.sidebar.selectbox if s.label == "Checkpoint")
    existing = [f for f in _brain_files_listed_in_the_app() if (MODELS_DIR / f).is_file()]
    assert len(picker.options) == len(existing) > 0
    assert picker.index == 0
    assert DEFAULT_BRAIN.stem.removeprefix("ppo_bus_brain_") in picker.options[0]
    # The brain comparison shows the published measurements (busmerge.results), not hand-typed numbers.
    shown = [m.value for m in (*at.markdown, *at.sidebar.markdown)]
    assert any(results.brain_table() in v for v in shown)


@pytest.mark.parametrize("seed,outcome", [(2000, "merged"), (2001, "off_road")])
def test_app_run_shows_the_outcome_the_harness_measured(seed, outcome):
    # Expected outcomes: verify_brain on v13 with the app defaults (results/v13.rows.json.gz).
    at = _app().run()
    next(c for c in at.sidebar.checkbox if c.label == "Fixed random seed").check()
    next(c for c in at.sidebar.checkbox if c.label == "Merge-zone animation").uncheck()   # renders every frame
    at.run()
    next(n for n in at.sidebar.number_input if n.label == "Seed").set_value(seed)
    at.run()
    next(b for b in at.button if b.label == "Run Simulation").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    kind, text = BANNERS[outcome]
    shown = [e.value for e in getattr(at, kind)]
    assert any(v.startswith(text) for v in shown), shown
    others = [t for o, (k, t) in BANNERS.items() if o != outcome]
    every_banner = [e.value for e in (*at.success, *at.error, *at.warning)]
    assert not any(v.startswith(t) for v in every_banner for t in others), every_banner
    assert any(v.startswith("Physics checks") for v in every_banner)
