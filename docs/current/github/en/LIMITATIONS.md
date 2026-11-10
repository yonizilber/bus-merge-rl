# Limitations

Everything that is known not to work, in plain words, with the test that tracks it. None of this is hidden: each
item has an ID in the full list (`docs/reference/BUGS.md`), and where a test can show it, a strict xfail[^strict_xfail]
test does.

## The agent

<!-- cards -->

| ID | What happens | How often | Why | Tracked by |
|---|---|---|---|---|
| O2 | The bus pulls out while a car is alongside and the two touch | 2.2% of 1,000 unseen runs (brain 0.13.0) | A real behaviour of the agent; every brain has it. Likely reasons, not yet tested: it sees only the nearest car and has no memory, and its training rarely shows a moving car beside the bay | `test_brain_behaviour.py` |
| O12 | The bus leaves the road: a kerb corner[^kerb_corner] cuts into its side | 8.7% of runs | From the far end of the bay (about 306-307 m), after letting a car pass, the agent steers out too slowly. A scripted exit from the same stops is clean, so it is the agent, not the geometry | `test_brain_behaviour.py` |
| O15 | The merge counts as complete while a rear corner is still over the kerb line | 3 of 1,000 runs | "Complete" means the bus centre is at -0.25 m or further into the lane, which is wholly in the lane only when the bus is nearly parallel. A criterion based on the whole body would be exact | none |

## The simulation

<!-- cards -->

| ID | What is simplified | Effect | Tracked by |
|---|---|---|---|
| O17 | There is no vehicle mass: every vehicle, the 11 m bus included, can brake as hard as 9 m/s². Real emergency braking is about 8-9 m/s² for a car and about 5-7 for a city bus | The bus can follow closer than a real one | `test_physics_limits.py` |
| O18 | There is no brake actuation lag: a car goes from cruising to -9 m/s² within one 0.1 s step, a jerk[^jerk] of about 100 m/s³. A real brake needs 0.15-0.3 s | Rare: about 25 frames in 5 runs | `test_physics_limits.py` |
| O19 | The safe-speed law lets a follower get up to 0.55 m into its own 2 m minimum gap (never into contact) | Found by property-based testing | `test_safe_speed_properties.py` |
| O20 | The car generator loses arrivals while the entry is blocked, so the inflow delivered is about λ / (1 + 1.5·λ): 80% of the setting at 0.2 cars/s, 71% at the default 0.4, 46% at 0.8 | The "heavy" traffic settings are not much heavier. A real stress test needs the training scenarios or a different arrival model | `test_traffic_density.py` |
| O11 | The model turns the bus about the centre of its body; a real bus pivots near its rear axle | The tail swing is exaggerated, which limits how sharply the bus may exit | none |
| O16 | The pull-in steering (6 m look-ahead) is unstable for a sudden target step at speed, for example 3.5 m off the line at 10 m/s | It only ever follows the gradual kerb line, and 300 pull-ins were clean | none (the steering test excludes it) |
| O21 | The cars' steering law has no heading term and overshoots every target, the defect the bus had before the case study's fix. Measured: a 0.5 m sideways move overshoots by 100% (peak heading about 5°); a 3.5 m move by 99-100% (34-39°) and never settles | Hidden in v1.0 because cars only nudge 0.5 m to make room for the bus. It causes most of the cars crossing the centre line (see below). A lane change would show it. A fix is pure pursuit for cars, and then every number that depends on car behaviour must be measured again | `test_car_steering_controller.py` |
| O22 | The IDM acceleration functions change the vehicle's state (the squeeze flag and the yield limiter), not only return a number | Hidden because the engine asks once per car per frame. It prevents "what-if" queries: a lane-change model such as MOBIL must ask what the acceleration would be in another lane without braking the car now. A fix splits each function into a pure computation and an explicit commit | `test_idm_query_side_effects.py` |
| O5, O7 | The arrival in the bay still sets the bus speed to 0 (at 0.05 m/s or less), and scenario A resets the bus pose | An assignment, within the physical limit | `test_no_state_assignment.py` |

## What is reported but not failed

| ID | What | Decision |
|---|---|---|
| O10, O14 | Cars cross the centre line (and the kerb, up to 0.35 m). With brain 0.13.0 it happens in 60% of runs, up to 0.93 m | Mostly the overshoot of the cars' steering law (O21), not lane drift or realism: in a 50-seed check, 62% of runs have a car over the centre line, 6% with the cars' 0.5 m nudge switched off, and 8% with cars steered by pure pursuit. It is reported, not failed (2026-10-10), but it is a defect of the model |

## Training

| ID | What | Note |
|---|---|---|
| R1 | The closing-risk reward term fires when the gap is opening instead of closing | Not yet fixed; changing the reward means retraining |
| R3 | Saving every epoch may overwrite a promoted checkpoint | Not verified |
| R4 | The experimental "spongy" profile (brain 0.10.0's training runs) treats contact up to 3 m² as non-terminal | Experimental only |
| R5 | The in-training "best" selection picks checkpoints that are worse in the app | Selection is done with the acceptance gate instead |
| R6 | Training from scratch (600 epochs) reaches 20-25 s per merge | 0.13.0 is a fine-tune; this repository does not reproduce 0.9.0 from scratch |

## Housekeeping found while writing these pages

- `STATE_CLIP` and `STATE_NORM` in `merge_constants.py` are not used by any code, and their sign convention is
  inconsistent (the shift is added for some inputs and subtracted for others). The real ranges are in
  `encode_features`, and the table on the [Agent](AGENT.md) page is checked against it by a test.
  The constants should be deleted.
- Nine inherited tests are kept as strict xfail, written against an old interface.
- The governor's escape boost (planned "G2") was never finished. The governor is off by default.

[^strict_xfail]: **Strict xfail.** A test for a known limitation: it keeps its honest assertion, must fail on that assertion, and turns red the day the behaviour changes. Deleting the test or loosening its threshold would hide the limitation. With strict xfail it stays in the suite, next to the code, and it cannot silently start passing or break for another reason. [more](GLOSSARY.md#strict_xfail)
[^kerb_corner]: **Kerb corner.** The point where the bay's exit taper meets the plain kerb. It points into the road. If the bus steers out too slowly from the far end of the bay, this corner cuts into the bus's side. The checker first missed it, because it compared only the four body corners with the road edge. Now the kerb corners are tested against the body too. [more](GLOSSARY.md#kerb_corner)
[^jerk]: **Jerk.** The rate of change of acceleration, in m/s³. A real brake needs time to build up force, so jerk is bounded. The test suite checks that jerk stays within bounds. One known limitation is that braking can start with a jerk of about 100 m/s³, where a real brake system gives 30 - 60 (see the limitations page). [more](GLOSSARY.md#jerk)
