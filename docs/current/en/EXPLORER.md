# Measurements and research

> **An interactive tool: try it yourself.** Choose the traffic, the people per car and on the bus, and the stop time in
> the lane and in the bay (separately, equal, or equal plus a penalty for the bay's less precise stop). The tool answers
> from {{stop:runs}} stored simulated runs, with the 95% interval. Its starting values are only a place to begin; the
> assumptions behind them, with their sources, are at the bottom of the tool and on the [Field data](FIELD_DATA.md) tab.

<!-- embed: explorer -->

Below the tool: what the runs showed across the whole range, chapter by chapter. Our conclusion from them is on the
[Conclusions](RESULTS.md) tab.

## The question, and what we did

[The research question](RESEARCH.md): when does traffic move fastest, when the bus stops in a bay or when it stops in
the lane? To find out, we ran the same road {{stop:runs}} times: two designs (the bay, where the trained driver
[[merged|merges]] back into traffic, and the lane), five traffic inflows (0.1 to 0.5 cars per second), and eight stop
times ({{stop:dwells}} s), with {{stop:pairs_min}} to {{stop:pairs_max}} different seeds for each combination.

**The two designs always faced the same traffic** ([[paired|paired runs]]). For a given seed the cars arrive at the same moments, with the same
sizes and the same desired speeds, in both designs, so any difference in the outcome comes from the stop and not from
the luck of the draw.

**People, not vehicles, and the reader picks the people.** The yardstick is [[person_time|person-time]]: every vehicle's trip, from the
moment it was due to enter the road until it left the other end, multiplied by the people it carries. How many people
ride on the bus and in each car is not something the simulation can decide, and it changes from line to line and hour
to hour, so **nothing on this page assumes a bus load.** For each pair of runs the simulation measures two things:

- **a**, how much longer the bus's trip is with the bay (seconds, paid by every passenger on board);
- **b**, how much longer the trips of all the cars together are with the bay (vehicle-seconds).

The difference is `ΔPT = bus passengers × a + people per car × b`: **below zero, the bay moved people faster.** The
formula is linear, so the stored data answers for any occupancy without a new run. The tables below give the number of
bus passengers at which the two designs tie, and the explorer above lets you set every value yourself.
Where one car occupancy is needed we use {{stop:pc}}, the middle of the Israeli range (1.2 to 1.5; see the
[field-data check](FIELD_DATA.md)).

## Chapter 1: what the bay costs the bus

The bay has one price, and the bus pays it: after boarding, the bus must find a gap and merge back. Compared with
leaving at once from a stop in the lane, **the bus's trip is {{stop:a_min}} to {{stop:a_max}} s longer in every one of
the {{stop:cells}} cells**, even with no stop at all, and longer when the traffic is denser:

**In the table:** how many seconds longer the bus's trip is when it stops in the bay rather than in the lane (bay minus
lane). Rows: the stop time, the same in both designs. Columns: the traffic inflow, in cars per second. Each number is a
mean over paired runs with the same cars.

{{stop:table_bus}}

Every passenger on the bus pays these seconds, so the fuller the bus, the more the bay costs.

## Chapter 2: what the bay buys the cars

What the bay buys is for the cars. A bus that stops in the lane stands there for the whole stop, and every car behind it
waits. On a single lane nobody can pass, so a queue forms: from none at all in the shortest stops to **{{stop:q_max}}
cars on average** when the stop is long and the traffic dense, and in the worst cell the longest wait at the entrance of
the road averages {{stop:entry_wait_max}} s. In the bay the cars drive past the standing bus.

**In the table:** how much the total travel time of all the cars in a run changes when the bus stops in the bay rather
than in the lane (bay minus lane), in vehicle-minutes: one minute of one car. Minus: the bay saved the cars time. Plus:
the bay slowed them. Rows and columns as in chapter 1.

{{stop:table_cars}}

The saving grows with the inflow and the stop time, to about {{stop:b_big}} vehicle-minutes in a single run at 45 s and
0.5 cars/s.

**Short stops are the exception.** The bay makes the cars *slower* {{stop:slower_cars}}: there is little or no queue to
save them from, and they brake for the bus as it pulls back into the lane. With no stop at all, at 0.5 cars/s, the cars
lose about {{stop:b_stop0}} vehicle-minutes in a run.

## Chapter 3: who wins

Put the bus's loss and the cars' gain on the same scale: **the bay wins when the bus carries few enough passengers that
their lost seconds weigh less than the cars' saved minutes.** The bus load at which the two sides balance is the
[[break_even|tipping point]].

**In the table:** the number of bus passengers at which the bay and the lane move people equally fast, with {{stop:pc}}
people per car. With fewer passengers on board, the bay wins; with more, the lane. For example, at 15 s and 0.1 cars/s
the cell says {{stop:tip_0.1_15}}: up to {{stop:tip_0.1_15}} passengers the bay wins, above that the lane. *lane always*:
the lane wins at any bus load. *over 100*: the bay wins even for a full bus. Rows: the stop time, the same in both
designs. Columns: the traffic inflow, in cars per second.

