[Overview](README.md) · **Research question** · [Measurements and research](EXPLORER.md) · [Conclusions](RESULTS.md) · [Field data](FIELD_DATA.md) · [World model](WORLD.md) · [Agent](AGENT.md) · [Case study](CASE_STUDY.md) · [Changelog](CHANGELOG.md) · [Testing](TESTING.md) · [Limitations](LIMITATIONS.md) · [Glossary](GLOSSARY.md) · [עברית](../he/RESEARCH.md)

# Research question

> **Status: two experiments have run (19,500 runs).** This page states the question and describes how it was
> answered. The measurements, with a tool to try other conditions, are in [Measurements and research](EXPLORER.md); the
> check against the field in [Field data](FIELD_DATA.md); and the conclusion in [Conclusions](RESULTS.md).

## The question

**On a single-lane urban road, does a bus stop in a bay or in the travel lane move more people to their destination
faster?**

The unit is the person, not the vehicle. A design that saves a bus 20 seconds saves 20 s for every passenger on board;
a design that delays every car behind the bus by 20 seconds costs 20 s for every person in those cars. Both groups count,
and how many people each carries is the reader's choice, not the simulation's.

## Why it is not obvious

| | Bay stop | In-lane stop |
|---|---|---|
| Cars behind the bus | keep moving while passengers board | wait until boarding ends: a queue forms |
| The bus after boarding | must find a gap and merge back; traffic decides how long that takes | leaves at once |
| Stopping | the bus follows the bay's kerb and stops within a range of positions | the bus stops in its lane, at the kerb |
| Boarding time | may be longer if the bus stops away from the kerb or the doors | may be shorter: the stop is precise |
| Risk | the merge: contact with a car alongside, the bay's exit kerb | a car changing lanes around the bus (not modelled: one lane) |

Neither column wins everywhere. A bay spares the cars the queue but costs the bus the merge; a stop in the lane spares
the bus the merge but holds up everyone behind it. Both costs grow with the traffic, and the queue's cost grows with
the stop time too. Where the balance tips is the question.

## What was measured

For every pair of runs (the same seed, once with a bay and once in the lane):

- **a**, how many seconds longer the bus's trip is with a bay, and **b**, how many vehicle-seconds longer all the cars'
  trips together are with a bay. Each vehicle's trip is timed from the moment it was due to enter the road until it
  leaves at the far end, so waiting at the entry counts.
- **The primary measure**, the difference in person-time[^person_time]: `ΔPT = bus passengers × a + people per car × b`.
  Below zero, the bay is better. From it comes the tipping point[^break_even]: the bus load at which the two designs
  are equal.
- **The queue** behind a bus stopped in the lane, and the wait at the road's entry.
- **The merge** at the bay: from the end of boarding until the bus has merged[^merged].
- **Safety**: contacts, kerb strikes and other physics violations[^invariants] in every run, and runs that did not
  finish in time.

## What was varied

The table gives what the experiments actually ran. The original plan had other ranges; they were replaced once it
was clear what is realistic.

| Factor | Range | Why |
|---|---|---|
| Stop design | bay (scenario B), in lane (scenario A) | the question |
| Traffic inflow | 0.1 to 0.5 cars/s requested | the main driver of both costs. 0.5 is above the capacity of one lane, about 0.43 |
| Stop time | 0, 3, 6, 10, 15, 20, 30 and 45 s, for each design | measured for every pair of lane time and bay time, so the [explorer](EXPLORER.md) lets you choose them separately |
| People per car | chosen at analysis time; 1.2 to 1.5 in Israel, 1.35 where one value is needed | a weight only, not part of the run |
| Bus passengers | chosen at analysis time, with no fixed value | a weight only, not part of the run. The verdict is especially sensitive to it, so there is no single default |

## How it was run

- **Paired comparisons[^paired].** For a given seed both designs get exactly the same cars: the same arrival times,
  sizes and desired speeds. Arrivals have their own random generator, so they do not depend on what happens on the
  road, and the difference is measured on identical traffic.
- **Reserved seeds** 4000 to 4299, never used for training, brain selection or the published results. The first
  experiment (stops of 10 to 45 s) has 300 pairs per combination; the second (0 to 6 s) has 150 pairs, on seeds 4000 to
  4149, so the runs of the two experiments pair with each other.
