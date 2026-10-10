# Test coverage and proposed automated tests

Status on 2026-10-10 (branch `fix/bus-steering-geometry`, default brain v13). This document has two
parts:
- **Part 1:** what is checked automatically today, and what is not.
- **Part 2:** a numbered menu of proposed tests, so the project owner can choose which to build.

Every proposed test names the bug or the class of bug it guards against. Most of these bugs were
found during this project (see [BUGS.md](BUGS.md)).

## Implemented (2026-10-10)

Menu numbers refer to Part 2.
- **#3, half-way stall:** `tests/test_brain_behaviour.py`.
  - v13 merges within 15 s on an empty road from 297, 302 and 307 m.
  - A companion test checks that v11 is caught stalling.
  - Two control placements (a car just ahead, a car passing fast) check that the bus waits in the bay.
- **#13, pure pursuit:** `tests/test_steering_controller.py`, 56 cases.
  - **Tolerance:** overshoot at most 5% of the starting distance. A 5 cm bound was too strict: the
    rate-limited controller overshoots 3.5 m steps by 0.10-0.14 m.
  - **Sensitivity:** the old law fails the same check.
  - **Scope:** the 6 m pull-in look-ahead is left out, since it is not stable for sudden steps at speed
    (BUGS O16).
- **#9, physics under any policy:** `tests/test_physics_any_policy.py`. Uniform and full-extreme random
  merging policies, at 0.4 and 0.8 cars/s.
- **#25, single sources:** `tests/test_single_source.py`. An AST scan for the bay x coordinates and the
  merge threshold, plus a check that the scan can see a copy.
- **#19, reward ranking:** `tests/test_reward_ranking.py`, with the default and the v13 reward.
- **#20, training smoke:** `tests/test_training_smoke.py`. Two epochs, all files written to a temporary
  folder; the weights must change and the app engine must drive with the result.
- **#1 and #4, strict `xfail` with `raises=AssertionError`:** each reproduced by a placement that fails
  today.
  - **#1:** stop at 307 m, a car 6 m behind at 6 m/s, contact of 0.85 m².
  - **#4:** stop at 307 m, a car passing, the kerb 0.10-0.14 m deep in the body.
  - **What the experiments showed:** in 20 constructed placements at 302 m, v13 never touched a car.
    It does leave the bay while a car is still alongside (up to -1.84 m) in about half of them. On an
    empty road it exits cleanly even from 307 m.
- **#21, rollback:** `tests/test_training_rollback.py`.
  - The rule is now a function, `train.rollback_due`, and it was fixed: rollback only restores a
    checkpoint that evaluated with at least one success.
  - A real two-epoch run set up as in the fine-tune recipe is not reset.
  - The same run under the old rule is reset, which proves the test can fail.
- **#26, published numbers:** `tests/test_published_numbers.py`.
  - `results/` holds each published measurement: per-seed rows and provenance.
  - Summaries are recomputed from the rows.
  - The marked blocks in the README, SPECS and the case study must equal what the measurements render.
  - A changed measurement is caught.
- **#29, headless app:** `tests/test_app_headless.py`.
  - The app loads, offers exactly the brains that exist with v13 first, and renders the published table.
  - For seeds 2000 (merged) and 2001 (off road) it shows the same outcome `verify_brain` measured.
  - Writing it found a bug: the app had no banner for off-road or centre-line outcomes (BUGS H15).
  - The merge-zone animation can be switched off in the sidebar; the test does so, because it draws
    every frame.
- **Margins:** all of these pass or fail by a wide margin. For example, a merge in 7.6-7.8 s against a
  15 s limit, and a 3,000-point reward gap against a measured 6,900.
- **Cost:** about 50 s locally for all the new tests.

## 1. Current coverage

### Runs automatically on every push (CI: `ruff check .` and `pytest`, about 171 test cases, 1-6 minutes)