{{stop:table_tipping}}

The same points as a chart, with the short urban stops marked, are on the [Conclusions](RESULTS.md#our-conclusion) tab.
With 1.2 or 1.5 people per car instead of {{stop:pc}}, every number in the table shrinks or grows by 11%.

- **A short stop: the lane, whatever the bus carries.** At stops of {{stop:lane_always_max}} s or less the lane wins at
  every inflow, at any bus load and any car occupancy: the bay costs both the bus and the cars. What this means for
  urban stops: see [Conclusions](RESULTS.md#our-conclusion).
- **In between, the bus load decides.** At 15 s and 0.3 cars/s the tipping point is about {{stop:tip_0.3_15}}
  passengers; at 0.5 cars/s, about {{stop:tip_0.5_15}}. At 20 s and 0.3 cars/s, about {{stop:tip_0.3_20}}.
- **A long stop in dense traffic: the bay, unless the bus is full.** At 30 s and 45 s, from 0.3 cars/s, the tipping
  point is above 100 passengers: the queue the bay spares is so long that it wins even for a crowded bus.
- **The emptier the bus, the better the bay.** The bus's loss is counted in people and the cars' gain is not, so every
  passenger fewer on the bus moves the verdict toward the bay.

The same picture as a count: how many of the cells go to each design, by the number of bus passengers.

**In the table:** each cell of the experiment is one combination of traffic inflow and stop time, {{stop:cells}} cells in
all (5 inflows × 8 stop times), so every row adds up to {{stop:cells}}. Each row is a different bus load, with
{{stop:pc}} people per car. *Bay wins* or *lane wins*: in that cell the runs decide in its favour (the 95% interval of the
mean lies wholly on one side of zero). *Undecided*: the difference between the designs is smaller than the spread
between runs, so we cannot say which is better.

{{stop:table_examples}}

## Chapter 4: what if the bay stop is longer?

The stop times above are the same in both designs, but a stop in a bay may not be as quick. In the lane the bus stops
in line with the kerb; in a bay it may stop further from the kerb or from the waiting passengers, and boarding takes a
little longer (the [field-data check](FIELD_DATA.md) collects what is known). How much
longer is an assumption, so we paired a lane stop with a *longer* bay stop.

**In the table:** as in chapter 3, the number of bus passengers at which the two designs tie ({{stop:pc}} people per
car): fewer passengers, the bay wins; more, the lane. The difference is in the rows: the stop time in the lane / the stop
time in the bay, in seconds. For example, 15 / 20 is a 15 s stop in the lane against a 20 s stop in the bay. Columns: the
traffic inflow, in cars per second.

{{stop:table_pairs}}

A bay stop that is only a few seconds longer moves the tipping point down sharply. At 0.3 cars/s, a 15 s lane stop
against a 20 s bay stop ties at about {{stop:tip_0.3_15_20}} passengers, against {{stop:tip_0.3_15}} when both stops
take 15 s; and a 6 s lane stop beats a 10 s bay stop at any load. **So the bay needs long stops, dense traffic and a
lightly loaded bus to pay for itself, and every second it adds to the stop pushes that further out.**

## How sure are we

- **Every number is a mean over paired runs.** Each cell has {{stop:pairs_min}} pairs (stops of 0 to 6 s) or
  {{stop:pairs_max}} (10 to 45 s), and the verdicts use the 95% interval of the mean (normal approximation). The tipping
  points are means; near them single seeds disagree, and the explorer above shows the interval for any
  choice.
- **The driver's imperfections do not decide it.** The trained driver touches a car in {{stop:contact_pct}}% of its
  {{stop:bay_runs}} pull-outs and clips the bay's exit kerb in {{stop:offroad_pct}}%. Leaving out every seed whose bay
  run ended in contact changes the bus's delay by at most {{stop:da_max}} s and the cars' total by at most
  {{stop:db_max}} vehicle-seconds, in any cell.
- **Nothing was cut off.** Runs with a vehicle still on the road at the time limit: {{stop:censored}} of
  {{stop:runs}}. The [physics checks](GLOSSARY.md#invariants) found only the bay's known kerb clipping and contacts.
- **Where the data comes from.** The first experiment was measured at commit `{{stop:commit_v1}}`. The short-stop
  experiment was first measured with uncommitted changes in the working tree, so it was run again from the clean commit
  `{{stop:commit_v2}}` ({{stop:date_v2}}). All {{stop:runs_v2}} runs and every vehicle trip in them came out identical to
  the first measurement. Its runs pair with the first experiment's because the arrival schedule depends only on the seed.

## The data

The data, the analysis scripts and the design are in the repository: the summary of both experiments is
`results/experiments/stop_design/combined.json` (written by `scripts/summarize_stop_experiments.py`), and the design is
described in [the research question](RESEARCH.md#how-it-was-run) and `docs/reference/EXPERIMENT_STOP_DESIGN.md`.
