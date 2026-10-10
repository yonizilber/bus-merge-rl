# System specification

How the simulation, the agent and the evaluation work **today**. Numbers come from the code
(`busmerge/rl/merge_constants.py` and the modules named); history is in [JOURNAL.md](JOURNAL.md).

## 1. What is simulated

- A single-lane urban road, 1000 m long, simulated at **dt = 0.1 s**.
- A city bus (11.0 × 2.5 m) drives in, pulls into a bus bay, boards passengers for `bus_dwell_time`
  (15 s by default), and must merge back into the traffic lane.
- Cars follow an Intelligent Driver Model with per-driver personalities.
- The merge itself (steering and speed while leaving the bay) is decided by a PPO agent ("brain").

**Geometry.**
- Lane width: 3.5 m.
- Bay centre line: `lateral_offset = -3.5` (one lane-width beside the lane centre, which is 0).
- Stop point: drawn per run from N(300, 5), clipped to [285, 315].
- Exit taper: 15 m after the stop point.

**Position convention: `Vehicle.position` is the front bumper.** A vehicle of length L occupies
`[x − L, x]`. Everything that builds a body polygon goes through `busmerge.geometry.vehicle_corners`
(centre = `x − L/2`, rotated by the heading).

## 2. Package layout

```
busmerge/
  simulation.py      SimulationEngine: spawning, bus state machine, physics step, frame log
  vehicle.py         Vehicle (IDM + steering-first bicycle model), Bus, BusState, car classes
  config.py          SimConfig (traffic, dwell, passengers)
  evaluation.py      run_episode, classify_outcome, merge_timeline, evaluate_brain  ← the one harness
  invariants.py      physical checks on a frame log; bus_contact_times
  traffic_metrics.py flow past the stop, cars near the bus, car jerk
  geometry.py        rotated rectangles, polygon overlap area, vehicle_corners
  safe_speed.py      the longitudinal safety law (one safe-speed limit on acceleration)
  paths.py           repository-relative locations (models/, outputs/)
  rl/
    env.py           BusMergeEnv: training scenarios + reward on top of SimulationEngine
    observation.py   build_observation: the only observation builder (engine and env)
    ppo_agent.py     actor-critic network and PPOAgent (strict checkpoint loading)
    train.py         PPO training loop
    feature_encoding.py, merge_success.py, merge_yield.py, traffic_leaders.py,
    governor_logic.py, merge_constants.py, ...
streamlit_app.py     dashboard (runs SimulationEngine through busmerge.evaluation)
scripts/             train.py, acceptance.py, evaluate_brains.py, gate_production.py, diagnostics
tests/               pytest suite incl. golden fingerprints (tests/golden/)
models/              versioned checkpoints (default: ppo_bus_brain_v11_engine.pth)
```

## 3. Vehicles

**Cars.**
- **Classes:** five (Compact, Mid, Large, SUV, Aggressive). Parameters are drawn per driver: top
  speed, time headway, comfortable braking 1.8-2.5 m/s², minimum gap 2 m, reaction time.
- **Politeness:** sampled per driver from Beta distributions.
- **Lateral motion:** a steering-first bicycle model with Ornstein-Uhlenbeck lane drift.
- **Longitudinal motion:** IDM, re-evaluated at the driver's reaction time.
- **Yielding:** when the bus merges, cars yield through a continuous blend ("yield factor", rate-limited
  by a "surprise filter"). They also see a virtual blinker during the last 3 s of boarding.
- **Arrivals (`SimulationEngine._try_spawn_car`):** drawn with probability `traffic_rate·dt` per frame,
  only while the entry is clear (0.5 s since the last car and 15 m to the nearest car).
  - **Speed:** a car enters at `min(desired, safe_speed(room, v_leader))`, the same law every
    follower obeys (section 4).
  - **No room:** if that is below 2 m/s, the arrival waits. Arrivals are delayed, never dropped.

**Bus states:** `MOVING → DECELERATING → IN_BAY → WAITING_TO_MERGE → MOVING`. Scenario A, the
in-lane stop baseline, uses `STOPPED_IN_LANE` instead of the bay.

