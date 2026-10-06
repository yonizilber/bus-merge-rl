# Training and how the shipped brain was produced

The training environment (`busmerge/rl/env.py`) keeps only what is specific to training (scenario
generators, reward, telemetry). Every physics step is executed by `SimulationEngine.step`, the same
code the Streamlit app runs, and the observation is built by `busmerge/rl/observation.py` in both.

## Default brain: `models/ppo_bus_brain_v11_engine.pth`
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
