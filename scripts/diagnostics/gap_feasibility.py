"""
diag_gap_feasibility.py -- 15-Second Audit
Tests how long until a safe gap (>6m) opens next to bus bay.
Scenarios A (Jam) and F (Dense Fast), 1000 rollouts each.
Bus stays perfectly stationary (gas=-1, steer=-1).
Run:  python diag_gap_feasibility.py [--n N] [--gap G] [--seed S]
"""

import os, sys, argparse
import random as _random
import numpy as np
from contextlib import contextmanager

from busmerge.rl.env import BusMergeEnv

DEFAULT_N   = 1000
DEFAULT_GAP = 6.0   # metres
DT          = 0.1   # seconds per step

# scenario_roll values that force each scenario in BusMergeEnv.reset()
# when _warmup_epoch=False, the FIRST random.random() call IS scenario_roll
SCENARIOS = {
    "A (Heavy Jam)":  0.06,   # roll < 0.12
    "F (Dense Fast)": 0.95,   # roll >= 0.82 (else branch)
}


@contextmanager
def _force_first_roll(target):
    """Intercept only the FIRST random.random() call inside reset()."""
    original = _random.random
    state    = {"n": 0}

    def patched():
        if state["n"] == 0:
            state["n"] += 1
            return target
        return original()

    _random.random = patched
    try:
        yield
    finally:
        _random.random = original


def run_audit(scenario_label, scenario_roll, n_rollouts, gap_threshold, base_seed):
    env = BusMergeEnv(eval_mode=False)
    env._warmup_epoch = False
    stay = np.array([-1.0, -1.0], dtype=np.float32)
    first_gap_times = []
    no_gap_count    = 0

    for i in range(n_rollouts):
        np.random.seed(base_seed + i)
        _random.seed(base_seed + i)

        with _force_first_roll(scenario_roll):
            env.reset()

        first_t = None
        for step in range(env.max_steps):
            gap, _, _, _, _, _ = env._scan_nearest_car()
            if gap > gap_threshold:
                first_t = step * DT
                break
            _, _, done, _ = env.step(stay)
            if done:
                break

        if first_t is None:
            no_gap_count += 1
        else:
            first_gap_times.append(first_t)

        if (i + 1) % 200 == 0:
            n_found = len(first_gap_times)
            n_done  = n_found + no_gap_count
            print("    %d/%d  gaps_found=%d  no_gap=%d  (%.1f%% solvable)" %
                  (i+1, n_rollouts, n_found, no_gap_count, n_found/n_done*100),
                  flush=True)

    return first_gap_times, no_gap_count


def print_results(label, gaps, no_gap, n_rollouts, max_ep_s, gap_thresh):
    total    = len(gaps) + no_gap
    pct_gap  = len(gaps) / total * 100

    print("")
    print("-" * 65)
    print("Scenario %s  (%d rollouts, threshold=%.1fm)" % (label, total, gap_thresh))
    print("-" * 65)
    print("  Episodes with >= 1 safe gap :  %5d/%d  (%.1f%%)" % (len(gaps), total, pct_gap))
    print("  Episodes with NO safe gap   :  %5d/%d  (%.1f%%)" % (no_gap, total, 100-pct_gap))

    if not gaps:
        print("")
        print("  IMPOSSIBLE: No safe gap in %d rollouts. Ceiling = 0%%." % total)
        return

    arr = np.array(gaps)
    p10, p25, p50, p75, p90 = np.percentile(arr, [10, 25, 50, 75, 90])

    print("")
    print("  First-gap wait time (s) -- when gap DOES open:")
    print("    Min    : %5.1fs" % arr.min())
    print("    P10    : %5.1fs" % p10)
    print("    P25    : %5.1fs" % p25)
    print("    Median : %5.1fs" % p50)
    print("    P75    : %5.1fs" % p75)
    print("    P90    : %5.1fs" % p90)
    print("    Max    : %5.1fs" % arr.max())
    print("    Mean   : %5.1fs +/- %.1fs" % (arr.mean(), arr.std()))

    print("")
    print("  %% of gap-solvable episodes where gap opens within T seconds:")
    for t in [10, 15, 20, 25]:
        pct = (arr <= t).mean() * 100
        bar = "#" * int(pct / 5)
        lim = " <-- episode limit" if abs(t - max_ep_s) < 0.01 else ""
        print("    %3ds : %5.1f%%  %s%s" % (t, pct, bar, lim))

    pct_within_limit = (arr <= max_ep_s).mean() * 100
    ceiling = (pct_gap / 100) * (pct_within_limit / 100) * 100

    print("")
    print("  THEORETICAL CEILING")
    print("    P(gap opens)                 = %5.1f%%" % pct_gap)
    print("    P(gap within %.0fs | opens)   = %5.1f%%" % (max_ep_s, pct_within_limit))
    print("    Max possible success rate    = %5.1f%%" % ceiling)

    if ceiling < 30:
        print("")
        print("  CRITICAL: Ceiling=%.0f%% -- scenario is structurally unsolvable." % ceiling)
    elif ceiling < 60:
        print("")
        print("  WARNING: Ceiling=%.0f%% -- solvable but demands sharp timing." % ceiling)
    else:
        print("")
        print("  OK: Ceiling=%.0f%% -- traffic permits high success rates." % ceiling)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n",    type=int,   default=DEFAULT_N)
    p.add_argument("--gap",  type=float, default=DEFAULT_GAP)
    p.add_argument("--seed", type=int,   default=42)
    args = p.parse_args()

    probe    = BusMergeEnv(eval_mode=False)
    max_ep_s = probe.max_steps * DT

    print("=" * 65)
    print("GAP FEASIBILITY AUDIT")
    print("  N per scenario  : %d" % args.n)
    print("  Gap threshold   : %.1f m" % args.gap)
    print("  Episode limit   : %.0fs (%d steps x %.1fs)" % (max_ep_s, probe.max_steps, DT))
    print("  Bus behaviour   : stationary (gas=-1, steer=-1)")
    print("  Base seed       : %d" % args.seed)
    print("=" * 65)

    results = {}
    for label, roll in SCENARIOS.items():
        print("")
        print("Running Scenario %s (%d rollouts)..." % (label, args.n), flush=True)
        gaps, no_gap = run_audit(label, roll, args.n, args.gap, args.seed)
        results[label] = (gaps, no_gap)

    print("")
    print("")
    print("=" * 65)
    print("RESULTS")
    print("=" * 65)

    for label, (gaps, no_gap) in results.items():
        print_results(label, gaps, no_gap, args.n, max_ep_s, args.gap)

    print("")
    print("=" * 65)
    print("GUIDE")
    print("=" * 65)
    print("  Ceiling = max success rate any perfect agent can achieve.")
    print("  < 30%%  ceiling: structurally unsolvable; reward shaping wont help")
    print("  30-60%% ceiling: solvable but requires very sharp timing")
    print("  > 60%%  ceiling: traffic is passable; failures are agent errors")
    print("")
    print("  If Scenario A ceiling < 30%%, consider removing it from eval seeds.")


if __name__ == "__main__":
    main()
