# Measurements and research

> **An interactive tool: try it yourself.** Choose the traffic, the people per car and on the bus, and the stop time in
> the lane and in the bay (separately, equal, or equal plus a penalty for the bay's less precise stop). The tool answers
> from 19,500 stored simulated runs, with the 95% interval. Its starting values are only a place to begin; the
> assumptions behind them, with their sources, are at the bottom of the tool and on the [Field data](FIELD_DATA.md) tab.

> **The interactive explorer** is an HTML page: download [`stop_design_explorer.en.html`](../../../tools/stop_design_explorer.en.html) and open it in a browser, or browse the HTML site.

Below the tool: what the runs showed across the whole range, chapter by chapter. Our conclusion from them is on the
[Conclusions](RESULTS.md) tab.

## The question, and what we did

[The research question](RESEARCH.md): when does traffic move fastest, when the bus stops in a bay or when it stops in
the lane? To find out, we ran the same road 19,500 times: two designs (the bay, where the trained driver
merges[^merged] back into traffic, and the lane), five traffic inflows (0.1 to 0.5 cars per second), and eight stop
times (0, 3, 6, 10, 15, 20, 30 and 45 s), with 150 to 300 different seeds for each combination.

**The two designs always faced the same traffic** (paired runs[^paired]). For a given seed the cars arrive at the same moments, with the same
sizes and the same desired speeds, in both designs, so any difference in the outcome comes from the stop and not from
the luck of the draw.

**People, not vehicles, and the reader picks the people.** The yardstick is person-time[^person_time]: every vehicle's trip, from the
moment it was due to enter the road until it left the other end, multiplied by the people it carries. How many people
ride on the bus and in each car is not something the simulation can decide, and it changes from line to line and hour
to hour, so **nothing on this page assumes a bus load.** For each pair of runs the simulation measures two things:

- **a**, how much longer the bus's trip is with the bay (seconds, paid by every passenger on board);
- **b**, how much longer the trips of all the cars together are with the bay (vehicle-seconds).

The difference is `ΔPT = bus passengers × a + people per car × b`: **below zero, the bay moved people faster.** The
formula is linear, so the stored data answers for any occupancy without a new run. The tables below give the number of
bus passengers at which the two designs tie, and the explorer above lets you set every value yourself.
Where one car occupancy is needed we use 1.35, the middle of the Israeli range (1.2 to 1.5; see the
[field-data check](FIELD_DATA.md)).

## Chapter 1: what the bay costs the bus

The bay has one price, and the bus pays it: after boarding, the bus must find a gap and merge back. Compared with
leaving at once from a stop in the lane, **the bus's trip is 5.3 to 10.5 s longer in every one of
the 40 cells**, even with no stop at all, and longer when the traffic is denser:

**In the table:** how many seconds longer the bus's trip is when it stops in the bay rather than in the lane (bay minus
lane). Rows: the stop time, the same in both designs. Columns: the traffic inflow, in cars per second. Each number is a
mean over paired runs with the same cars.

| Bus, bay − lane (s) | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 |
|---|---|---|---|---|---|
| **45 s** | +5.3 | +6.7 | +8.0 | +9.4 | +10.5 |
| **30 s** | +5.5 | +6.5 | +7.4 | +7.9 | +8.4 |
| **20 s** | +5.4 | +6.7 | +7.2 | +7.3 | +7.4 |
| **15 s** | +5.3 | +6.5 | +7.1 | +7.3 | +7.2 |
| **10 s** | +5.5 | +6.4 | +6.8 | +7.1 | +7.3 |
| **6 s** | +5.5 | +6.4 | +6.9 | +7.2 | +7.0 |
| **3 s** | +5.5 | +6.3 | +6.6 | +6.7 | +6.6 |
| **0 s** | +6.2 | +7.7 | +8.6 | +9.0 | +9.2 |

Every passenger on the bus pays these seconds, so the fuller the bus, the more the bay costs.

## Chapter 2: what the bay buys the cars

What the bay buys is for the cars. A bus that stops in the lane stands there for the whole stop, and every car behind it
waits. On a single lane nobody can pass, so a queue forms: from none at all in the shortest stops to **22
cars on average** when the stop is long and the traffic dense, and in the worst cell the longest wait at the entrance of
the road averages 77 s. In the bay the cars drive past the standing bus.

**In the table:** how much the total travel time of all the cars in a run changes when the bus stops in the bay rather
than in the lane (bay minus lane), in vehicle-minutes: one minute of one car. Minus: the bay saved the cars time. Plus:
the bay slowed them. Rows and columns as in chapter 1.

