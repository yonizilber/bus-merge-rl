# bus-merge-rl

A microscopic traffic simulation of a city bus pulling out of a bus bay and merging back into
traffic. The merge decision is made by a PPO (reinforcement learning) agent; surrounding cars
follow an Intelligent Driver Model with per-driver personalities. A Streamlit dashboard lets you
run scenarios, compare trained agents, and inspect the merge frame by frame.

> This README is a work in progress. Full documentation (architecture, results, design decisions
> and known limitations) is being written.

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
