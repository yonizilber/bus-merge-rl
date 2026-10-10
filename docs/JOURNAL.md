# Engineering journal

A dated record of the work on this repository since it was split out of the original
development repository (`bus_simulation`) on 2026-10-04: what was done, why, and what the
measurements showed. Design details live in [SPECS.md](SPECS.md), every bug with its evidence in
[BUGS.md](BUGS.md), and open work in [ROADMAP.md](ROADMAP.md).

Two working rules were set during this period and shape everything below:

1. **One harness.** Every number is produced by the same code path the Streamlit app runs. If a test,
   a smoke check and the app disagree, that is a bug to fix immediately, not a known issue.
2. **No silent corrections.** The simulation may not fix an impossible state by assigning a speed or a
   position. Either it is real physics, or it is recorded as a violation and fails a check. A brain
   that visibly fails is preferred to one whose success depends on the simulation cheating.

---

## 2026-10-04: review, backup, new repository

**Review of the original repository.**
- **The committed code did not run.** Five core modules (`feature_encoding`, `merge_yield`,
  `traffic_leaders`, `queue_analytics`, `crash_replay`) and 11 test files had never been committed.
  `app.py` imported a `PhysicsMode` that existed only in uncommitted changes.
- **Tests:** 114 passed and 9 failed, all of them legacy tests written against an old API.
- **The public GitHub repository** held only an old branch, 29 commits behind, with a 14 MB slide deck, a
  Word file and a pickled legacy model.
- **Code quality:** the main weakness was that the physics was written twice, once for the app engine
  and once for the training environment. Other issues: 1,800-line `app.py`, `sys.path` hacks, dead
  code, magic numbers.

**Safety first.** Full archive of the old folder. All uncommitted work was committed to a local
`snapshot/pre-publish` branch; a clean export of it then passed the same tests and ran the app headlessly.

**New repository.**
- **Package and imports:** a `busmerge` package with only the live code. Imports were rewritten, and
  every `sys.path` hack and `try/except ImportError` fallback was removed.
- **Paths:** resolved through `busmerge/paths.py`, no longer relative to the working directory.
- **Tooling:** `pyproject`, MIT licence, CI (ruff + pytest on CPU-only torch).
- **Golden-run test:** five fixed-seed simulations fingerprinted from the old code reproduced
  **exactly** in the new layout. This proved the move changed nothing.

**First bug seen in the running app:** "Bus merged in -36 s". The merge-completion search started
before the bus entered the bay, and the bus starts in the lane at progress 1.0.

## 2026-10-05: one harness for every number

**The rule.** The user ruled that test/app inconsistencies are bugs. The investigation found that the
smoke test, the smoke button, the validation demo and the app each had their own episode loop, their
own traffic settings and their own definition of "merged" and "collision".
- **One harness:** `busmerge/evaluation.py` (`run_episode`, `classify_outcome`) became the only
  implementation, and the negative merge time disappeared.
- **Merge-time breakdown:** `merge_timeline` splits the time from end of boarding to fully merged into
  hesitation, leaving the bay, entering the lane and settling.

**The unexplained "9/30" validation score was a bug in the training environment, not in the brain.**
- Its legacy 1-D crash rule read `presence_factor`, which has a 0.15 floor while the bus waits in the
  bay. So a car merely passing the bay counted as a crash.
- The validation demo also built the environment without the reward flags the checkpoint was trained
  with.

**Small app fixes:** failure banners chained to the wrong `if`; a missing checkpoint silently running a
random network; a preset that did nothing; the GIF written to a shared file; the dashboard reading the
current sidebar instead of the run's settings.

**Experiment: train on the production engine.**
- **`EngineEnv`:** keeps the training environment's scenarios and reward but steps the world with
  `SimulationEngine`. It trained stably at about 16% more wall time.
- **Training-tool bugs found on the way:**
  - the in-training evaluation lacked the run's reward flags, so every checkpoint scored 0/30 and
    best-checkpoint selection did not work
  - `scripts/train.py` could not reproduce the shipped checkpoints (no `--disable-governor`)
  - the brains labelled "7-feat" are 11-feature networks
  - a feature-count mismatch silently restarted training from random weights

