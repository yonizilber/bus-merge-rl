# bus-merge-rl

A microscopic traffic simulation of a city bus pulling out of a bus bay and merging back into
traffic. The merge decision is made by a PPO (reinforcement learning) agent; surrounding cars
follow an Intelligent Driver Model with per-driver personalities. A Streamlit dashboard lets you
run scenarios, compare trained agents, and inspect the merge frame by frame.

> This README is a work in progress. Full documentation (architecture, results, design decisions
> and known limitations) is being written.

## Case study: an agent that merged by exploiting its steering

The default agent merged in 97.9% of unseen runs, until hidden corrections were removed from the
simulation. It turned out the agent asked to go only half way out of the bay, and relied on an
overshooting steering controller to carry it into the lane (and over the centre line in every run).
With the controller fixed, it merged in 0% of runs. The full investigation, the fixes and the
retraining are in [docs/CASE_STUDY_REWARD_HACKING.md](docs/CASE_STUDY_REWARD_HACKING.md).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
streamlit run streamlit_app.py
```

The app opens at http://localhost:8501.

## Project layout

```
busmerge/            core package
  simulation.py      simulation engine: traffic spawner, bus state machine, telemetry
  vehicle.py         vehicle and bus dynamics (IDM, steering-first bicycle model)
  config.py          simulation configuration
  rl/                PPO agent, training environment, safety governor/shield, shared constants
  graphics/          frame renderer and merge-zone GIF builder
streamlit_app.py     interactive dashboard
models/              trained policy checkpoints used by the dashboard
scripts/             training, production gate, diagnostics and benchmarks
tests/               pytest suite, including a fixed-seed golden-run regression test
```

## Common tasks

```bash
pytest                                   # run the test suite
python scripts/train.py --help           # train a new policy
python scripts/gate_production.py        # acceptance gate for a checkpoint
```

## License

MIT, see [LICENSE](LICENSE).