| State | Lateral | Longitudinal |
|---|---|---|
| `DECELERATING` (last 50 m) | ramps from the lane to the bay | comfortable IDM plan toward the stop point, limited by `Bus.bay_stop_acceleration` (below) |
| `IN_BAY` | held | boarding for `bus_dwell_time` |
| `WAITING_TO_MERGE` | the PPO agent decides | the PPO agent decides; ends at `lateral_offset ≥ -0.1` |

`Bus.bay_stop_acceleration` limits the `DECELERATING` plan as follows:
- **Before the stop point:** brake exactly as needed to reach it at rest, or at crawl speed if the bus
  is not yet parallel: `a = min(plan, (v_end² − v²)/2d)`.
- **Still angled after it:** crawl at 1.5 m/s with bounded acceleration until parallel (within 2°).
- **Parallel:** stop at comfortable braking.
- **Always:** never pass the end of the bay, and never exceed `MAX_BRAKE_MS2 = 9`. Arrival in the bay
  is a state change once the bus has come to rest (≤ 0.05 m/s).

The merge starts from the pose the bus actually stopped in.

## 4. Follower physics: one safe-speed law

Every follower (cars, the bus once back in the lane, and the merging bus toward the nearest car fully
ahead of it) has its driver's acceleration limited by `busmerge/safe_speed.py`:

```
v_safe  = sqrt(v_leader² + 2·b_comf·gap)     gap = leader rear − min_gap − follower front
v_frame = v_leader + gap / dt
a       = max(min(a_driver, (min(v_safe, v_frame) − v) / dt), −9 m/s²)
```

Speed and position then follow from the acceleration. Nothing is assigned. If even 9 m/s² is not
enough, vehicles touch and the contact is recorded as a collision. The only remaining non-physical
operations are the speed floor at 0 (vehicles do not reverse) and clamps on the merging bus (lateral
position to [-4.5, 0.5], heading to ±60°), which are not yet counted (BUGS O3).

This law replaced, on 2026-10-10, the "Hand of God" corrections: speed caps of up to 2.4 m/s per frame,
position trims, frozen stop-holds and forward-only clamps. Under those, 68/100 acceptance runs
contained braking beyond 9 m/s², and a contact physics could not avoid was hidden. The old code is at
the git tag `legacy-hand-of-god`.

## 5. The agent

**Observation (`rl/observation.py::build_observation`).** 4, 7 or 11 features: merge progress, bus
heading, gap to the nearest car, lateral clearance, car speed, car acceleration, car width, car length,
relative speed, relative acceleration, car heading.
- **Normalisation:** each feature is clipped and normalised in `feature_encoding.encode_features`.
- **No car in the scan window** (50 m ahead, 20 m behind): gap = 60 m and relative speed = 0.
- **Optional perception noise:** temporally correlated (Ornstein-Uhlenbeck) biases, applied to the
  encoded state only. Governor and shield always see the truth.

**Action.** `(steer, gas)` in [-1, 1]².
- **Lateral target:** `interp(steer, [-1, 1], [-3.5, 0])`.
- **Speed target:** `max(0, gas)·BUS_MAX_SPEED` (11.1 m/s).
- **Longitudinal control:** a P-controller, `a = clip(2·(v_target − v), −3, MERGE_ACCEL_MAX = 2)`.
- **Steering:** a pure-pursuit bicycle step.
- **Safety layers:** a predictive governor (off by default; the shipped brains were trained without it)
  and a per-frame safety shield (always on).

**Network.** Actor-critic MLP with a state-dependent log-std head. The feature count is read from the
checkpoint itself.

## 6. Training (`rl/env.py`, `rl/train.py`, `scripts/train.py`)

`BusMergeEnv` has **no physics of its own**: `reset()` builds a scenario and hands the bus and cars to a
`SimulationEngine` (with `load_brain=False` and `record_frames=False`). `step()` passes the action to the
engine as `external_action` and steps it.

**Scenarios:**
- A-F: jam, slow city, mid-merge, fast flow, platoon, dense urban
- G: sparse warm-up
- H: dense evaluation stream
- P: production-like queue

Training randomises the starting pose (±0.4 m lateral, ±4.6° heading), the bus power, and driver
distraction.

