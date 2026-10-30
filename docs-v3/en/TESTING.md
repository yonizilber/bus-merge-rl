# Testing

## Status

{{test_totals}} That is **0 unknown failures**: every test that does not pass is either an accepted, documented
limitation or deliberately not run on every push. The [test report](TEST_REPORT.html) lists every test case with its
result, from that one real run.

| Result | Count | What it means |
|---|---|---|
| Passed | 370 | The behaviour is as required |
| Expected failure (strict xfail) | 22 | **13 known limitations** of the simulation or the brain, each a test that keeps the correct requirement and fails on it today (listed [below](#known-limitations-as-tests)), and **9 legacy tests** inherited from the original project, written against an interface that no longer exists |
| Skipped | 6 | **5 statistical gates** that take 10-20 minutes and run as a [scheduled job](#when-the-tests-run), and **1 test that never reaches its check** (see future work) |
| Failed | 0 | |

A [[strict_xfail|strict xfail]] is a test for a known limitation: it must fail on its assertion, and it turns red the
day the behaviour changes, so a limitation can neither be hidden nor be fixed without anyone noticing.

**Future work.**
- Rewrite or delete the 9 legacy tests.
- Fix the test that always skips: `test_follower_telemetry.py` runs 200 steps, which end before the bus merges, so it
  never has a trace to check.
- Add tests for the limitations that have none yet: O11 (the bus turns about its centre), O15 (the merge criterion
  for a tilted bus), O16 (the pull-in steering at speed).

## When the tests run

| When | What runs | Blocking? |
|---|---|---|
| Every push and every pull request (GitHub Actions, `ci.yml`) | `ruff` and the whole suite except the statistical gates, about 2 minutes | **Yes**: a pull request is merged into `main` only when this passes |
| Scheduled job, daily at 02:00 UTC, and on demand (`nightly.yml`, `cron` and `workflow_dispatch`) | the 5 statistical gates: the default brain on 400 runs over unseen seeds | No; they guard against slow drift, and run before every release |
| Before a release | the acceptance gate and a 1,000-seed verification for every published number | Yes, by rule |

**The development rule.** `main` is protected: work happens on a feature branch, reaches `main` only through a pull
request, and a pull request is merged only when CI is green. What blocks a merge:
- any failing test or lint error;
- a strict xfail that starts to pass (it means a limitation changed: update the test and the documentation);
- any new test that fails without a documented reason.

What is accepted: the 22 strict xfails, each linked to an entry in `docs/BUGS.md`, and the 6 skips above.

The workflows exist in `.github/workflows/`. Branch protection (the "required status check") is a repository setting
that is switched on when the repository is published.

## What is tested

| Area | What is checked | Examples |
|---|---|---|
| Physical limits | The [[invariants|invariants]]: deceleration up to 9 m/s², acceleration up to 5 m/s², no negative speed, no backward motion, no position jump, no overlap, the road edges, the centre line, heading | Every steering update in a real run (over 5,000) respects the bicycle model; a random or extreme driver never produces an impossible moment; a sweep from 0.2 to 0.8 cars/s |
| The safe-speed law | [[property_test|Property-based]] tests over thousands of generated cases | It never brakes beyond the limit, never closes more than the gap in one step, never into contact |
| Geometry | The road-edge check against a brute-force walk of the outline at 1 cm resolution | 3,000 random poses at the tapers |
| Steering | [[pure_pursuit|Pure pursuit]] converges without overshoot; the cars' law does not (O21) | 56 cases; the old overshooting law is shown to fail |
| Training pipeline | The training environment matches the app engine bit for bit; the PPO ratio is 1 before the first update; the [[rollback|rollback rule]] never restores starting weights; a two-epoch training run end to end; every reward term by its formula; the reward ranks a full merge above stopping half way; a checkpoint survives saving and loading | A drift of 1e-9 m/s is caught; the old clipped-action buffer and the old rollback rule are shown to fail |
| Agent behaviour | The default brain in constructed situations | It merges within 15 s from every metre of the stop range and never stalls half way (0.11.0's exploit is caught) |
| Determinism | The same seed gives the same run, with noise enabled | The app and the training environment produce identical runs |
| The app | A headless Streamlit run | It loads, offers exactly the brains that exist, shows the published table, and for a fixed seed shows the outcome the harness measured |
| Published numbers | Summaries recomputed from the per-seed rows; every generated block checked | A one-point change is caught |
| Documentation | Every page builds, no link is broken, the two languages stay separate | |

Every check is accompanied by proof that it can fail: the steering test is run against the old controller, the stall
test against brain 0.11.0, the parity test against an injected drift, the single-source scan against a planted copy.

## Known limitations as tests

| Limitation | Tracked by | ID |
|---|---|---|
| The agent sometimes pulls out while a car is alongside (about 2% of runs) | `test_brain_behaviour.py` | O2 |
| From the far end of the bay the agent steers out too slowly and clips the exit kerb (about 9%) | `test_brain_behaviour.py` (2 placements) | O12 |
| The stopped bus's speed is set to 0; scenario A resets the bus pose | `test_no_state_assignment.py` | O5, O7 |
| **No vehicle mass:** a bus brakes as hard as a compact car | `test_physics_limits.py` | O17 |
| **No brake actuation lag:** a jerk of up to about 107 m/s³ | `test_physics_limits.py` | O18 |
| The safe-speed law can intrude up to 0.55 m into the 2 m minimum gap, never into contact | `test_safe_speed_properties.py` | O19 |
| The car generator loses arrivals: about 71% of the requested inflow is delivered at the default | `test_traffic_density.py` (4 densities) | O20 |
| **The cars' steering law overshoots:** a 0.5 m nudge overshoots by about 100% and never settles | `test_car_steering_controller.py` | O21 |
| **The IDM functions change the vehicle's state:** a second identical query gets another answer | `test_idm_query_side_effects.py` | O22 |

Each is explained in plain words on the [Limitations](LIMITATIONS.md) page.

## Seed sets

Random seeds are kept in separate ranges so that no number is measured on data it was tuned on: 1000-1099 to choose
between candidate brains, 2000-2999 for the published numbers, 3000-3249 for the scheduled gates.

## Running the tests

```bash
pip install -e ".[dev]"
ruff check . && pytest -q               # what CI runs on every push
pytest --nightly -m nightly             # the scheduled statistical gates
python scripts/build_test_report.py     # run everything and write the test report
```