## 2026-10-06: unifying the physics (plan U0-U7)

- **U0, baseline:** v9 and v10 measured on 100 seeds. The acceptance thresholds were fixed from these
  numbers before any new brain existed: all merged (≥ 98 with noise), no collision, mean time after
  boarding ≤ 6.0 s, p95 ≤ 7.0 s.
- **U1, one observation:** a single observation builder, `build_observation`, now serves both the engine
  and the environment. Golden tests stayed bit-identical.
- **U2+U3, one environment:** `BusMergeEnv` became a training wrapper around `SimulationEngine.step`, with
  no physics of its own. Success uses the app's rule. The legacy implementation is kept at the tag
  `legacy-dual-physics` and in an archive outside the repository.
- **Training seeds:** `--seed` was added. A bug made two seeds produce identical runs, because the
  in-training evaluation re-seeded the RNGs; it is fixed by re-seeding every epoch.
- **v11:** v9 fine-tuned for 300 epochs on the unified environment.
  - **Passed acceptance on 100 unseen seeds:** 100/100 merged, mean 4.6 s, p95 4.9 s. On the same
    seeds, v9 had a p95 of 9.4 s and 97/100 merged with noise, so v9 did not meet its own bar.
  - **Training from scratch** for 600 epochs did not reach this level (20-25 s).

## 2026-10-07: "Accel Paradox" → physical-invariant checks

**The user saw an "Accel Paradox" warning in the app.**
- **The detector:** it flagged the frame in which a braking car comes to rest. That was a false positive,
  fixed.
- **The real problem:** a follower speed cap (the "Hand of God") cut speeds by up to 2.4 m/s per frame
  while the driver model asked for far less.

**`busmerge/invariants.py`.** Counts physically impossible moments in a frame log: braking beyond
9 m/s², backward motion, position not following from speed, polygon overlap. Every run contained
impossible braking, from three sources:
- the bus snapping to a stop in the bay (-50 m/s²)
- cars created too fast for the car ahead
- the follower cap

Simply disabling the cap made things worse, because other code then zeroed speeds after movement.

**A second convention bug.** The physics treats `x` as the front bumper, while the app drawing, the GIF,
the renderer and the training crash test treated it as the centre. Every vehicle was drawn and judged
half a length ahead of its physical position.

## 2026-10-08: physical correctness, Part 1 + root fixes A, B, prototype C

**An external critique of the plan was answered with data.**
- **Claim:** the -51 m/s² was traffic being "saved". **Measured:** it was the bus parking.
- **Claim:** removing the cap would collapse the brain. **Measured:** v11 made no overlaps even with the cap off.

The agreed path: Part 1 now, A and B now, C as a time-boxed prototype behind a flag.

**Part 1.**
- **One position convention everywhere**, through `busmerge/geometry.py`.
- **Physics checks in every gate:** acceptance, the smoke test, and a banner after every app run.
- **First result:** a real 0.24 m² bus-car overlap lasting about 2 s, which the old convention had hidden.

**A: the bus stops by physics.** `Bus.bay_stop_acceleration` brakes exactly as hard as needed (v²/2d),
finishes its alignment at crawl speed, and never exceeds 9 m/s².
- **Removed:** the speed snap, two crawl floors, the bay-end clamp and the pose reset at the start of the
  merge.
- **Measured:** worst bus braking -2.0 m/s² (was -50). The bus now arrives about 7 s later.

**B: safe arrivals.** A car enters at a speed from which it can stop behind the car ahead. Arrivals that
do not fit are delayed, not dropped.
- **First attempt:** used the leader-speed formula and made things worse, because the existing cap
  assumes a stationary leader.
- **Final version:** 0 violations at creation, down from 551 and 955 frames. Traffic flow changed by
  only +1-2%, verified with the new traffic metrics.

**C: strict physics prototype.** `busmerge/safe_speed.py` replaces the cap, the position trims and the
stop-holds with one safe-speed limit on acceleration, behind `SimConfig.strict_physics`. Measured with
v11 on 100 unseen seeds:

