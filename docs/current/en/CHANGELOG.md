# Changelog

Every notable change to the simulation and to the brains, newest first, with the commit that made it. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). The identifiers in brackets (P7, H16, O21, …) are the entries of the full
issue list, `docs/reference/BUGS.md`, which gives the evidence for each.

## Versioning

**Two things are versioned separately**, because a brain is trained on one version of the world and can stop working
when the world changes.

| | Simulation (the `busmerge` package) | Brain (the trained driver) |
|---|---|---|
| Form | MAJOR.MINOR.PATCH | MAJOR.MINOR.PATCH |
| MAJOR | a change to the physics or the interface that makes earlier results or brains invalid | 0 until a brain passes every acceptance criterion; then 1 |
| MINOR | new behaviour that keeps earlier results valid | a new training run (retraining or fine-tuning) or a new network architecture |
| PATCH | a fix, test or document that changes no behaviour | a re-export or fix that does not change the brain's decisions |
| Current | **1.0.1** | **0.13.0** |

Before 1.0.0 the simulation was in initial development (0.y.z), when, by the rules of semantic versioning, anything may
change; the physics did change a lot. Brain versions keep the number of their training run, so v13 became 0.13.0; the
model files keep their original names (`models/ppo_bus_brain_v13.pth`). Release tags take the form `v1.0.1`.

## [Unreleased]

### Added
- **The stop-design experiment** (`feature/stop-experiment`): an opt-in schedule of arrivals that gives both designs the same
  cars and loses none (`fa5ee4c`), a runner and an analysis, and 15,000 measured runs with stops of 10 to 45 s
  (`70a44a9`, `e0a9e63`). When released this is a minor version of the simulation, 1.1.0.
- **A second experiment with short stops** of 0, 3 and 6 s: 4,500 runs on the same seeds, so they pair with the first.
  It was first measured with uncommitted changes and then run again from the clean commit `c4894bc`; every run and
  every trip came out identical. The two are summarised together in `results/experiments/stop_design/combined.json`
  (`81acf6f`).
- **The comparison with published field data** (`2c675a8`, `055c198`, `e6969f5`) and **the interactive explorer**
  (`61b9afd`, `70327ff`, `b2b92d2`, `9ea2f67`): choose the traffic, the occupancies, the stop times and the accuracy
  penalties, and see which design wins.
- **The results as three tabs**, [Measurements and research](EXPLORER.md) (the tool, with the measurements below it),
  [Conclusions](RESULTS.md) and Field data, in both languages (`81acf6f`, `c4894bc`), with our conclusion: in Israeli cities, where stops are short, a stop in the lane is better. The
  conclusion states the assumption it rests on (stops of up to about 12 s, by scattered measurements made for building
  this project) and keeps the Israeli guidelines as the only direct support; the sources from elsewhere are given as
  inspiration and comparison.
- A third version of the documentation, in English and Hebrew: a research question, separate pages for the world and
  the agent, this changelog, and a GitHub-ready Markdown export.
- A GIF of the in-lane stop (scenario A), next to the bay.

### Changed
- The app's default occupancies are 1.35 people per car and 20 passengers per bus (were 1.2 and 50), and the app says
  it is for illustration only; the results come from the experiment. The occupancies affect only the KPIs the app
  shows.
- No page assumes a fixed bus load; a test checks six pages for it.
- The golden tests compare a sample of each run within 0.001 instead of an exact hash, which differed on GitHub's
  machine only in the last bit of a float (the steps, rewards and final positions were identical). Regenerated from the
  same code; no behaviour changed.
- The GitHub version of every page starts and ends with the tabs, and the repository's front page is the current
  overview.

## [1.0.1] - 2026-10-25

### Added
- Strict-xfail tests that pin two limitations: the cars' steering overshoot (O21) and the side effects of the IDM
  functions (O22) (`d1bfad5`).

### Changed
- Documented O21 and O22, found while researching a multi-lane extension, and the measurement that the cars'
  steering law, not lane drift, causes most of the cars crossing the centre line (`5ef0459`).

## [1.0.0] - 2026-10-22

The first public release: the physics, the brain 0.13.0, the generated results, the tests and the documentation.
Tagged `v1.0-stable` (`fb2b067`).

### Added
- Every published number generated from stored per-seed measurements in `results/`; a test fails if a page differs
  (H16, `5a913a1`).
- Automated tests for behaviour, steering, physics under any policy, single sources, reward terms, training
  safety, env/engine parity, PPO ratio, determinism, property-based tests of the safe-speed law, the scheduled gates
  (`e3de4c8`, `5a913a1`, `73c014a`, `4f95bdd`).
- Documentation: README, bilingual QA summary, the merge GIF (`2e47598`); a styled HTML site (`ac7f2c9`); a bilingual
  test report (`27401c0`); the second documentation version with expandable technical notes (`b0fe264`, `fb2b067`).

### Fixed
- The app showed no outcome when the bus left the road or crossed the centre line (H15, `5a913a1`).
- The merge-zone view ran to the end of the traffic instead of ending when the bus left it; the governor panel listed
  "disabled" frames as decisions; the control label said "PPO + Governor" with the governor off (H17, H18, H19,
  `26b969c`).
- 151,000 deprecation warnings per test run from the geometry code (`32790fa`).

## [0.4.0] - 2026-10-10

Honest geometry and steering. This release made every earlier brain stop working (see the
[case study](CASE_STUDY.md)).

