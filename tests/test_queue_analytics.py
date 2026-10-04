#!/usr/bin/env python3
"""Queue / overtake analytics tests."""
import sys
import numpy as np
import pandas as pd


from busmerge.rl.queue_analytics import (
    merge_end_time,
    detect_longitudinal_overtakes,
    detect_chart_artifact_crossings,
    filter_exempt_overtakes,
    parse_leader_id,
)


def test_parse_leader_id():
    assert parse_leader_id("ID 1 (front-rear gap: 18.9m)") == 1
    assert parse_leader_id("Clear Road") is None
    assert parse_leader_id("ID 999 (front-rear gap: 51.9m)") == 999
    print("  PASS  parse_leader_id")


def test_merge_end_after_wait():
    rows = []
    for t, st in [(0.0, "MOVING"), (10.0, "IN_BAY"), (20.0, "WAITING_TO_MERGE"),
                  (25.0, "WAITING_TO_MERGE"), (26.0, "MOVING")]:
        rows.append({"time": t, "id": 999, "type": "Bus", "state": st, "x": 300.0})
    df = pd.DataFrame(rows)
    assert merge_end_time(df) == 26.0
    print("  PASS  merge_end_after_wait")


def test_synthetic_overtake():
    times = np.arange(0, 10.0, 0.1)
    slow = pd.DataFrame({"time": times, "id": 1, "type": "Car", "x": 100 + 3 * times, "v": 3.0, "state": "Cruising"})
    fast = pd.DataFrame({"time": times, "id": 2, "type": "Car", "x": 80 + 8 * times, "v": 8.0, "state": "Cruising"})
    df = pd.concat([slow, fast], ignore_index=True)
    ot = detect_longitudinal_overtakes(df, post_merge_only=False, min_sep_m=1.0)
    assert not ot.empty
    assert int(ot.iloc[0]["passer_id"]) == 2
    assert int(ot.iloc[0]["passed_id"]) == 1
    print("  PASS  synthetic_overtake")


def test_chart_artifact_not_physics():
    times = np.arange(0, 10.0, 0.1)
    a = pd.DataFrame({"time": times, "id": 1, "type": "Car", "x": 10 * times, "v": 10.0, "state": "Cruising"})
    b = pd.DataFrame({"time": times, "id": 2, "type": "Car", "x": 10 * times + 20, "v": 10.0, "state": "Cruising"})
    full = pd.concat([a, b], ignore_index=True)
    # Sparse chart: fake crossing chord
    chart = full.iloc[::5].copy()
    art = detect_chart_artifact_crossings(full, chart)
    # Parallel lines — no real overtake; chart may or may not artifact
    ot = detect_longitudinal_overtakes(full, post_merge_only=False)
    assert ot.empty
    print("  PASS  parallel_no_overtake")


def test_filter_exempt_bay_pass():
    times = np.arange(0, 5.0, 0.1)
    bus = pd.DataFrame({
        "time": times, "id": 999, "type": "Bus", "x": 300.0, "v": 0.0, "state": "IN_BAY",
    })
    car = pd.DataFrame({
        "time": times, "id": 1, "type": "Car",
        "x": 280 + 8 * times, "v": 8.0, "state": "Cruising",
    })
    df = pd.concat([bus, car], ignore_index=True)
    ot = detect_longitudinal_overtakes(df, post_merge_only=False)
    assert not ot.empty
    assert filter_exempt_overtakes(df, ot).empty
    print("  PASS  filter_exempt_bay_pass")


if __name__ == "__main__":
    print("=" * 60)
    print("QUEUE ANALYTICS")
    print("=" * 60)
    failed = []
    for fn in (
        test_parse_leader_id,
        test_merge_end_after_wait,
        test_synthetic_overtake,
        test_chart_artifact_not_physics,
        test_filter_exempt_bay_pass,
    ):
        try:
            fn()
        except AssertionError as e:
            failed.append((fn.__name__, str(e)))
            print(f"  FAIL  {fn.__name__}: {e}")
    print("=" * 60)
    if failed:
        print(f"FAILED {len(failed)} test(s)")
        sys.exit(1)
    print("ALL QUEUE ANALYTICS TESTS PASSED")
    sys.exit(0)