| Area | What is asserted | Tests |
|---|---|---|
| Regression fingerprints | Five fixed-seed engine runs (scenario B ×3, A ×2) with v13, and four fixed-seed training-env episodes, reproduce stored hashes of every frame. **Any** behaviour change fails until the fingerprints are regenerated on purpose. | `test_golden_run`, `test_env_golden` |
| The physics checker itself | It detects braking beyond 9.5 m/s², backward motion, position jumps, polygon overlap, a bus below the kerb or bay wall (including a kerb corner inside the body), a bus over the centre line, and heading beyond 60°. A clean log passes. | `test_invariants` (unit part) |
| Physics end to end, few seeds | A real engine run has no overlap, negative speed or position jump. Cars enter the road without impossible braking. The bus stops in the bay without braking beyond the limit. | `test_invariants` (engine part) |
| Bus pull-in, 5 seeds | On the road (exact check), at the stop target, at bay depth, parallel, with a continuous heading, and frozen while stopped. | `test_bus_physics` |
| Safe-speed law | Never brakes beyond 9 m/s², never closes more than the gap in one step, keeps the minimum gap, and leaves the driver's command alone on a free road. | `test_safe_speed` |
| Car behaviour | IDM yield to the bus, blinker braking, no teleports or backward snaps, queues, squeeze hysteresis, the yield surprise filter. | `test_idm_merge_yield`, `test_blinker_presence`, `test_trajectory_kinematics`, `test_bus_queue_follow`, `test_squeeze_hysteresis`, `test_yield_surprise_filter` |
| Governor and shield (off by default) | Clear-road bypass, hold versus lunge, telemetry columns. | `test_governor_*` |
| One judge for every number | The crash judge in training equals the acceptance gate, including a car that is not the nearest and contact on the completing frame. Outcome rules: no early "merged", collision overrides merge, side contact counts. The validation demo judges like the app, and the merge timeline adds up. | `test_crash_judge`, `test_evaluation` |
| Observation | One builder; sentinels on an empty road; the feature width; noise changes the state but not the facts. | `test_observation`, `test_sensor_noise` |
| Training consistency | Training start poses are on the road and cover the stop range. PPO stores each sampled action with its own log-probability. | `test_training_consistency` |
| Legacy | Nine tests written against the old API, kept as strict `xfail`. | `test_behavior`, `test_merge`, `test_physics`, `test_safety`, `test_deadlock` |

**What this protects well:**
- **Accidental behaviour changes:** caught by the golden fingerprints.
- **The checker's correctness:** each kind of violation has a unit test.
- **Measurement consistency:** the app, the gates and training judge an episode the same way.

### Not automated (run by hand)

| Gap | Today | Why it matters (found in this project) |
|---|---|---|
| Brain quality | `scripts/verify_brain.py` (1,000 seeds, about 15 min on 16 cores), `scripts/acceptance.py` (200 episodes, about 20 min, single process), smoke test (10 seeds) | A drop in the merge rate or a new kind of failure is only seen if someone runs them |
| Physics at scale | The end-to-end physics tests use a handful of seeds at the default density, with one brain | The centre-line crossing (P11) showed in 100% of runs, but only once the road edges were checked over many runs |
| Physics under any policy | Every engine test uses a sensible brain or a scripted merge | A physics defect can hide behind a policy that never triggers it (the overshoot was only reached because v11 asked for -1.5 m) |
| Training loop | No test runs even one epoch of training | The rollback bug (P18) and the PPO buffer bug (P17) were invisible until a fine-tune failed |
| Reward function | Only the crash term and the shield-penalty scale are tested | The reward ranked a full merge first but gave no usable gradient from half way; the audit was manual |
| Steering controller | Covered only indirectly by the golden fingerprints | The overshooting controller (P11) passed every test |
| The app | Never run in CI (it was run headlessly by hand) | An import error or a broken banner would ship |
| Published numbers | The README, the app's brain table and SPECS are copied by hand | The app showed v11's 97/100 after it had become false |
| Single source of truth | Nothing stops a new copy of a constant | The bay was drawn in three places with different tapers (P15); the merge threshold existed twice (-0.1 in the engine and in `merge_success`) |

## 2. Proposed tests (menu)

Columns:
- **Cost:** *fast* is under 10 s, *medium* is under 2 min, *slow* (nightly) is over 2 min.
- **Today:** whether the test would pass on the current code.

A test expected to fail documents a known limitation. It would be added as a strict `xfail` that
names the BUGS entry, so it turns red the day the behaviour changes, for better or worse.

### A. Behavioural and scenario tests (the brain in a forced situation)

