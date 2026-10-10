# Training and how the shipped brain was produced

The training environment (`busmerge/rl/env.py`) keeps only what is specific to training (scenario
generators, reward, telemetry). Every physics step is executed by `SimulationEngine.step`, the same
code the Streamlit app runs, and the observation is built by `busmerge/rl/observation.py` in both.

## Default brain: `models/ppo_bus_brain_v11_engine.pth`
Trained before strict physics was adopted; on the adopted physics it merges 97/100 with 3 side contacts
(see SPECS section 8).

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
mean time after boarding <= 6.0 s, p95 <= 7.0 s. The thresholds were fixed from the v9/v10 measurements
before any engine-trained brain existed.

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
