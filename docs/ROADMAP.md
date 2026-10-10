# Roadmap

What comes next, in order. Each step follows the working rules in [JOURNAL.md](JOURNAL.md):
one harness for every number, no silent corrections, measurements on seeds not used for
development, and golden fingerprints changed only on purpose and with an explanation.

## 1. Strict physics: done (2026-10-10)

Adopted with v11 as the default brain after the v12 fine-tune did not beat it. The "Hand of God"
corrections and `PhysicsMode` are deleted, arrivals use the same safe-speed law, and the golden files
are regenerated.
- **Physics violations:** 0 in acceptance, other than contact.
- **No brain passes acceptance:** every one makes 2-4 side contacts per 100 runs (BUGS O2), which is the
  open research item below.

## 1b. Teach the brain to wait for a car alongside (research)

**Hypotheses to test one at a time**, each with a fine-tune and acceptance:
- shaping terms that pay for early lateral progress or steering on a "safe" gap
- an observation of the nearest car only (no second car, no car alongside)
- training scenarios in which a moving car beside the bay is rare: add a dedicated scenario
- the in-training evaluation does not move at all (26-28/30), so measure the reward components first

## 2. Finish physical correctness

- Count, then remove, the clamps on the merging bus (BUGS O3).
- Add a bay-geometry check (O4).
- Remove the remaining arrival assignment (O5) and the scenario A pose resets (O7).
- Add the checks to the training environment's telemetry, so training runs report physics violations too.

## 3. Courtesy (decision needed)

The brain is measured on its own merge time. It is not yet measured on the braking it forces on the car
behind. Decide whether acceptance should also require, for example, follower braking ≤ 6 m/s² without
a large increase in merge time. Decide this only after step 1, because strict physics changes how cars
brake.

## 4. Training correctness (BUGS R1-R6)

- Fix the closing-risk sign (R1) and the PPO log-probability of clamped actions (R2).
- Verify the checkpoint overwrite (R3).
- Select checkpoints by acceptance instead of the in-training metric (R5).
- Each change alters what the brain learns, so each needs a fine-tune and acceptance.

## 5. Code cleanup

- Split `streamlit_app.py` (about 1,500 lines, mostly at module level) into sections with functions.
- Split `SimulationEngine.step`, `_handle_bus_logic` and `BusMergeEnv.reset`.
- Replace magic numbers with named constants.
- Use `logging` instead of `print`.
- Remove `getattr(self, "x", default)` calls on attributes that always exist, and changelog-style
  comments.
- Rewrite or delete the nine legacy `xfail` tests.
- Tighten the `ruff` rules step by step.

## 6. Documentation and publication

- README: what the project is, a GIF, the architecture, how to run and train, measured results with
  their source, known limitations.
- Choose which of the original project notes to publish.
- Create the public repository, push, and confirm CI is green.
- Point Streamlit Community Cloud at it.
- Make the old repository private (the user's decision).

## Ideas carried over from the original project (not scheduled)

- Dwell time that depends on how precisely the bus parked.
- Several bus sizes, with the bus length as a feature.
- Two traffic lanes.
- Preference-based reward tuning from human comparisons of merges.
- A formal safety score per episode.
