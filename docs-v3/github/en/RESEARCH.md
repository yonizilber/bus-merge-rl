# Research question

> **Status: planned.** This page states the question and how it will be answered. It contains no results and no
> conclusions yet; the simulation and the driver described on the other pages are the instrument built for it.

## The question

**On a single-lane urban road, does a bus stop in a bay or in the travel lane move more people to their destination
faster?**

The unit is the person, not the vehicle. A design that saves a bus 20 seconds is worth 50 passengers × 20 s; a
design that delays every car behind the bus by 20 seconds costs 1.2 people × 20 s per car. Both groups count.

## Why it is not obvious

| | Bay stop | In-lane stop |
|---|---|---|
| Cars behind the bus | keep moving while passengers board | wait until boarding ends: a queue forms |
| The bus after boarding | must find a gap and merge back; traffic decides how long that takes | leaves at once |
| Stopping | the bus follows the bay's kerb and stops within a range of positions | the bus stops in its lane, at the kerb |
| Boarding time | may be longer if the bus stops away from the kerb or the doors | may be shorter: the stop is precise |
| Risk | the merge: contact with a car alongside, the bay's exit kerb | a car changing lanes around the bus (not modelled: one lane) |

Neither column wins everywhere. In light traffic a bay costs the bus almost nothing and spares the cars; in heavy
traffic the merge can take long, while the queue behind an in-lane stop grows with the inflow. Where the balance tips
is the question.

## What will be measured

- **Total person delay** (primary): for every person, car occupants and bus passengers alike, the travel time through
  the road section minus the time at free-flow speed, summed. Lower is better.
- **Person-weighted average speed** and **people delivered** per hour. The simulation already computes both
  (`AnalyticsEngine.compute_kpis`, weighting each vehicle by its occupancy).
- **Bus delay**: from the end of boarding to back at speed in the lane (the merge[^merged] time, for the bay).
- **Queue** behind the bus: length and duration.
- **Safety**: contacts and other physics violations[^invariants] per stop.

## What will be varied

| Factor | Range | Why |
|---|---|---|
| Stop design | bay (scenario B), in lane (scenario A) | the question |
| Traffic inflow | 0.2 - 0.8 cars/s requested | the main driver of both costs |
| Boarding time | 10 - 30 s, separately for each design | the in-lane stop may be shorter; how much is an assumption to vary, not a fact |
| Car occupancy | 1.0 - 1.6 people per car (default 1.2) | weighs the cars against the bus |
| Bus occupancy | 20 - 80 passengers (default 50) | weighs the bus against the cars |

## How it will be run

- **Paired comparisons.** The same seed should give the same arrivals of cars in both designs (common random
  numbers), so the difference is measured on identical traffic and its noise is small. Today the arrivals share one
  random stream with everything else, so this needs a separate stream for arrivals (see below).
- **Unseen seeds,** separate from those used for training, selection and the published results.
- **Enough runs per point** for 95% confidence intervals on the difference (Wilson intervals[^wilson] for
  rates, bootstrap intervals for delays), and the curves of the difference against inflow, with the point where it
  changes sign if there is one.

## What must be in place first

The instrument is built, but these items would bias this particular comparison and come first:
- **Traffic arrivals (limitation O20).** The generator loses arrivals while its entry is blocked, so "heavy" traffic
  is not much heavier. A queue of pending arrivals is needed to test high inflows.
- **The in-lane scenario (O5, O7).** It is a baseline that still resets the bus's pose at the stop; it needs the same
  physical treatment as the bay.
- **Cars' steering (O21).** Cars overshoot when they move aside for the bus; with a queue behind an in-lane stop that
  matters less, at a bay more.
- **Paired arrivals.** Arrivals need their own random stream, so that a seed produces the same traffic in both
  designs.
- **Person delay.** The existing person-weighted speed counts each vehicle's whole trip; the primary measure needs the
  free-flow reference defined and tested first.

## Threats to validity

- One lane, one stop, one bus; no buses in sequence, no traffic lights.
- No vehicle mass (a bus brakes like a car) and no brake lag ([limitations](LIMITATIONS.md) O17, O18).
- The driver is good but not perfect: 2.2% of its pull-outs end in contact. The bay's cost may be slightly
  overstated or understated depending on how a real driver would handle those cases.
- Arrivals are synthetic (Poisson), not counted from a real street.

[^merged]: **Merged.** The bus is wholly in the lane (lateral position at least -0.25 m). Judged on traffic only. "Merged" says nothing about the road edges: a merged bus may still have left the road on the way. That is what [strict success](GLOSSARY.md#strict) adds. [more](GLOSSARY.md#merged)
[^invariants]: **Invariants (physics checks).** Checks run on every simulated run for moments that cannot happen in reality. A run is not judged only by its outcome. `busmerge/invariants.py` goes over the whole frame log and reports every impossible moment. Cars crossing the centre line or the kerb are reported but not failed (mostly the overshoot of their steering law when they move over for the bus, limitation O21). [more](GLOSSARY.md#invariants)
[^wilson]: **Wilson interval.** A confidence interval for a percentage measured on a limited number of runs. For 100 runs, a result near 97% has a 95% interval of about ±6 points in the worst case, so two results that differ by a few points are not necessarily different. [more](GLOSSARY.md#wilson)