| All cars, bay − lane (vehicle-min) | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 |
|---|---|---|---|---|---|
| **45 s** | −3.6 | −10.7 | −22.4 | −34.9 | −45.4 |
| **30 s** | −1.8 | −5.1 | −11.3 | −18.4 | −24.5 |
| **20 s** | −0.9 | −2.3 | −4.7 | −8.1 | −11.0 |
| **15 s** | −0.5 | −1.1 | −1.9 | −3.3 | −4.7 |
| **10 s** | −0.2 | −0.2 | +0.3 | +1.1 | +1.4 |
| **6 s** | +0.0 | +0.4 | +1.8 | +4.3 | +6.5 |
| **3 s** | +0.2 | +0.8 | +2.7 | +6.5 | +9.9 |
| **0 s** | +0.2 | +1.0 | +3.1 | +7.7 | +12.3 |

The saving grows with the inflow and the stop time, to about 45 vehicle-minutes in a single run at 45 s and
0.5 cars/s.

**Short stops are the exception.** The bay makes the cars *slower* for stops of 6 s or shorter at every inflow, and at 10 s from 0.3 cars/s: there is little or no queue to
save them from, and they brake for the bus as it pulls back into the lane. With no stop at all, at 0.5 cars/s, the cars
lose about 12 vehicle-minutes in a run.

## Chapter 3: who wins

Put the bus's loss and the cars' gain on the same scale: **the bay wins when the bus carries few enough passengers that
their lost seconds weigh less than the cars' saved minutes.** The bus load at which the two sides balance is the
tipping point[^break_even].

**In the table:** the number of bus passengers at which the bay and the lane move people equally fast, with 1.35
people per car. With fewer passengers on board, the bay wins; with more, the lane. For example, at 15 s and 0.1 cars/s
the cell says 8: up to 8 passengers the bay wins, above that the lane. *lane always*:
the lane wins at any bus load. *over 100*: the bay wins even for a full bus. Rows: the stop time, the same in both
designs. Columns: the traffic inflow, in cars per second.

| Dwell time / inflow (cars/s) | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 |
|---|---|---|---|---|---|
| **45 s** | 55 | over 100 | over 100 | over 100 | over 100 |
| **30 s** | 27 | 64 | over 100 | over 100 | over 100 |
| **20 s** | 13 | 28 | 52 | 90 | over 100 |
| **15 s** | 8 | 14 | 22 | 37 | 53 |
| **10 s** | 3 | 2 | lane always | lane always | lane always |
| **6 s** | lane always | lane always | lane always | lane always | lane always |
| **3 s** | lane always | lane always | lane always | lane always | lane always |
| **0 s** | lane always | lane always | lane always | lane always | lane always |

