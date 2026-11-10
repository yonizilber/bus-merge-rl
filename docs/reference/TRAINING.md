# Training and how the shipped brain was produced

The training environment (`busmerge/rl/env.py`) keeps only what is specific to training (scenario
generators, reward, telemetry). Every physics step is executed by `SimulationEngine.step`, the same
code the Streamlit app runs, and the observation is built by `busmerge/rl/observation.py` in both.

## Default brain: `models/ppo_bus_brain_v13.pth`
v11 fine-tuned under honest steering (section "v13" below). It merges in 97.8% of 1,000 unseen runs.

## Previous default: `models/ppo_bus_brain_v11_engine.pth`
Trained while the merge steering overshot. It merged 97/100 then, and stops half way under honest
steering.

Fine-tuned from `ppo_bus_brain_exp7satv9_best.pth` for 300 epochs on the unified environment
(11 features, governor off, seed 2):

```bash
cp models/ppo_bus_brain_exp7satv9_best.pth models/ppo_bus_brain_myrun_best.pth
python -u scripts/train.py --feature-dim 11 --epochs 300 --run-tag myrun --disable-governor --seed 2
```

The last-epoch weights (`ppo_bus_brain_myrun.pth`) were used, not the `_best` file: on this environment
the in-training "best" selection picked checkpoints that were worse in the app. Selection is therefore
done with `scripts/acceptance.py` on seeds that training never saw.

## Acceptance (`scripts/acceptance.py`)
100 episodes in the app engine at noise 0 and 0.15: all merged (>= 98 with noise), no collisions,
mean time after boarding <= 15.0 s, p95 <= 20.0 s.
- **The time limits** were set by the project owner on 2026-10-10, to fail a brain that freezes, not a
  cautious one.
- **The earlier limits** (6.0 / 7.0 s, from the v9/v10 measurements) assumed the overshooting
  steering. A scripted full-throttle merge takes 6.3 s under honest steering.

## What did not work
- Training from scratch (600 epochs, same recipe): 20-25 s per merge and some runs stuck waiting.
  v9 itself came from ~900 epochs in several stages; this repository does not reproduce that from scratch.
- The pre-unification training environment (two physics implementations) is preserved at the git tag
  `legacy-dual-physics`.

## Attempt: v12, fine-tune on strict physics (2026-10-09), not adopted
Starting point v11; strict physics; crash judge = acceptance judge (any bus-car contact above
0.01 m² is a terminal crash); 2 seeds × 300 epochs; tags `exp7satv12s1`, `exp7satv12s2`.

Acceptance with `--strict-physics`, 100 unseen seeds (1000-1099), merged / collisions / stuck:

| Brain | noise 0 | noise 0.15 | mean / p95 (noise 0) |
|---|---|---|---|
| v11 (reference, same code) | 98 / 2 / 0 | 98 / 2 / 0 | 4.90 / 5.6 s |
| v12s1 last | 96 / 4 / 0 | 97 / 3 / 0 | 4.92 / 6.0 s |
| v12s1 best | 96 / 4 / 0 | 97 / 3 / 0 | 5.01 / 6.1 s |
| v12s2 last | 79 / 1 / 20 | 83 / 1 / 16 | 4.85 / 9.3 s |
| v12s2 best | 84 / 1 / 15 | 90 / 1 / 9 | 4.43 / 4.8 s |

No physics violations in any run (strict physics). The fine-tune did not remove the contacts:
one seed traded them for more collisions, the other for runs that never merge. The in-training
evaluation stayed flat at 26-28/30 for all 300 epochs; its crashes are almost all the same situation
as in the app (pulling out at progress 0.05-0.3 while a car is alongside, negative gap), so the
training signal did not teach waiting. Likely contributors, not yet tested: shaping terms that reward
early lateral progress and steering on a "safe" gap, an observation that describes only the nearest
car, and training scenarios in which a moving car alongside the bay is rare.

## v13: fine-tune under honest steering (2026-10-10)

**Why it was needed.** Once the steering was fixed, no brain merged: v9-v11 asked for a target half way
out of the bay and had relied on the old controller's overshoot ([case study](CASE_STUDY_REWARD_HACKING.md)).

**Changes before training** (BUGS P16-P18).
- **Start poses:** drawn over the app's stop range (297-307 m) and kept only if the body is on the
  road.
- **PPO buffer:** stores the raw sample with its own log-probability. Before, it stored the clipped
  action, which biased learning against the action limit.
- **Rollback:** `--rollback-patience 0`. A run starting at 0 successes was otherwise reset to its
  starting weights every 30 epochs.
- **Reward:** one change. The safe-steer weight is 30 instead of 8 once the bus is out of the bay
  (progress ≥ 0.15, gap > 6 m). It is `--commit-steer-weight`; the default 8 is the old reward.

**Command.** The run tag must start with `exp7sat` to train with the polygon crash judge.

```bash
cp models/ppo_bus_brain_v11_engine.pth models/ppo_bus_brain_exp7satmyrun_best.pth
python -u scripts/train.py --feature-dim 11 --epochs 300 --run-tag exp7satmyrun --disable-governor \
    --seed 1 --commit-steer-weight 30 --rollback-patience 0
```

The epoch-300 weights are used (`ppo_bus_brain_exp7satmyrun.pth`, not `_best`). The in-training
evaluation never succeeded under the -0.10 m threshold, so `_best` stayed a copy of v11.

**Attempts.** All start from v11 and run 300 epochs, about 45 minutes with four runs in parallel. The
mean steer command is measured at the half-way state (lateral -2 to -1 m): v11 outputs 0.06, and about
0.94 is needed to reach the lane.

| Tag | Weight | Rollback | Outcome |
|---|---|---|---|
| v13 s1-s3 | 8 | on | Steer rose to 0.2, then was reset to v11 at each rollback. Stopped at epoch 60 |
| v14 w30/w60 × 2 | 30, 60 | on | Same: up to 0.3, reset at epoch 30-40. Stopped at epoch 42 |
| v15 w8 s1 | 8 | off | Half way: highest lateral -0.86 m |
| **v15 w30 s1** | 30 | off | Bus fully in the lane in every run. Selected (v13) |
| v15 w60 s1/s2 | 60 | off | Stops at -0.28 to -0.32 m, plus off-road at the exit kerb in 33-41% |

**Merge threshold.** At epoch 300 the w30 brain put the whole bus in the lane in every run, but
stopped at a median of -0.13 m, short of the -0.10 m "merged" threshold. The project owner moved the
threshold to -0.25 m (bus wholly inside the lane, 0.25 m clear of the kerb; `merge_success.py`).

**Selection, seeds 1000-1099, threshold -0.25 m:**

| Candidate | Merged (traffic) | Contact | Stuck | Strict | Off road | Mean / p95 time |
|---|---|---|---|---|---|---|
| w30 e225 | 98 | 2 | 0 | 87 | 11 | 12.0 / 15.0 s |
| w30 e250 | 99 | 1 | 0 | 87 | 12 | 12.9 / 16.3 s |
| w30 e275 | 99 | 1 | 0 | 89 | 10 | 13.9 / 17.1 s |
| **w30 e300** | **100** | **0** | **0** | **91** | **9** | 13.9 / 17.3 s |
| w60 s1 e300 | 0 | 1 | 99 | 0 | 41 | |
| w60 s2 e300 | 9 | 0 | 91 | 9 | 33 | 16.8 / 21.5 s |

Under -0.10 m the same w30 e300 brain merged 25/100. The other 75 stopped inside the lane short of the
threshold, with the same 9 off-road runs.
