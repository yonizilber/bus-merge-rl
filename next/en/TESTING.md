# Testing

This project treats testing as part of the result. A number is only worth publishing if the same code that the
app runs produced it, and if a test would have caught it going wrong.

{{test_totals}} The [test report](TEST_REPORT.html) lists every test case with its result, taken from one real
run.

## Principles

- **One harness for every number.** The app, the test suite, the verification script and the
  [[nightly|nightly gates]] all run the same episode code and judge it the same way. A difference between a test
  and the app counts as a bug, not as a "known issue".
- **No hidden corrections.** Speed and position only follow from acceleration. Every run is checked for moments
  that cannot happen in reality ([[invariants|physics checks]]) instead of having them clamped away. A model that
  fails visibly is better than one that invents.
- **Every guard can fail.** A check is accompanied by a demonstration that it catches the problem it is for: the
  steering test is run against the old overshooting controller, the stall test against v11, the parity test
  against an injected drift, the single-source scan against a planted copy.
- **Known limitations stay visible.** A [[strict_xfail|strict xfail]] test keeps the honest assertion in the
  suite, and turns red the day the behaviour changes.
- **Every published number is generated** from stored per-seed measurements; a test fails if a page differs.

## What is tested

| Area | What is checked | Examples |
|---|---|---|
| Physics limits | The [[invariants|invariants]]: braking up to 9 m/s², acceleration up to 5 m/s², no negative speed, no backward motion, no position jump, no overlap, the road edges, the centre line, heading | Every steering update in a real run (over 5,000) respects the bicycle model and its limits; a random or full-extreme driver produces no impossible moment; a sweep at 0.2-0.8 cars/s |
| The safe-speed law | [[property_test|Property-based]] tests over thousands of generated cases | Never brakes beyond the limit; never closes more than the gap in one step; never into contact |
| Geometry | The road-edge check against a brute-force walk of the outline at 1 cm | 3,000 random poses at the tapers |
| Steering | [[pure_pursuit|Pure pursuit]] converges without overshoot | 56 cases; the old overshooting law is shown to fail |
| Training pipeline | The training environment equals the app engine bit for bit; the PPO ratio is 1 before the first update; the [[rollback|rollback rule]] never restores starting weights; a two-epoch training run end to end; each reward term by its formula; the reward ranks a full merge above stopping half way; a checkpoint survives a save and load; valid start poses | A drift of 1e-9 m/s is caught; the old clipped-action buffer and the old rollback rule are shown to fail |
| Agent behaviour | The default agent in forced situations | Merges within 15 s from every metre of the stop range; never stalls half way (v11's reward hack is caught) |
| Determinism | The same seed gives the same run, with noise on | The app run and the training environment are identical |
| The app | A headless Streamlit run | It loads, offers exactly the brains that exist, shows the published table, and for a fixed seed shows the outcome the harness measured |
| Published numbers | Summaries recomputed from per-seed rows; every generated block checked | A one-point change is caught |
| The docs | Every page builds, no link is broken, the two languages stay separate | |

## Layers

| Layer | When | What it runs |
|---|---|---|
| CI | Every push | Lint and the whole suite, in about 2 minutes |
| [[nightly|Nightly gates]] | Every night on GitHub | The default agent on seeds used nowhere else: 200 at the app defaults, then 50 at each of four traffic inflows |
| [[acceptance|Acceptance gate]] | Before choosing a brain | 100 episodes at noise 0 and 0.15, with the time limits |
| Verification | When a result is published | 1,000 episodes on seeds 2000-2999, with [[wilson|confidence intervals]] |
| In the app | Manually | The banner shows the outcome, the merge-time breakdown and the physics checks of each run |

The seed ranges never overlap: 1000-1099 to choose between candidates, 2000-2999 for the published
numbers, 3000-3249 for the nightly gates.

## Known limitations as tests

There are 11 [[strict_xfail|strict xfail]] cases that document a limitation of the engine or the agent, and 9
inherited from the original project, written against an older interface and kept until they are rewritten.
Each of the 11 cites its entry in the list on the [Limitations](LIMITATIONS.md) page.

| Limitation | Tracked by | ID |
|---|---|---|
| The agent sometimes pulls out while a car is alongside (about 2% of runs) | `test_brain_behaviour.py` | O2 |
| From the far end of the bay the agent steers out too slowly and clips the exit kerb (about 9%) | `test_brain_behaviour.py` (2 placements) | O12 |
| The stopped bus's speed is set to 0; one scenario resets the bus pose | `test_no_state_assignment.py` | O5, O7 |
| **No vehicle mass:** a bus brakes as hard as a compact car | `test_physics_limits.py` | O17 |
| **No brake actuation lag:** a jerk of up to about 107 m/s³ | `test_physics_limits.py` | O18 |
| The safe-speed law can intrude up to 0.55 m into the 2 m minimum gap, never into contact | `test_safe_speed_properties.py` | O19 |
| The car generator loses arrivals: about 71% of the requested inflow is delivered at the default | `test_traffic_density.py` (4 densities) | O20 |

For a limitation that is a list (the state assignments outside the physics), a passing companion test pins
the list exactly, so a new case fails the build.

## Tests as a discovery tool

Writing the tests found real problems, each fixed or documented:
- **O16:** the pull-in steering is unstable for a sudden target step at speed.
- **O19:** the safe-speed law can intrude into its own minimum gap. `hypothesis` found the smallest case.
- **O20:** the car generator loses arrivals, which explained why the stress results were flat.
- **H15:** the app showed no outcome when the bus left the road.
- **P17 and P18:** a PPO buffer bias and a silent rollback, both of which had blocked retraining.

Clicking through the app by hand then found four more (H17-H19 and a layout problem). See the
[history of problems](HISTORY.md).

## Running the tests

```bash
pip install -e ".[dev]"
pytest -p no:cacheprovider -q          # the CI suite
pytest --nightly -m nightly            # the nightly gates
python scripts/build_test_report.py    # run everything and write the test report
```