### Added
- Brain **0.13.0**, fine-tuned under the corrected steering: 97.8% merged on 1,000 unseen runs (`d49dc0c`).
- Checks of the road edges, the centre line and extreme headings, replacing the clamps (P10, `7b59caf`).

### Changed
- The merge counts as complete at -0.25 m (the whole bus inside the lane), the project owner's decision (`d49dc0c`).
- Acceptance limits: mean merge time ≤ 15 s, 95th percentile ≤ 20 s (`fbe2f3e`).

### Fixed
- The bus crossed the centre line in 100% of runs: the merge steering had no heading term and overshot every target.
  It now uses pure pursuit (P11, `4ff0fd8`).
- The bus cut the kerb when pulling in (47% of runs), could stop past the bay, and the bay was drawn in three
  different ways (P12, P13, P15, `4ff0fd8`).
- The checker could miss a kerb corner cutting into the side of the bus (P14, `4ff0fd8`).
- 14.6% of training start poses were off the road; the PPO buffer was biased against the action at the limit
  (P16, P17, `b0aa46b`).
- The rollback rule reset every fine-tune that started without a success to its starting weights (P18, `d49dc0c`,
  `5a913a1`).

### Removed
- Six clamps on the positions and headings of the bus and the cars (P10, `7b59caf`).

## [0.3.0] - 2026-10-10

Strict physics: nothing is assigned.

### Added
- The physics checker: braking, acceleration, speed, backward motion, position jumps, overlaps (`bdcef50`), in every
  gate and in the app (`d81b69f`).
- One safe-speed law limiting every follower's acceleration (P7, P8, `ea0f727`).

### Fixed
- The bus stopped in the bay from about 5 m/s to 0 in one frame (-50 m/s²); it now brakes to its stop point by
  physics (P3, `c05b885`, `b3a75ce`).
- Cars braked at 16-24 m/s² right after appearing; they now enter at a speed they can brake from (P4, `ff4e54b`).
- Drawings and crash tests were shifted half a vehicle ahead of the physics (P2, `eadf451`).
- A bus touching a car's side counted as merged (H12, `eeba728`); training and the acceptance gate judged collisions
  differently (H13, `973facd`).
- A false "accel paradox" alarm on the frame a car stopped (H11, `48225ad`).
- The smoke test's "maximum wait" measured the clock, not the wait (H14, `fea1d7c`).

### Removed
- The "Hand of God" corrections: speed caps, position trims, frozen stops (P7, `ea0f727`; the old code is at the tag
  `legacy-hand-of-god`).

## [0.2.0] - 2026-10-06

One world.

### Added
- Brain **0.11.0**, fine-tuned on the unified environment (`2578bad`).
- The acceptance script (`1a2f94b`).

### Changed
- The training environment runs the app's engine; one observation builder for both (P1, `95d1a4f`, `f7d29c4`; the
  old two-engine code is at the tag `legacy-dual-physics`).
- One harness runs and judges every episode for the app, the smoke test and the scripts (H3, `38c7bf3`).

### Fixed
- "Merged in -36 s" in the app (H2, `38c7bf3`); "9 of 30" validation caused by a crash rule that counted a car passing
  the bay (H4, `38c7bf3`).
- In-training evaluation without the run's flags, checkpoints that could not be reproduced, wrong feature labels,
  silent restarts from random weights (H5-H8, `4e3fa7b`); a random network when a checkpoint was missing (H9,
  `29a06e0`); identical runs for different seeds (H10, `d0de39c`).

## [0.1.0] - 2026-10-04

The original project imported as a package, with a regression test that fingerprints fixed-seed runs (`d96b8b3`).

## Before 0.1.0: the original repository

The project was developed for nine months in a separate repository, `bus_simulation`. Its notes record the problems
solved on the way; the numbers below are quoted from them and were not re-measured. Hashes refer to that repository;
where a fix was never committed on its own it is marked *notes*.

| Date | Change | Commit |
|---|---|---|
| 2026-03-30 | A shield deadlock (bus and car both frozen, 4,910 emergency stops in 240 episodes) resolved; a deterministic crash traced to a shield rule that fired too late | *notes* |
| 2026-05-20 | Bus heading no longer overwritten by the car steering routine | `10638cd` |
| 2026-05-20 | Bus drawn at its real lateral position, not 1 m off | `29ec116` |
| 2026-05-26/27 | Six differences between training and the app fixed: speed constant, governor retreat, initial heading, traffic speeds, cars that yielded only in training, a free "hold" exploit | probably `3ed9baf` |
| 2026-06-02 | The checkpoint selector no longer promotes a policy with 0 successes; the app gets a "Validate brain" smoke test | `7814c46` |
| 2026-06 to 07 | IDM yielding reworked; four "teleport" mechanisms fixed one by one (each fix exposed the next) | snapshot `79972f5` |
| 2026-07-02 | Brain 0.9.0 frozen as the default; experimental 0.10.0 | `db523bf`, `0961c6c` |
| 2026-07-26 to 08-13 | A documentation audit against the code; three bugs it found fixed (a shield lunge overriding a governor hold, a dead reward curriculum, a reward dead zone for small overlaps) | `c3c0c72`, `dd1cc15`, `e4c18e5` |

The patterns these share (two copies of one thing drifting apart; corrections hiding failures; fixing symptoms instead
of causes) shaped the rules of this repository: one definition of everything, no hidden corrections, and every
number generated and tested.
