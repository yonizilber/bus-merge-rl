# Bugs: found, fixed, open

Every entry gives the symptom, the root cause, the fix and the evidence. Commits refer to this
repository. Entries before 2026-10-04 are in the original development repository's notes.

## Fixed

### Harness and evaluation consistency

| # | Symptom | Root cause | Fix | Evidence |
|---|---|---|---|---|
| H1 | The committed code did not run from a fresh clone | Core modules and tests were never committed; `app.py` imported an uncommitted `PhysicsMode` | Snapshot commit; new package | Clean export: 114 passed, app runs headlessly |
| H2 | App showed "Bus merged in -36 s" | Merge completion was searched from t=0; the bus starts in the lane at progress 1.0 | `classify_outcome` searches only after WAITING_TO_MERGE (`38c7bf3`) | Regression test `test_bus_starting_in_lane_does_not_count_as_merged_early` |
| H3 | Smoke test 10/10, validation "9/30", app 30/30 for the same brain | Four episode loops with different traffic settings and different definitions of "merged"/"collision" | One harness: `run_episode` + `classify_outcome` (`38c7bf3`) | App, smoke test and demo agree |
| H4 | "9/30" validation for every v8/v9 brain | Legacy 1-D crash rule read `presence_factor`, floored at 0.15 while waiting → a car passing the bay was a "crash"; demo built the env without the checkpoint's reward flags | SAT is the only crash judge when enabled; flags derived from the checkpoint (`38c7bf3`) | 29-30/30 in both engines after the fix |
| H5 | In-training evaluation scored 0/30 for every checkpoint; "best" selection did not work | Evaluation env built without the run's SAT/spongy flags | `ENV_FLAGS` from the run tag (`4e3fa7b`) | With the flags (and the correct feature count, H8) v9’s in-training baseline is 29/30 |
| H6 | Shipped checkpoints could not be reproduced | `scripts/train.py` had no `--disable-governor` | Flag added (`4e3fa7b`) | |
| H7 | Brains labelled "7-feat" in the app | Hand-written labels; v8/v9/v10 are 11-feature networks | Labels read from the checkpoint (`4e3fa7b`) | |
| H8 | Training silently restarted from random weights | Bootstrap checkpoint with the wrong feature count: shape error swallowed | Strict loading raises (`4e3fa7b`) | |
| H9 | App ran a random network if a checkpoint was missing | `PPOAgent.load` printed and continued | `load(strict=True)` (`29a06e0`) | Test raises `FileNotFoundError` |
| H10 | `--seed 1` and `--seed 2` produced identical runs | In-training evaluation re-seeded the global RNGs | Re-seed every epoch from (seed, epoch) (`d0de39c`) | Runs diverge from epoch 1 |
| H11 | "Accel Paradox" on the frame a car stops | Detector compared Δv to the logged accel, already reset to 0 at rest | Stop frame excluded (`48225ad`) | `test_stop_frame_is_not_reported_as_accel_paradox` |
| H12 | Side contact reported as "merged" | `classify_outcome` only used the bus's rear-end flag | Polygon contact with any car = collision (`eeba728`) | `test_side_contact_with_a_car_counts_as_collision` |
| H13 | Training and the acceptance gate disagreed on what a collision is | Training judged only the nearest car, without the bus's lane drift, penalised contact up to 1 m² mildly (0.12 m² cost about 6 points) and judged success before contact | Same polygon test, threshold and order as the gate (`973facd`) | `tests/test_crash_judge.py` (incl. a contact with a car that is not the nearest) |
| H14 | Every brain failed the smoke test after fix A while merging within 6 s | The "max wait" criterion compared the clock time at which boarding ended (`wait_before_merge_s`) with 45 s; it never measured a wait | Measures the longest time from end of boarding to merged; field renamed `boarding_ended_at_s` (`fea1d7c`) | Smoke 10/10 for v9, v10, v11; longest wait 5.2-5.9 s |

### Physics

