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
- The road edge (`busmerge.geometry`): the centre line at y = +1.75, the kerb at y = -1.75, and the
  bay, one lane deep (bay wall at y = -5.25). Its outline is `geometry.bay_outline()`:
  - **entry taper:** 265-285 m
  - **flat part:** 285-315 m
  - **exit taper:** 315-330 m

  The app, the GIF and the renderer draw that outline, and the checks use the same edge
  (`road_lower_edge`, `KERB_CORNERS`).
- Bay centre line: `lateral_offset = -3.5` (one lane-width beside the lane centre, which is 0).
- **Stop point (front bumper):** drawn per run from N(`bus_stop_position` = 300, 5) and clipped to
  [297, 307]. The whole bus is then in the flat part (rear ≥ 286 m), with 8 m left before the exit
  taper. The 8 m was measured: from a stop at 308 m, some exits touch the taper.

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
  - **No room:** if that is below 2 m/s, the arrival waits (at most one is held).
  - **Lost arrivals:** while the entry is not clear, no arrival is drawn, so those arrivals are lost
    rather than delayed. Each car blocks the entry for about 1.5 s, so the delivered rate is about
    λ / (1 + 1.5·λ): 0.28 cars/s at the app default of 0.4 (BUGS O20).

**Bus states:** `MOVING → DECELERATING → IN_BAY → WAITING_TO_MERGE → MOVING`. Scenario A, the
in-lane stop baseline, uses `STOPPED_IN_LANE` instead of the bay.

| State | Lateral | Longitudinal |
|---|---|---|
| `DECELERATING` (last 50 m) | follows the drawn kerb into the bay: target = how far the road edge under the bus's front has dropped (`geometry.bay_pull_in_target`) | comfortable IDM plan toward the stop point, limited by `Bus.bay_stop_acceleration` (below) |
| `IN_BAY` | held | boarding for `bus_dwell_time` |
| `WAITING_TO_MERGE` | the PPO agent decides | the PPO agent decides; ends at `lateral_offset ≥ -0.25` (`merge_success.PRODUCTION_MERGE_LATERAL_THRESHOLD`; the bus is then wholly in the lane if nearly parallel) |

`Bus.bay_stop_acceleration` limits the `DECELERATING` plan as follows:
- **Before the stop point:** brake exactly as needed to reach it at rest, or at crawl speed if the bus
  is not yet parallel: `a = min(plan, (v_end² − v²)/2d)`.
- **Still angled after it:** crawl at 1.5 m/s with bounded acceleration until parallel (within 2°).
- **Parallel:** stop at comfortable braking.
- **Always:** never pass the end of the flat part of the bay (315 m), and never exceed `MAX_BRAKE_MS2 = 9`. Arrival in the bay
  is a state change once the bus has come to rest (≤ 0.05 m/s).

The merge starts from the pose the bus actually stopped in.

**Steering.** The bus always steers by pure pursuit (`vehicle.pure_pursuit_steer`). It aims at the
target line a look-ahead distance ahead, in its own frame, so it counter-steers as its heading
approaches the line and arrives parallel instead of overshooting.
- **Look-ahead:** 18 m in the lane, 6 m pulling in (low speed, tight path), 12 m when merging.
- **Limits:** steering is bounded by the bus's maximum angle (15°) and rate (about 25°/s).
- **Why not shorter when merging:** the model rotates the bus about the centre of its body, so a
  shorter merge look-ahead swings the rear corner into the bay wall (BUGS O11).
- **What the brain controls:** while merging, the lateral target is the brain's command
  (`steer ∈ [-1, 1]` → [-3.5, 0] m). The bus goes where the brain asks and no further.

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
operation is the speed floor at 0 (vehicles do not reverse). Positions and headings are never clamped;
leaving the road is checked instead (section 7).

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
- `off_road`: the bus body below the kerb or the bay wall
- `over_centre_line`: the bus body in the opposing lane
- `merged`: completion after boarding
- `stuck_waiting`
- `never_waited`

**`merge_timeline`** gives the time from the end of boarding to fully merged, split into hesitation,
leaving the bay, entering the lane and settling, plus the time spent standing still.

**`check_invariants`** counts these violations (for the bus, leaving the road too):

| Check | Fails when |
|---|---|
| Braking | beyond 9.5 m/s² (9 + tolerance) |
| Acceleration | beyond 5 m/s² |
| Speed | negative |
| Backward motion | position decreases |
| Position jump | \|Δx − v·dt\| > 0.5 m |
| Overlap | any polygon overlap |
| Off the road | a bus corner below the kerb or bay wall, or a kerb corner inside the bus body |
| Over the centre line | a bus corner in the opposing lane |
| Extreme heading | beyond 60° |

The tolerance for the road edges is 0.02 m. A car across the centre line or the kerb is **reported,
not failed** (`InvariantReport.notes`). Cars drift in their lane and move over for the bus (BUGS O10).

**`traffic_metrics`** reports flow past the stop, cars within 60 m of the bus when boarding ends, and
car jerk.

