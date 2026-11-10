"""Every published number comes from a measurement in results/ (docs/reference/TEST_STRATEGY.md, #26).

- Each stored summary is exactly what its per-seed rows give: no number was typed in by hand.
- The marked blocks in the README, SPECS and the case study are what the measurements render
  (`scripts/publish_results.py` regenerates them).
- The app renders the same brain table at run time (checked in tests/test_app_headless.py).
- The default brain's headline comes from a large run on unseen seeds, made with the current merge
  threshold on the brain file the app uses.

Prose outside the marked blocks is not checked; it is written as a dated record.
"""
import pytest

from busmerge import results
from busmerge.paths import DEFAULT_BRAIN
from busmerge.rl.merge_success import PRODUCTION_MERGE_LATERAL_THRESHOLD

NAMES = sorted(p.name.removesuffix(".json") for p in results.RESULTS_DIR.glob("*.json"))


def test_every_published_measurement_is_stored():
    assert {*results.BRAINS, *results.STRESS, *results.CASE_STUDY} <= set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_stored_summary_is_what_the_rows_give(name):
    assert results.load(name)["summary"] == results.summarize(results.load_rows(name))


def test_published_blocks_match_the_measurements():
    assert results.refresh(check=True) == []


def test_a_changed_measurement_is_caught(monkeypatch):
    # The check above must be able to fail.
    real = results.load

    def one_point_lower(name):
        m = real(name)
        m["summary"] = {**m["summary"], "merged_pct": m["summary"]["merged_pct"] - 1.0}
        return m

    monkeypatch.setattr(results, "load", one_point_lower)
    assert results.refresh(check=True)


def test_the_default_brain_headline_is_a_large_unseen_run_on_the_current_rules():
    m = results.load(results.DEFAULT)
    assert m["brain"] == DEFAULT_BRAIN.name
    assert m["summary"]["n"] >= 1000 and m["seeds"][0] >= 2000
    assert m["merge_threshold_m"] == PRODUCTION_MERGE_LATERAL_THRESHOLD