| # | Symptom | Root cause | Fix | Evidence |
|---|---|---|---|---|
| P1 | Training and app physics drifted (bumper-cap order, crash rules, empty-road sentinel, lane drift) | Two implementations of the same world | `BusMergeEnv` steps `SimulationEngine` (`95d1a4f`); one observation builder (`f7d29c4`) | Golden tests; legacy kept at tag `legacy-dual-physics` |
| P2 | Drawings and crash tests shifted half a vehicle ahead of the physics | Physics uses the front bumper, drawing/SAT used the centre | `busmerge.geometry.vehicle_corners` everywhere (`eadf451`) | Rendered frame matches the logged bumper; a hidden 0.24 m² overlap became visible |
| P3 | Bus braked at about -50 m/s² when entering the bay, every run | `velocity = 0` on arrival; a crawl floor that raised the speed; a bay-end clamp; a pose reset at the start of the merge | `Bus.bay_stop_acceleration` (v²/2d, crawl to align, bounded by 9 m/s²); assignments removed (`c05b885`, `b3a75ce`) | Worst bus braking -2.0 m/s²; `test_bus_stops_in_the_bay_physically` |
| P4 | Cars braked at 16-24 m/s² right after appearing | Spawned at 68-95% of top speed regardless of the car ahead; the follower cap then cut the speed | Spawn speed limited to `max_approach_speed(room)`; arrival deferred below 2 m/s (`ff4e54b`) | 551/955 → 0 violation frames; flow +1-2%; `test_cars_enter_the_road_without_impossible_braking` |
| P5 | A slow, still-angled bus could not accelerate back to crawl speed before the stop point | `v_end = min(v, crawl)` made the bound 0 | `v_end = crawl` when not parallel (`973facd`) | |
| P6 | Renderer drew a tilt for vehicles with heading 0 | Fallback "sine approximation" when heading was exactly 0 | Logged heading used as is (`eadf451`) | |
| P7 | Impossible braking (beyond 9 m/s^2) in 68/100 acceptance runs; cars moved backwards or jumped position in 3-6/100 | "Hand of God" corrections kept cars apart by assignment: speed caps (up to 2.4 m/s per frame), position trims, stop-holds, forward-only clamps | One safe-speed law on acceleration for every follower (`busmerge/safe_speed.py`); corrections deleted (`ea0f727`, tag `legacy-hand-of-god`) | 0 physics violations other than contact in 600 acceptance runs |
| P8 | Two definitions of a safe speed (arrivals: stationary leader; followers: braking leader) | Arrival rule was written to match the old cap | Arrivals use `safe_speed` (`ea0f727`) | Flow past the stop +5% (0.4 cars/s), +12% (0.8 cars/s): arrivals no longer throttled |
| P9 | Two tests expected a car to stop where no car can: on the bumper line at 8 m/s (3.6 m needed even at 9 m/s^2), or frozen at 0 m/s while alongside | The stop-hold froze cars in place | Tests start from physically possible states and check the behaviour (`ea0f727`) | |

### App and tooling (`29a06e0` unless noted)

Failure banners chained to the wrong `if`; a merge-test preset that changed nothing; the smoke result
erased by an immediate rerun; the GIF written to a shared file in the working directory; the dashboard
reading the current sidebar instead of the run's settings; a collision-prone cache key; unknown training
flags silently ignored; "secret" seeds that were public; about 200 lines of commented-out code;
deprecated `use_container_width`. Later: the smoke test now includes the physics checks (`d81b69f`);
the physics-check function was 35× faster after vectorisation and had dead code removed (`d81b69f`).

## Open

### Physics

| # | Issue | Where | Notes |
|---|---|---|---|
| O2 | Bus-car side contact in 3-4/100 runs (v11), 2/100 (v9, v10) | brain behaviour | Real: pulling out while a car is alongside. The old corrections hid it; a 300-epoch fine-tune (v12) did not remove it, see TRAINING.md |
| O3 | Clamps on the merging bus (lateral to [-4.5, 0.5], heading to ±60°) are corrections the checks do not count | `simulation.py` merge steering step | Count when they bind, then remove |
| O4 | No check that the bus stays inside the bay geometry | — | Largest stop measured 315.44 m, 0.44 m into the exit taper |
| O5 | Arrival in the bay still assigns `velocity = 0` (≤ 0.05 m/s) | `simulation.py` arrival | Within the physical limit, but an assignment |
| O7 | Scenario A (in-lane stop) still resets pose on arrival and at dwell end | `simulation.py` | Baseline scenario only |

### Training and reward (pre-existing, not yet addressed)

| # | Issue | Where |
|---|---|---|
| R1 | Closing-risk reward term penalises `rel_speed > 0` (gap opening) instead of closing | `rl/env.py` reward term 3 |
| R2 | PPO stores the clamped action but its log-probability was computed on the unclamped sample | `rl/ppo_agent.py`, `rl/train.py` |
| R3 | Saving every epoch may overwrite a promoted checkpoint | `rl/train.py` (not verified) |
| R4 | The experimental "spongy" profile (v10 tags) still treats contact up to 3 m² as non-terminal, unlike the gate | `rl/env.py` |
| R5 | In-training "best" selection picks checkpoints that are worse in the app | `rl/train.py`; selection is done with `scripts/acceptance.py` instead |
| R6 | From-scratch training (600 epochs) reaches 20-25 s, far from v9/v11 | recipe |

### Other
- Nine legacy tests written against an old API are kept as strict `xfail`.
- `SimConfig.bus_stop_position` is not used by the simulation (stop point drawn around 300 m), and bay
  taper lengths differ between the renderer, the GIF and the vehicle model.
- The predictive governor's escape boost (planned "G2") was never finished; the governor is off by default.
- Under default physics, legacy v9 merges 28/30 since the start-pose reset was removed.