| | strict physics | default physics |
|---|---|---|
| runs with impossible physics | 0 | 68 |
| merged | 100/100 | 100/100 |
| car jerk | lower | — |
| runs with bus-car contact | 2 (up to 0.12 m²) | — |

The 2 contacts are real brain mistakes that the cap used to hide: pulling out while a car is alongside.
Side contact now also counts as a collision in `classify_outcome`.

## 2026-10-09: code review of the changes, judge fixes, fine-tune

**A code review before spending compute found that the training crash judge disagreed with the
acceptance gate in four ways:**
- it looked at the nearest car only
- it ignored the bus's lane drift
- it treated contact up to 1 m² as a small per-frame penalty
- it judged success before contact

All four were fixed so the training judge and the gate are now the same test.

**A hypothesis was checked rather than assumed.** The suggestion was that the nearest-car-only judge
explained v11's contacts. In the case inspected, the car hit was the nearest car, so the likelier cause
is the weak penalty for small contact plus the old position convention v11 was trained under.

**Also done:**
- unit tests for the safe-speed law
- a slow, still-angled bus can again accelerate to crawl speed

**Fine-tune v12** (v11 on strict physics with the corrected judge, 2 seeds × 300 epochs) **failed
acceptance**, and was no better than v11 measured on the same code.
- **v11** (the fair reference): 98/100 merged, 2 collisions (side contact), 0 physics violations.
- **v12, seed 1:** 3-4 collisions.
- **v12, seed 2:** stayed in the bay in 9-20 runs.
- **During training**, the evaluation never improved (26-28/30). The training signal did not teach the
  brain to wait for a car alongside.
- Details in [TRAINING.md](TRAINING.md).

## 2026-10-10: strict physics adopted

**Decision.** The user chose to adopt strict physics with v11 rather than invest first in training
research. A brain that visibly makes 3 contacts in 100 runs is preferred to a simulation that hides them.

**What changed.**
- **Removed** (state tagged `legacy-hand-of-god`): the follower corrections (`rl/bumper_kinematics.py`),
  `PhysicsMode`, the strict flag, the override telemetry and the app's physics-mode selector.
- **Arrivals** use the same safe-speed law as followers. Traffic flow rose 5-12%, because arrivals are
  no longer throttled as if the car ahead were stationary.

**Tests.**
- Tests of deleted mechanisms were removed.
- Two behavioural tests had expected a car to stop where no car physically can. They now start from
  feasible states.

**One more measurement bug.** The smoke test's "max wait" compared the clock time at which boarding
ended with 45 s. After fix A every brain "failed" it while merging within 6 s. It now measures the
wait after boarding.

**Acceptance on unseen seeds**, merged / contact (noise 0); physics violations other than contact: none.

| Brain | Merged / contact | Mean time |
|---|---|---|
| v11 | 97 / 3 | 4.8 s |
| v10 | 98 / 2 | 5.7 s |
| v9 | 93 / 2, plus 5 stuck | 5.9 s |

## 2026-10-10: verification without clamps, honest bus steering

**RL work halted** (user decision): before publishing, check that the 97% is real.

**Verification of v11 on 1,000 unseen seeds (2000-2999)**, with every position and heading clamp removed
(`7b59caf`) and the road edges checked (`scripts/verify_brain.py`):
- **Judged on the traffic only:** 97.9% merged (95% CI 96.8-98.6%), 2.1% contact.
- **Strict success:** 0%.
  - **Centre line:** the bus crossed it in every run (median 0.84 m, up to 2.34 m).
  - **Kerb:** it cut the kerb while pulling in in 47% of runs.
  - **End of the bay:** it stopped past it in 3%.

**Causes and fixes.** The user chose to fix only the bus. Cars crossing the centre line or the kerb is
driving behaviour, so it is now reported, not failed. Details are in BUGS P11-P15.
- **Merge steering** had no heading term, so it overshot any target. It is now pure pursuit with the
  heading term, the same function as for every other bus state.
- **Pull-in** did not follow the drawn bay. Its target is now read off the drawn road edge under the
  bus's front.
- **Stop range and bay-end limit:** the stop range lets the whole bus fit in the flat part with room
  to steer out, and the stop limit is the real end of the bay.