**Reward (core profile).**
- **Shaping terms:** -1 per step, +0.5 for waiting still when the lane is blocked, lateral progress,
  a closing-risk term, a governor-hold deterrent, a shield-intervention penalty, and a safe-steer incentive.
- **Contact (`exp7sat*` run tags):** the bus polygon is tested against **every** nearby car, with lane
  drift included. Contact above `OVERLAP_MIN_AREA_M2 = 0.01 m²` is a terminal crash
  (−2500 − 1000·progress), judged **before** success. This is the same test as the acceptance gate.
- **Success:** +5000, by the app's completion rule.
- **Timeout:** −3500 − 6000·(idle fraction)².

**Options and run tags:** `--feature-dim`, `--disable-governor`, `--seed` (re-seeded every epoch).
- The run tag selects the reward profile: `exp7sat*` enables the contact judge; `exp7satv10*` selects
  the experimental "spongy" profile.
- A checkpoint named `<tag>_best.pth` is used as the starting point.

## 7. Evaluation and gates

All of them go through `busmerge/evaluation.py`, so a number means the same thing everywhere.

**`classify_outcome(frame log)`** returns one of:
- `collision`: any contact between the bus body and a car body (exact polygons), or a rear-end
- `merged`: completion after boarding
- `stuck_waiting`
- `never_waited`

**`merge_timeline`** gives the time from the end of boarding to fully merged, split into hesitation,
leaving the bay, entering the lane and settling, plus the time spent standing still.

**`check_invariants`** counts five kinds of physically impossible moment:

| Check | Fails when |
|---|---|
| Braking | beyond 9.5 m/s² (9 + tolerance) |
| Acceleration | beyond 5 m/s² |
| Speed | negative |
| Backward motion | position decreases |
| Position jump | \|Δx − v·dt\| > 0.5 m |
| Overlap | any polygon overlap |

**`traffic_metrics`** reports flow past the stop, cars within 60 m of the bus when boarding ends, and
car jerk.

| Gate | What it runs | Pass criteria |
|---|---|---|
| `pytest` (CI) | unit + regression tests, golden fingerprints of the engine and the env | all green; 9 legacy tests are strict `xfail` |
| `scripts/acceptance.py` | 100 episodes × noise 0 and 0.15, app defaults; `--seed-start 1000` for unseen seeds | merged 100/100 (≥ 98 with noise), 0 collisions, mean ≤ 6.0 s, p95 ≤ 7.0 s, **0 physics violations of every kind** |
| smoke test / app button | 10 seeds, sidebar traffic settings | ≥ 90% merged, avg merge ≤ 30 s, longest time from end of boarding to merged ≤ 45 s, **0 physics violations** |
| app banner | every run | shows the outcome, the merge-time breakdown and the physics checks with first examples |

## 8. Brains (models/)

Acceptance on 100 unseen seeds (1000-1099), app defaults, after strict physics was adopted
(2026-10-10). Merged / collisions / stuck, then mean and p95 time from the end of boarding to merged:

| Checkpoint | Trained on | Noise 0 | Noise 0.15 | Time (noise 0) |
|---|---|---|---|---|
| `ppo_bus_brain_v11_engine.pth` (**default**) | unified env, v9 fine-tune | 97 / 3 / 0 | 96 / 4 / 0 | 4.8 / 5.4 s |
| `ppo_bus_brain_exp7satv10_best.pth` | legacy env, "spongy" profile | 98 / 2 / 0 | 97 / 2 / 1 | 5.7 / 6.1 s |
| `ppo_bus_brain_exp7satv9_best.pth` | legacy env (golden-test brain) | 93 / 2 / 5 | 94 / 2 / 4 | 5.9 / 6.3 s |
| `ppo_bus_brain_exp7sat*_best.pth`, `exp4`, `exp7` | legacy env | not measured | | |

- **No brain passes acceptance:** every collision is a side contact while pulling out with a car
  alongside (BUGS O2). There are no physics violations apart from those contacts.
- **v11 vs v10:** v11 is the fastest. v10 has slightly fewer contacts, but with 100 seeds the
  difference between 2 and 3-4 is not significant.