| # | Test | Asserts | Guards against | Cost | Today |
|---|---|---|---|---|---|
| 1 | Car alongside the bay | A car is placed beside the bus as boarding ends. The bus stays in the bay (lateral ≤ -3.0 m) until the car's rear has passed, and never touches it | Pulling out into a car alongside (BUGS O2) | fast | expected to **fail** on some placements (2.2% contact) |
| 2 | Empty road merges | With no traffic, the brain merges within 15 s of the end of boarding, from every stop point in the range (297, 302, 307 m) | A brain that freezes; the stop-range limits | fast | pass expected except possibly 307 m (O12) |
| 3 | No half-way stall | Once the bus is out of the bay on a clear road, the lateral command keeps rising until the merge completes; the bus never holds a lateral position below the threshold for more than 3 s | The v11 reward hack: asking for -1.5 m and relying on a defect (case study) | fast | pass expected |
| 4 | Exit from the far end of the bay | Stop at 307 m on a clear road. The exit never puts a kerb corner inside the body | O12 (8.7% of runs) | fast | expected to **fail** |
| 5 | Fast car approaching from behind | A car 15-30 m behind at 12 m/s. The bus does not start to leave the bay until the car has passed or the gap is safe | Pulling out in front of a closing car | fast | to be measured |
| 6 | Platoon | Five cars with 1-2 s headways pass. The bus waits for the gap after the last car, with no contact and no stuck run | Merging into the middle of a platoon; waiting forever | medium | to be measured |
| 7 | Policy sanity | The same observation gives the same action. Actions are finite on edge observations (empty road, a car at zero gap, extreme speeds) | NaN or erratic outputs on rare inputs | fast | pass expected |
| 8 | Scripted reference merge | An immediate scripted merge (steer for the lane, constant throttle, ignoring traffic) from every stop in the range is on the road and never crosses the centre line, and its time stays near the measured floor (6.3 s at full throttle) | Steering or geometry regressions that make a merge physically impossible or slower (P11-P13), independent of any brain | medium | pass expected |

### B. Physics and boundary tests

| # | Test | Asserts | Guards against | Cost | Today |
|---|---|---|---|---|---|
| 9 | Physics under a random policy | Many seeds with a random or adversarial policy (random steer and gas every step). There are 0 violations of the physical kinds: braking beyond the limit, acceleration beyond 5 m/s², negative speed, backward motion, position jump, extreme heading | Physics that is honest only for the actions a good brain happens to take | medium | to be measured (a random policy may drive off the road, which is a reported outcome, not a physics violation) |
| 10 | Invariant sweep across densities | 20-50 seeds at 0.2, 0.4, 0.6 and 0.8 cars/s with v13: 0 violations other than contact and the bus's road edges, and car-car overlap stays at 0 | Corrections that break only in dense traffic (spawn, queues) | slow | **passes** (measured 2026-10-10: 100 seeds at each of 0.2-0.8, 0 such violations) |
| 11 | Property-based safe-speed law | Random gaps, speeds and leader speeds (`hypothesis`): the command is never below -9 m/s², and when a stop is physically possible the follower never overlaps its leader in the next step | Edge cases of the one law every follower uses | fast | pass expected |
| 12 | Bicycle-model limits | Per step: the steering change is at most the rate limit, the angle at most its maximum, the heading change follows v·tan(δ)/L, and there is no lateral motion at zero speed | Teleports in heading or lateral position | fast | pass expected |
| 13 | Pure pursuit converges without overshoot | From any lateral offset (-4 to 1 m) and heading (±15°) at 2-10 m/s, the bus reaches the target line and never overshoots it by more than 5 cm | The overshooting controller behind the reward hack (P11) | fast | pass expected |
| 14 | Road-edge check against a dense reference | Random bus poses near the tapers: `road_edge_excess` agrees with a brute-force check (thousands of points along the body outline against the edge) | Holes in the off-road check (P14, the kerb corner) | fast | pass expected |
| 15 | Determinism | The same seed gives an identical frame log twice, in the app engine and in the training env | Hidden global state or an unseeded RNG, which would make every replayed seed a lie | medium | pass expected |
| 16 | No assignment of state | A static check that `position`, `velocity`, `heading_angle` and `lateral_offset` are written only by the physics update (with an allow-list such as spawning and scenario reset) | Silent corrections coming back ("Hand of God", P7) | fast | expected to **fail** on the scenario A pose resets (O7) and the bay-arrival `velocity = 0` (O5) |
| 17 | Spawning at every density | At 0.2-0.8 cars/s no car enters overlapping or needing braking beyond the limit, and the cars actually present grow with the inflow | Impossible arrivals (P4); "dense" settings that are not denser | medium | the "denser" part **fails**: from 0.4 to 0.8 cars/s the cars near the bus grow only from 2.6 to 3.4 (SPECS section 8) |