- **The checker** could miss a kerb corner inside the body side; it now checks for it.
- **The drawn bay** was defined in three places. It now comes from a single `geometry.bay_outline()`.

**The physics allows a clean merge.** A scripted exit (steer for the lane at constant throttle,
ignoring traffic) over 1,500 runs:
- 0 frames off the road and 0 over the centre line
- heading ≤ 11°
- every run merged (median merge distance 33 m)

**Re-measured v11 (same 1,000 seeds):**
- **Merge outcome:** 0% merged, 99.2% stuck, 0.8% contact.
- **Road edges:** off the road in 100% (every case while merging, none while pulling in), over the
  centre line in 0%.
- **No other physics violation.**
- **Cars across a road edge:** 13.7% (was 34.6%).

**Why v11 stopped merging.** v11 commands a lateral target of about -1.5 m, half way out of the bay,
and holds it. In seed 2000, steer 0.06-0.16 maps to a target of -1.46 to -1.69 m. Under the old steering,
that command overshot into a full merge and on over the centre line; v11 had learned to use the defect.
The 97.9% measured the brain together with the defect.
v9 and v10 behave the same way (0/100 merged each, seeds 2000-2099): every brain was trained under
the overshooting steering. The app's brain table now says so.

**Open (user decision).**
- A fine-tune under the fixed dynamics (BUGS O8).
- First, fix the training env's start poses: 14.6% of them put the bus off the road (BUGS O9).

## 2026-10-10 (evening): fine-tune under honest steering, v13

The user chose a time-boxed fine-tune, kept off `main`, with a fallback to documenting the result if it
failed.

**Before training.**
- **Start poses:** checked with the checker's own road-edge function (P16).
- **PPO buffer:** unbiased at the action limit (P17).
- **Reward:** audited by running fixed policies. A full merge earns about 6,700 more than holding half
  way.

**Attempts 1 and 2 failed.** The mean steer at the half-way state (probed on fixed observations) rose,
then fell back to v11's value. The cause was a rollback rule: after 30 epochs without a better
evaluation, training restored the best checkpoint, which for a run starting at 0 successes is its
starting weights (P18). It also rolled the earlier v12 fine-tune back 7-8 times.

**Attempt 3, rollback off.** Four runs of 300 epochs (about 45 minutes): weight 8, 30 and 60 for the
safe-steer term once out of the bay.
- **Weight 30:** got the whole bus into the lane in every run, but stopped at a median of -0.13 m,
  short of the -0.10 m threshold.
- **Weight 8:** stayed half way.
- **Weight 60:** stopped at about -0.3 m.

**Threshold, the user's decision:** -0.25 m, the bus wholly inside the lane. It is one constant used
by the engine, the evaluation and training.

**Selection**, seeds 1000-1099: weight 30 at epoch 300 had 100 merged, 0 contact, 91 strict.

**v13 on the 1,000 unseen seeds:**
- **Merge outcome:** 97.8% merged, 2.2% contact, 0% stuck.
- **Road edges:** 0% over the centre line; 8.7% off the road (exit kerb corner).
- **Strict success:** 89.4%.
- **No other violation.**
- **Time:** mean 13.3 s, p95 16.7 s.

v13 is now the default and the golden-test brain. Its 10-seed smoke test fails: 9/10, with one contact
counted as a physics violation.

**Next:** development frozen; QA and documentation (ROADMAP 1c).

**Later the same evening.**
- **Acceptance limits:** mean 15.0 s and p95 20.0 s (the user's decision).
- **`verify_brain`:** takes `--traffic-rate` and `--cars`, and reports the traffic actually present.
- **Stress test of v13:** 100 unseen seeds at 0.2, 0.4, 0.6 and 0.8 cars/s. Merged 97-99, contact 1-3,
  never stuck, never over the centre line, strict 84-90; the differences are within noise.
- **The arrivals saturate:** at 0.8 cars/s there are only 3.4 cars near the bus, against 2.6 at 0.4.
- **Test strategy:** a coverage summary and a menu of 29 proposed tests are in
  [TEST_STRATEGY.md](TEST_STRATEGY.md), for the user to choose from.