- **A 95% confidence interval** for the mean of every cell, by the normal approximation. A cell is decided for a design
  only when the whole interval is on one side of zero.
- **No arrivals are lost.** Cars arrive on a schedule (Poisson) during the first 150 s. A car that finds the entry
  blocked waits, and the run goes on until every vehicle has left (a cap of 900 s, which no run reached).
- **Occupancies are not part of the run.** The simulation measures times only; the people in each vehicle are chosen at
  analysis time, so the same runs answer for any occupancy.

The full design, with the data dictionary and the commands to run it again, is in
`docs/reference/EXPERIMENT_STOP_DESIGN.md`.

## What was handled before the experiment, and what was not

- **Traffic arrivals (limitation O20).** *Handled in the experiment:* a car that finds the entry blocked waits instead
  of being lost, so "heavy" traffic is heavy. The app's arrival model still loses them.
- **Paired arrivals.** *Handled:* arrivals have their own random generator, so a seed produces the same traffic in both
  designs.
- **The in-lane scenario (O5, O7).** *Not fixed:* it still resets the bus's pose at the stop, and both experiments ran
  with it. The reset is lateral only and leaves the position along the road unchanged ([world model](WORLD.md#scenarios)).
- **Cars' steering (O21).** *Not fixed:* cars overshoot when they move aside for the bus. With a queue behind an in-lane
  stop that matters less, at a bay more; how much it changes the trip times we have not measured.

## Model limitations

- One lane, one stop, one bus; no buses in sequence, no traffic lights.
- No vehicle mass (a bus brakes like a car) and no brake lag ([limitations](LIMITATIONS.md) O17, O18).
- The driver is good but not perfect: 2.3% of its pull-outs in the experiment ended in contact.\*
- Arrivals are synthetic (Poisson), not counted from a real street.
- The stop time is fixed in every run; on the street it varies.
- The conclusion rests on the assumption that Israeli city stops are short, up to about 12 s, by scattered
  measurements made for building this project ([our conclusion](RESULTS.md#our-conclusion)).

\* Real streets have crashes when buses leave a bay too. For simplicity the model does not put a cost on them: a run that
ended in contact counts like any other. Leaving those runs out changes the bus's delay by at most 0.4 s in
any cell.

[^person_time]: **Person-time.** How long all the people in the vehicles travelled: each vehicle's trip time times the people in it, summed. The stop experiment compares the two designs on person-time, not vehicle-time, because a bus carries many people and a car one or two. [more](GLOSSARY.md#person_time)
[^break_even]: **Tipping point.** The number of bus passengers at which a bay and an in-lane stop are equal. With fewer passengers the bay is better, with more the lane. A cell where the lane wins at any load has no tipping point ("lane always"). [more](GLOSSARY.md#break_even)
[^merged]: **Merged.** The bus is wholly in the lane (lateral position at least -0.25 m). Judged on traffic only. "Merged" says nothing about the road edges: a merged bus may still have left the road on the way. That is what [strict success](GLOSSARY.md#strict) adds. [more](GLOSSARY.md#merged)
[^invariants]: **Invariants (physics checks).** Checks run on every simulated run for moments that cannot happen in reality. A run is not judged only by its outcome. `busmerge/invariants.py` goes over the whole frame log and reports every impossible moment. Cars crossing the centre line or the kerb are reported but not failed (mostly the overshoot of their steering law when they move over for the bus, limitation O21). [more](GLOSSARY.md#invariants)
[^paired]: **Paired runs.** Two runs, one for each stop design, with exactly the same cars. For one seed, the bay run and the in-lane run get the same arrival times, and every car the same class, size and desired speed (common random numbers). Any difference between the two is then due to the stop, not to the luck of the draw, and far fewer runs are needed for a tight interval than with independent runs. [more](GLOSSARY.md#paired)

---

[Overview](README.md) · **Research question** · [Measurements and research](EXPLORER.md) · [Conclusions](RESULTS.md) · [Field data](FIELD_DATA.md) · [World model](WORLD.md) · [Agent](AGENT.md) · [Case study](CASE_STUDY.md) · [Changelog](CHANGELOG.md) · [Testing](TESTING.md) · [Limitations](LIMITATIONS.md) · [Glossary](GLOSSARY.md) · [עברית](../he/RESEARCH.md)