| Gate | What it runs | Pass criteria |
|---|---|---|
| `pytest` (CI) | unit + regression tests, golden fingerprints of the engine and the env | all green; 9 legacy tests are strict `xfail` |
| `scripts/acceptance.py` | 100 episodes × noise 0 and 0.15, app defaults; `--seed-start 1000` for unseen seeds | merged 100/100 (≥ 98 with noise), 0 collisions, mean ≤ 15.0 s, p95 ≤ 20.0 s (owner's decision, 2026-10-10), **0 physics violations of every kind** |
| `scripts/verify_brain.py` | 1,000 episodes (seeds 2000-2999), app defaults, in parallel | reports the merge outcome judged on traffic only, the bus's road-edge anomalies by stage, every other violation, car edge crossings, Wilson 95% intervals and up to 10 failure seeds to replay in the app; a strict success is merged with none of them |
| smoke test / app button | 10 seeds, sidebar traffic settings | ≥ 90% merged, avg merge ≤ 30 s, longest time from end of boarding to merged ≤ 45 s, **0 physics violations** |
| app banner | every run | shows the outcome, the merge-time breakdown and the physics checks with first examples |

## 8. Brains (models/)

Measured with `scripts/verify_brain.py` on seeds that were never used for training or selection
(2000-2999), app defaults, honest steering, merge threshold -0.25 m, on the current code. *Merged* is judged on the traffic
only. *Strict* also requires the bus to stay on the road and out of the opposing lane, with no other
physics violation.

<!-- results:brain_table (generated by scripts/publish_results.py; do not edit) -->
| Brain | Seeds | Merged | Contact | Stuck | Strict | Over centre line | Off road | Mean / p95 time |
|---|---|---|---|---|---|---|---|---|
| v13 (default) | 2000-2999 | 97.8% | 2.2% | 0.0% | 89.4% | 0.0% | 8.7% | 13.3 / 16.7 s |
| v11 | 2000-2999 | 0.0% | 0.8% | 99.2% | 0.0% | 0.0% | 100.0% | – |
| v10 best | 2000-2099 | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% | 100.0% | – |
| v9 best | 2000-2099 | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% | 100.0% | – |
<!-- /results:brain_table -->

Every number above is generated from the measurements in `results/` (provenance: brain, seeds,
code commit, date); `tests/test_published_numbers.py` fails if a table here, in the README, in the case
study or in the app differs from them.

- **v13** is v11 fine-tuned under honest steering ([TRAINING.md](TRAINING.md)).
  - **Where it fails strict (Off road):** the kerb corner at the end of the exit taper cuts into
    its side, when it steers out slowly from the far end of the bay.
  - **Contact:** side contact while pulling out with a car alongside.
  - **Centre line:** it never crosses it.
**v13 stress test** (`verify_brain --traffic-rate`, the same 100 unseen seeds 2000-2099 at each inflow,
50 cars; app defaults otherwise):

<!-- results:stress_table (generated by scripts/publish_results.py; do not edit) -->
| Inflow (cars/s) | Cars within 60 m when boarding ends | Flow past the stop (cars/min) | Merged | Contact | Stuck | Strict | Off road | Mean / p95 time |
|---|---|---|---|---|---|---|---|---|
| 0.2 | 1.46 | 9.6 | 99.0% | 1.0% | 0.0% | 90.0% | 9.0% | 12.9 / 17.3 s |
| 0.4 | 2.56 | 15.9 | 97.0% | 3.0% | 0.0% | 84.0% | 13.0% | 13.3 / 16.6 s |
| 0.6 | 3.02 | 19.3 | 98.0% | 2.0% | 0.0% | 88.0% | 11.0% | 13.2 / 15.5 s |
| 0.8 | 3.43 | 20.6 | 98.0% | 2.0% | 0.0% | 85.0% | 13.0% | 13.2 / 16.1 s |
<!-- /results:stress_table -->

The inflow is the *requested* rate. The generator delivers less (about λ / (1 + 1.5·λ), BUGS O20), which
is why the cars present grow so little between 0.4 and 0.8.

- **No density has a centre-line crossing, a stuck run or any other physics violation.**
- **The differences between densities are within the 95% intervals** (about ±6 points at 100 seeds).
- **The traffic saturates:** doubling the inflow from 0.4 to 0.8 cars/s raises the flow by only 30%
  and the cars near the bus from 2.6 to 3.4. Arrivals wait for 0.5 s and 15 m of clear road, so "0.8"
  is not twice as dense. A real stress test needs the training scenarios (jam, platoon) or a
  different arrival model.

- **v9-v11** were trained while the merge steering overshot its target. They ask for a target half
  way out of the bay and stop there ([case study](CASE_STUDY_REWARD_HACKING.md)).
- **Acceptance (`scripts/acceptance.py`) is not passed by any brain.** v13 meets the time limits
  but not the contact and road-edge criteria (O2, O12).
  - **The time limits:** mean ≤ 15.0 s and p95 ≤ 20.0 s since 2026-10-10. They are meant to fail a
    brain that freezes, not a cautious one.
  - **The old limits** (6.0 / 7.0 s) were set while the steering overshot. Under honest steering, even
    a scripted full-throttle merge takes 6.3 s on average.
