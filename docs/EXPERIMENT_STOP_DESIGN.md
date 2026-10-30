# Experiment: bus stop in a bay or in the lane

**Status:** design and code ready; the pilot is done (1,000 runs); the full run and its analysis are pending.
**No conclusions yet.**

## Question

On a single-lane urban road, does a bus stop in a **bay** (scenario B: cars pass the stopped bus, the bus must then
merge back, here with the trained brain 0.13.0) or **in the lane** (scenario A: the bus leaves at once, cars queue
behind it) move more people to the end of the road faster?

## Measure

**Person-time** of a run: for every vehicle, its occupancy times its travel time, from its **scheduled arrival** at
the start of the road (so time spent waiting at a blocked entry counts) to its exit at 1,000 m, summed over the bus
and all cars.

**The comparison is paired.** For one seed, both designs get exactly the same cars: the same arrival times, classes,
sizes and desired speeds (common random numbers). The result per seed is

ΔPT = PT(bay) − PT(lane) = pax_bus · (T_bus,bay − T_bus,lane) + pax_car · Σ_cars (T_i,bay − T_i,lane)

**Negative ΔPT: the bay moves people faster.** Free-flow times cancel in the difference, so no reference run without a
bus is needed. Because ΔPT is linear in the occupancies, they are applied at analysis time, and the break-even car
occupancy follows directly: pax_car* = −pax_bus · mean ΔT_bus / mean ΔT_cars.

## Factors

| Factor | Levels | Simulated? |
|---|---|---|
| Stop design | A (in lane), B (bay) | yes |
| Requested traffic inflow | 0.1, 0.2, 0.3, 0.4, 0.5 cars/s (0.5 is above one lane's capacity, about 0.43) | yes |
| Dwell time | 10, 15, 20, 30, 45 s, for both designs | yes; at analysis time any lane dwell can be paired with any bay dwell (a more precise stop in the lane may board faster) |
| Car occupancy | default 1.2; any value | no, a weight |
| Bus occupancy | default 50; any value | no, a weight |

2 designs × 5 inflows × 5 dwell times = 50 cells. Seeds **4000-4999** are reserved for this experiment and used
nowhere else; the pilot uses 20 seeds per cell (1,000 runs), the full run 300 (15,000 runs).

**Why 300.** In the pilot the standard deviation of ΔPT over seeds was 96-466 person-seconds per cell (larger at
higher inflow and longer dwell). With 300 seeds the 95% interval of the mean is then at most about ±53
person-seconds, under one person-minute per run, in every cell, which is what is needed to place the break-even
points; 20 seeds give ±40 to ±200.

## How the runs differ from the app

Only through opt-in settings; with them unset the app, the tests and every published number are unchanged:
- **`SimConfig.arrival_seed`**: car arrivals come from a schedule drawn from their own generator (Poisson at the
  requested rate during the first `arrival_window_s` = 150 s, each car's class and size drawn with it). The rest of
  the run (drivers' reaction times, lane drift, the bus's stop point) keeps using the global random streams, which
  both designs consume differently; that only affects small details.
- **A car that finds the entry blocked waits** and enters as soon as there is room, instead of being lost (on `main`
  arrivals are lost there, BUGS O20). This matters: the queue behind a bus stopped in the lane can reach the entry.
- **The run lasts until every vehicle has left the road** (cap 900 s; a run that hits it is marked censored).

## Running it

```bash
python scripts/run_stop_experiment.py --pilot          # 20 seeds per cell, about 10 minutes on 12 cores
python scripts/run_stop_experiment.py                  # the full run, about 2.5 hours; resumable
python scripts/analyze_stop_experiment.py --pilot      # tables, figures and a report
python scripts/analyze_stop_experiment.py --pax-car 1.4 --pax-bus 35
```

The specification is `experiments/stop_design_v1.json`. The data goes to `outputs/experiments/stop_design_v1[_pilot]/`
(not committed; it can be regenerated from the specification and the commit in `provenance.json`). The analysis
writes `analysis/report.md`, `cells.csv`, `dwell_pairs.csv` and captioned figures next to it; `--publish` stores the
aggregate table in `results/experiments/stop_design_v1/summary.json`.

## Data dictionary

**`runs-*.parquet`**: one row per run.

| Column | Meaning |
|---|---|
| `run` | key `scenario|rate|dwell|seed` |
| `scenario` | `A` (in lane) or `B` (bay) |
| `traffic_rate` | requested inflow, cars/s |
| `dwell_s` | boarding time at the stop, s |
| `seed` | the run's seed (also the arrival seed) |
| `n_cars` | cars scheduled (and run) |
| `sim_time_s` | simulated time when the run ended |
| `censored` | a vehicle was still on the road at the time cap |
| `bus_travel_time_s` | the bus's time from the start of the road to its end |
| `bus_stopped_s` | time the bus spent below 0.5 m/s (boarding included) |
| `cars_travel_time_s` | sum over cars of travel time from scheduled arrival to exit |
| `cars_entry_wait_s`, `max_entry_wait_s` | total and longest wait at a blocked entry |
| `merge_time_s` | bay only: end of boarding to merged |
| `outcome` | bay: `merged`, `collision`, `off_road`, …; lane: `in_lane` |
| `bus_contact`, `bus_off_road`, `bus_over_centre` | bay only: the bus touched a car, left the road, crossed the centre line |
| `violations` | JSON: physics-check counts by kind (`busmerge/invariants.py`) |
| `queue_max_cars`, `queue_max_m` | largest number of stopped cars behind the bus while it stood at the stop, and how far back they reached |

**`trips-*.parquet`**: one row per vehicle and run.

| Column | Meaning |
|---|---|
| `run`, `vehicle_id`, `type`, `class` | the run key; vehicle id (999 is the bus); `Car` or `Bus`; car class |
| `scheduled_t`, `entered_t`, `exit_t` | arrival time on the schedule, time it entered the road, time it left at 1,000 m (s) |
| `travel_time_s` | `exit_t − scheduled_t` |
| `entry_wait_s` | `entered_t − scheduled_t` |
| `stopped_s` | time spent below 0.5 m/s |
| `free_flow_s` | road length / desired speed: a reference for absolute delay |
| `censored` | did not leave the road before the cap |

## Caveats

- The bay's driver is brain 0.13.0: about 2% of its pull-outs end in contact and about 9% clip the exit kerb. The
  analysis reports both and a sensitivity without contact runs.
- Scenario A still sets the bus's speed to 0 at the stop and resets its pose (BUGS O5, O7): an assignment within the
  physical limit, with no expected effect on travel times.
- Cars' steering overshoots (O21); it moves cars sideways, not along the road, so travel times are not expected to
  depend on it.
- No vehicle mass and no brake lag (O17, O18); synthetic Poisson arrivals; one lane, one stop, one bus, which enters
  an empty road at time 0.
