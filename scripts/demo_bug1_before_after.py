#!/usr/bin/env python3
"""Standalone before/after demo for Bug 1 (governor hold vs shield lunge).

Not part of the test suite -- a human-readable reproducer you can run against two
different git checkouts (e.g. via `git worktree`) to see the literal numbers change.
Reconstructs the exact scenario from test_governor_hold_shield_conflict.py: a bus
mid-merge (progress~0.35) with a trailing car closing at ~3 m/s, ~0.40 m behind the
bus's rear bumper -- close/fast enough that the governor vetoes acceleration
(reason="governor_hold"), but not so close that the shield's own independent
full-stop guard (emergency_stop) fires first.

Run identically in two worktrees to compare:
    python scripts/demo_bug1_before_after.py
"""


import numpy as np
import torch

from busmerge.config import SimConfig
from busmerge.simulation import SimulationEngine
from busmerge.vehicle import Bus, BusState, Vehicle, CAR_PARAMS
from busmerge.rl.env import BusMergeEnv

print("=" * 70)
print("Bug 1 reproducer: trailing car closing fast, governor vetoes gas")
print("bus progress~0.35, gap~0.40m, closing at 3 m/s")
print("=" * 70)

# ---- Production path (simulation.py, same stack app.py uses) --------------
eng = SimulationEngine(scenario="B", config=SimConfig(), governor_disabled=False)
eng.brain.policy = lambda state_tensor: (torch.tensor([[0.6, 0.6]]), None, None)
bus = Bus(999, 300.0, 2.0, CAR_PARAMS)
bus.state = BusState.WAITING_TO_MERGE
bus.lateral_offset = -2.275
bus.heading_angle = 0.0
car = Vehicle(4, 288.60, 5.0, CAR_PARAMS)
eng.vehicles = [bus, car]
eng._handle_bus_logic(bus)

print(f"\n[Production / Streamlit stack]  bus.acceleration = {bus.acceleration:+.2f} m/s^2")
print("  positive (~+2.0) = BUG: shield lunged forward despite governor's hold")
print("  zero or negative  = FIXED: shield respected the governor's hold")

# ---- Training path (busmerge/rl/env.py) ------------------------------
env = BusMergeEnv(eval_mode=False, governor_disabled=False)
env.reset()
env.bus.state = BusState.WAITING_TO_MERGE
env.bus.position = 300.0
env.bus.velocity = 2.0
env.bus.lateral_offset = -2.275
env.bus.heading_angle = 0.0
car2 = Vehicle(4, 288.60, 5.0, CAR_PARAMS)
env.vehicles = [car2]
env.step(np.array([0.6, 0.6], dtype=np.float32))

print(f"\n[Training env]  bus.acceleration = {env.bus.acceleration:+.2f} m/s^2  "
      f"(governor_reason={env.last_governor_reason!r}, shield_condition={env.last_shield_condition!r})")
print("  positive (~+2.0) = BUG   |   zero or negative = FIXED")
print("=" * 70)