### C. RL and pipeline tests

| # | Test | Asserts | Guards against | Cost | Today |
|---|---|---|---|---|---|
| 18 | Reward terms, one by one | Contact gives a large negative reward and ends the episode. Success gives +5,000 only at the threshold. A timeout is penalised. The safe-steer term is 0 within 6 m of a car, and the commit weight applies only once out of the bay | Reward changes that silently alter what is learned | fast | pass expected |
| 19 | Reward ranking | Over 20 episodes, a scripted full merge earns more than holding half way, which earns more than staying in the bay | A reward that pays for stopping short (the audit, automated) | medium | pass expected |
| 20 | Training smoke | Two epochs with a tiny batch run end to end. The weights change, and the saved checkpoint loads in the app and drives one episode | Training-loop breakage; checkpoints the app cannot load | medium | pass expected |
| 21 | Rollback never restores the starting weights | A run that has never had a successful evaluation is not rolled back to its starting weights; rollback only restores a checkpoint that evaluated better | P18 (the silent reset that defeated two fine-tunes and v12) | fast, after extracting the rollback decision into a function | pass expected with `--rollback-patience 0`; the default rule still fails it |
| 22 | PPO ratio starts at 1 | Before the first optimiser step, the PPO ratio is 1 for every stored sample, including those beyond the action limit | P17 and any future mismatch between the stored action and its log-probability | fast | pass expected |
| 23 | Checkpoint round trip | Save and load give identical outputs. Loading the wrong feature width raises an error | Silently starting from random weights (H8, H9) | fast | pass expected |
| 24 | Training env equals the app | The same seed and actions give the same bus and car trajectories in `BusMergeEnv` and in the app engine | Two physics implementations drifting apart again (P1) | medium | pass expected |
| 25 | One merge threshold, one bay | A static check: no literal lateral threshold or bay coordinate (-0.1, -0.25, 265, 285, 315, 330) outside `merge_success.py`, `merge_constants.py` and `geometry.py` | New copies of constants (P15, the second -0.1 in the engine) | fast | pass expected |
| 26 | Published numbers match the measurements | The app's brain table, the README and SPECS quote the numbers in the stored `verify_brain` JSON of the default brain (or are generated from it) | Stale claims, like the app showing 97/100 for v11 after it had become false | fast | expected to **fail** until the numbers are generated |

### D. Nightly gates (scheduled CI, not on every push)

| # | Test | Asserts | Cost |
|---|---|---|---|
| 27 | Brain quality gate | `verify_brain` on 200 unseen seeds: merged ≥ 95%, strict ≥ 85%, 0 over the centre line, 0 other violations, mean time ≤ 15 s (v13 today: 97.8%, 89.4%, 0, 0, 13.3 s) | about 5 min on 16 cores |
| 28 | Stress sweep | Tests 10 and 17 at all densities, with floors set from the measured table | about 15 min |
| 29 | Headless app | `streamlit.testing` loads the app, runs one simulation and finds the outcome banner and the physics-check banner, with no exception; the brain picker lists only files that exist | about 1 min |

## Suggested order

If only a few are built first, these give the most protection for the effort:
- **3 and 13:** the reward hack and the defect behind it.
- **9:** physics under any policy.
- **20 and 21:** the training loop that hid two bugs.
- **25 and 26:** single sources and published numbers.
- **29:** the app in CI.

**Practical notes:**
- Tests 9, 10, 17, 27 and 28 need a `slow` or `nightly` marker and a scheduled CI job; the marker
  `slow` already exists in `pyproject.toml`.
- Test 11 adds the `hypothesis` dependency.
- Test 21 needs a small refactor: move the rollback decision out of `train()`.