The same points as a chart, with the short urban stops marked, are on the [Conclusions](RESULTS.md#our-conclusion) tab.
With 1.2 or 1.5 people per car instead of 1.35, every number in the table shrinks or grows by 11%.

- **A short stop: the lane, whatever the bus carries.** At stops of 6 s or less the lane wins at
  every inflow, at any bus load and any car occupancy: the bay costs both the bus and the cars. What this means for
  urban stops: see [Conclusions](RESULTS.md#our-conclusion).
- **In between, the bus load decides.** At 15 s and 0.3 cars/s the tipping point is about 22
  passengers; at 0.5 cars/s, about 53. At 20 s and 0.3 cars/s, about 52.
- **A long stop in dense traffic: the bay, unless the bus is full.** At 30 s and 45 s, from 0.3 cars/s, the tipping
  point is above 100 passengers: the queue the bay spares is so long that it wins even for a crowded bus.
- **The emptier the bus, the better the bay.** The bus's loss is counted in people and the cars' gain is not, so every
  passenger fewer on the bus moves the verdict toward the bay.

The same picture as a count: how many of the cells go to each design, by the number of bus passengers.

**In the table:** each cell of the experiment is one combination of traffic inflow and stop time, 40 cells in
all (5 inflows × 8 stop times), so every row adds up to 40. Each row is a different bus load, with
1.35 people per car. *Bay wins* or *lane wins*: in that cell the runs decide in its favour (the 95% interval of the
mean lies wholly on one side of zero). *Undecided*: the difference between the designs is smaller than the spread
between runs, so we cannot say which is better.

| Bus passengers | Cells where the bay wins | Cells where the lane wins | Cells undecided |
|---|---|---|---|
| **10** | 19 | 21 | 0 |
| **20** | 16 | 23 | 1 |
| **40** | 13 | 26 | 1 |
| **60** | 9 | 30 | 1 |

## Chapter 4: what if the bay stop is longer?

The stop times above are the same in both designs, but a stop in a bay may not be as quick. In the lane the bus stops
in line with the kerb; in a bay it may stop further from the kerb or from the waiting passengers, and boarding takes a
little longer (the [field-data check](FIELD_DATA.md) collects what is known). How much
longer is an assumption, so we paired a lane stop with a *longer* bay stop.

**In the table:** as in chapter 3, the number of bus passengers at which the two designs tie (1.35 people per
car): fewer passengers, the bay wins; more, the lane. The difference is in the rows: the stop time in the lane / the stop
time in the bay, in seconds. For example, 15 / 20 is a 15 s stop in the lane against a 20 s stop in the bay. Columns: the
traffic inflow, in cars per second.

| Stop in lane / in bay | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 |
|---|---|---|---|---|---|
| **3 / 6 s** | lane always | lane always | lane always | lane always | lane always |
| **6 / 10 s** | lane always | lane always | lane always | lane always | lane always |
| **10 / 15 s** | 2 | 1 | lane always | lane always | lane always |
| **15 / 20 s** | 4 | 8 | 12 | 22 | 32 |
| **20 / 30 s** | 5 | 11 | 22 | 38 | 53 |
| **30 / 45 s** | 7 | 19 | 41 | 66 | 85 |

A bay stop that is only a few seconds longer moves the tipping point down sharply. At 0.3 cars/s, a 15 s lane stop
against a 20 s bay stop ties at about 12 passengers, against 22 when both stops
take 15 s; and a 6 s lane stop beats a 10 s bay stop at any load. **So the bay needs long stops, dense traffic and a
lightly loaded bus to pay for itself, and every second it adds to the stop pushes that further out.**

## How sure are we

- **Every number is a mean over paired runs.** Each cell has 150 pairs (stops of 0 to 6 s) or
  300 (10 to 45 s), and the verdicts use the 95% interval of the mean (normal approximation). The tipping
  points are means; near them single seeds disagree, and the explorer above shows the interval for any
  choice.
- **The driver's imperfections do not decide it.** The trained driver touches a car in 2.3% of its
  9,750 pull-outs and clips the bay's exit kerb in 8.6%. Leaving out every seed whose bay
  run ended in contact changes the bus's delay by at most 0.4 s and the cars' total by at most
  8 vehicle-seconds, in any cell.
- **Nothing was cut off.** Runs with a vehicle still on the road at the time limit: 0 of
  19,500. The [physics checks](GLOSSARY.md#invariants) found only the bay's known kerb clipping and contacts.
- **Where the data comes from.** The first experiment was measured at commit `fa5ee4c`. The short-stop
  experiment was first measured with uncommitted changes in the working tree, so it was run again from the clean commit
  `c4894bc` (2026-11-15). All 4,500 runs and every vehicle trip in them came out identical to
  the first measurement. Its runs pair with the first experiment's because the arrival schedule depends only on the seed.

## The data

The data, the analysis scripts and the design are in the repository: the summary of both experiments is
`results/experiments/stop_design/combined.json` (written by `scripts/summarize_stop_experiments.py`), and the design is
described in [the research question](RESEARCH.md#how-it-was-run) and `docs/reference/EXPERIMENT_STOP_DESIGN.md`.

[^merged]: **Merged.** The bus is wholly in the lane (lateral position at least -0.25 m). Judged on traffic only. "Merged" says nothing about the road edges: a merged bus may still have left the road on the way. That is what [strict success](GLOSSARY.md#strict) adds. [more](GLOSSARY.md#merged)
[^paired]: **Paired runs.** Two runs, one for each stop design, with exactly the same cars. For one seed, the bay run and the in-lane run get the same arrival times, and every car the same class, size and desired speed (common random numbers). Any difference between the two is then due to the stop, not to the luck of the draw, and far fewer runs are needed for a tight interval than with independent runs. [more](GLOSSARY.md#paired)
[^person_time]: **Person-time.** How long all the people in the vehicles travelled: each vehicle's trip time times the people in it, summed. The stop experiment compares the two designs on person-time, not vehicle-time, because a bus carries many people and a car one or two. [more](GLOSSARY.md#person_time)
[^break_even]: **Tipping point.** The number of bus passengers at which a bay and an in-lane stop are equal. With fewer passengers the bay is better, with more the lane. A cell where the lane wins at any load has no tipping point ("lane always"). [more](GLOSSARY.md#break_even)
