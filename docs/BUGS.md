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
| P10 | Six clamps hid what the bus and cars did (heading ±60°, bus lateral [-3.5, 0.5], car lateral [-0.05, 0.55], lane drift ±0.4) | Corrections by assignment that the checks could not see | Clamps deleted; the road edges (kerb, bay wall, centre line) and extreme heading are checked instead (`7b59caf`) | Verification of v11 on 1,000 unseen seeds showed what they hid: P11-P13 |
| P11 | The bus crossed the centre line while merging in 100% of runs (median 0.84 m, up to 2.34 m, for about 5 s) | The merge steering `atan2(lateral error, max(v, 5))` had no heading term: an undamped loop that overshoots any target | Pure pursuit with the heading term, `vehicle.pure_pursuit_steer`, shared by every bus state (12 m look-ahead when merging) | Scripted exits on 800 runs: never over the centre line, heading ≤ 11°. v11 no longer merges, see O8 |
| P12 | The bus cut the kerb before the bay in 47% of runs (up to 1.32 m) | The pull-in ramp started 50 m before the stop point wherever that was, not where the drawn taper starts | The lateral target is read off the drawn road edge under the bus's front (`geometry.bay_pull_in_target`), 6 m look-ahead | 300 seeds without a brain: 0 off-road frames (exact check, P14), stop at the target, lateral -3.5 ± 0.06 m, parallel, braking ≤ 2.4 m/s² |
| P13 | The bus stopped past the end of the bay in 3% of runs, could stop with its rear in the entry taper, or too close to the exit to steer out | Stop target N(300, 5) clipped to [285, 315] for the front bumper; the bay-end limit was the stop target + 15 m (up to 330 m) | Stop target clipped so the whole bus is in the flat part (rear ≥ 286 m) with 8 m to the exit taper (front ≤ 307 m; measured: from 308 m some exits touch the taper); the limit is the real bay end (315 m); the aim point is `SimConfig.bus_stop_position` | |
| P14 | The checker could miss the kerb cutting into the side of the bus | Only the four body corners were compared with the road edge; where a taper meets the plain kerb, the kerb has a corner pointing into the road that can enter a body side with all four body corners on the road (up to about 0.5 m) | `geometry.KERB_CORNERS` tested against the body | `test_bus_side_over_the_kerb_corner_is_off_road` |
| P15 | The drawn bay was defined in three places; the renderer drew 10 m tapers instead of 20/15 m | Copies of the numbers | App, GIF and renderer draw `geometry.bay_outline()`, the outline the checker uses | |
| P16 | 14.6% of training start poses had a corner past the bay wall; none covered the app's stop range (297-307 m) | The env drew 300 ± 2 m, ±0.4 m, ±4.6° and clipped each separately | Start poses drawn over `geometry.bus_stop_range` and kept only if `geometry.road_edge_excess` (the checker's function) says the body is on the road (`b0aa46b`) | `test_training_start_poses_are_on_the_road_and_cover_the_stop_range` |
| P17 | PPO learned least from the action the honest steering needs (`steer` ≈ +1, the action limit) | The buffer stored the clipped action with the raw sample's log-probability (was R2): the PPO ratio differed from 1 at the limit before any update, so good full-steer actions lost their gradient and bad ones were amplified | The raw sample is stored; only the vehicle's command is clipped (`b0aa46b`) | `test_ppo_stores_the_sampled_action_with_its_own_log_probability` |
| P18 | A fine-tune that starts with no successful evaluation can never improve | After 3 evaluations without a new best (30 epochs), training restores the best checkpoint. A run that starts at 0 successes has no best except its starting weights, so every 30 epochs of learning were thrown away. v12 was rolled back 7-8 times in 31 evaluations, which may explain part of its flat curve | `--rollback-patience` (default 3, unchanged); 0 disables it, as used for the 2026-10-10 fine-tune | Logs: steering at the half-way state rose for 20-30 epochs and dropped back to v11's value right after each rollback |

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
| O2 | Bus-car side contact: v13 2.2% of 1,000 runs (v11 under the old steering 2.1%) | brain behaviour | Real: pulling out while a car is alongside. Present in every brain |
| O5 | Arrival in the bay still assigns `velocity = 0` (≤ 0.05 m/s) | `simulation.py` arrival | Within the physical limit, but an assignment |
| O7 | Scenario A (in-lane stop) still resets pose on arrival and at dwell end | `simulation.py` | Baseline scenario only |
| O8 | v9-v11 do not merge under honest steering: they ask for a target half way out and relied on the old controller's overshoot | brain behaviour | **Resolved by v13** (fine-tuned under honest steering, 97.8% merged); the old brains are kept for comparison |
| O12 | v13: the kerb corner at the end of the exit taper cuts into the bus's side in 8.7% of runs | brain behaviour | From the far end of the stop range (about 306-307 m) the brain steers out slowly; scripted exits from the same stops are clean |
| O13 | Acceptance's time limits (6.0 / 7.0 s) were set while the steering overshot; a scripted full-throttle merge takes 6.3 s under honest steering | acceptance thresholds | **Resolved by decision (2026-10-10):** mean ≤ 15.0 s, p95 ≤ 20.0 s. v13: 13.3 / 16.7 s |
| O14 | With v13, cars cross the centre line in 60% of runs (up to 0.93 m), against 13.7% with v11 under honest steering | car behaviour while the bus merges slowly | Reported, not failed (O10) |
| O15 | -0.25 m means wholly in the lane only when the bus is nearly parallel: in 3 of 1,000 v13 runs a rear corner was still over the kerb line when the merge counted | `merge_success.py` | A geometric criterion (whole body in the lane) would be exact |
| O10 | Cars cross the centre line (and the kerb, up to 0.35 m) in about 35% of runs | car lane drift and moving over for the bus | Reported, not failed (`InvariantReport.notes`), decision of 2026-10-10 |
| O11 | The model rotates the bus about the centre of its body; a real bus pivots near its rear axle, so the tail swing is exaggerated | `vehicle.py` bicycle model | Limits how sharp the exit may be: with a merge look-ahead below 12 m the rear corner swings into the bay wall |

### Training and reward (pre-existing, not yet addressed)

| # | Issue | Where |
|---|---|---|
| R1 | Closing-risk reward term penalises `rel_speed > 0` (gap opening) instead of closing | `rl/env.py` reward term 3 |
| R3 | Saving every epoch may overwrite a promoted checkpoint | `rl/train.py` (not verified) |
| R4 | The experimental "spongy" profile (v10 tags) still treats contact up to 3 m² as non-terminal, unlike the gate | `rl/env.py` |
| R5 | In-training "best" selection picks checkpoints that are worse in the app | `rl/train.py`; selection is done with `scripts/acceptance.py` instead |
| R6 | From-scratch training (600 epochs) reaches 20-25 s, far from v9/v11 | recipe |

### Other
- Nine legacy tests written against an old API are kept as strict `xfail`.
- The predictive governor's escape boost (planned "G2") was never finished; the governor is off by default.
- Under default physics, legacy v9 merges 28/30 since the start-pose reset was removed.
