# The simulation against published field data

**Status:** updated 2026-11-05 for the explorer's model (passengers and doors set the dwell time, short stops of 0 to 6 s added in `stop_design_v2`, a penalty for the bay). First written 2026-11-01. It checks the stop-design experiment (`stop_design_v1` and `v2`, see
the results page, `docs-v3/en/RESULTS.md`) against what could be found in published studies. It is a literature check,
not a calibration: nothing in the simulation was changed because of it.

**Reading order.** First what the simulation *produces* (how long the bus takes to merge, how long a queue builds,
how many cars get in), because those are the things it claims to reproduce. Then what it only *uses* as input
(dwell times, people per car and per bus).

**How much to trust each source.** Every source is marked:
- **read**: the report's text was downloaded and the numbers below were read in it;
- **summary**: only a search-engine summary or an abstract page was seen. The number is repeated as found and should
  be checked against the original before anyone quotes it.

The simulation's numbers come from `scripts/compare_with_real_data.py`
(`results/experiments/stop_design_v1/real_data_comparison.json`), from the same 15,000 runs as the results page.

## Verdicts at a glance

| # | Question | Simulation | Field data | Verdict |
|---|---|---|---|---|
| 1 | How much longer is the bus's trip with a bay stop than with an in-lane stop? | +5.3 to +10.5 s, mean about 7 s | Singapore: acceleration with re-entry 11.35 s against 9.73 s, +1.6 s, at sites without heavy congestion (read). Ottawa: acceleration and re-entry 4 to 5 s longer (quoted in the Singapore paper; other summaries say 13 s per stop) | **Simulation at the top of the measured range** (about 2 to 6 s) |
| 2 | How long does the bus take to merge back? | 12.9 s on average (median 12.5, 90% under 16.2, longest 37.4 s) | San Francisco: 4 to 13 s average wait before moving, up to 52 s (read). Florida: 36 s average, 29 s when a car yields, 39 s when not (read) | **Average plausible; the long tail is missing** |
| 3 | How long is the queue behind a bus stopped in the lane? | 1.1 cars (10 s stop, 0.1 cars/s) to 22.3 cars (45 s, 0.5 cars/s); one lane, nobody passes | San Francisco: 1 to 3 cars on average, 6 at most; drivers change lanes about once per bus (read) | **Matches at short stops only; long queues are an artefact of one lane** |
| 4 | How many cars does the entry let in? | 0.34 cars/s (1,231 per hour) once a queue stands at it | Standard saturation flow 1,900 per hour per lane, about 1.9 s per car (summary) | **Simulation about a third below** |
| 5 | How much do cars lose to an in-lane stop, compared with a bay? | 2 to 4 s per car at a 15 s stop, 3 to 9 s at 20 s, 14 to 36 s at 45 s | Ottawa: about 8 s per stop at the kerb against about 4 s for a bus leaving a bay (summary) | **Same order at 15 to 20 s; cannot be checked finer** |
| 6 | Dwell times | 0 to 45 s, chosen directly (simulated at 0, 3, 6, 10, 15, 20, 30, 45 s); not derived from passengers | No Israeli measurement. Foreign measurements come from other systems (San Francisco: 3.93 s per passenger before all-door boarding, 2.45 s after; read); Israel has had boarding at all doors since 2015 (State Comptroller 2017, read) and app validation, which shorten stops | **No data: the explorer lets the reader choose it instead of guessing** |
| 7 | Does a bay stop take longer than a lane stop? | none in the simulation: the same braking time (bay minus lane: -0.03 s), the same distance from the stop pole (2.8 m) and a gap to the kerb of 0.46 m in the bay and 0.50 m in the lane. The explorer adds a field-based penalty (1 s to enter, 1 m more deviation, 0.4 m more gap) that can be changed | Singapore: 1.33 s per passenger at the kerb against 1.52 s in a bay, deceleration 8.53 against 8.84 s (read). Ottawa: deceleration 1 to 2 s longer in bays, Beijing 1.4 s (both second-hand) | **The simulation lacks the bay's extra difficulty; the explorer adds it as a visible assumption** |
| 8 | People per car | 1.35 in the explorer (middle of the Israeli range 1.2 to 1.5) | US 2017: 1.18 to or from work, 1.67 over all trips (read). Israel: 1.52 and 1.44 in household travel surveys (Ministry of Transport, 2021, read); 1.2 in news articles without a source report (see below) | **Inside the Israeli range** |
| 9 | People per bus | 20 in the explorer (a rough figure; 50 in the first experiment) | US 2016: 10.7 per bus on average, 5.1 to 16.8 across 33 metropolitan areas (read). Israel: only a fill factor (60% or less at the peak stop in over half of the trips, read) and about 20 per trip on city lines (news article, summary) | **A rough estimate, chosen by the reader in the explorer** |

## The simulation's outputs

### 1. The bus's extra time in a bay (5.3 to 10.5 s)

The simulation gives 5.3 to 10.5 s per run in all 40 cells (dwell times 0 to 45 s) (mean about 7 s). In Ottawa's review of bus bays
(consultant Genivar, 2011) the executive summary is quoted, in the search summaries, as: total stop delay without
dwell 7.6 s at the kerb against 14.75 s in a bay, an extra 5 to 6 s per stop, 4 to 5 s of it in clearance (start-up,
re-entry and acceleration). Other lines of the same review are quoted as "13 seconds per bay stop" and "12 s at
the kerb against 25 s in a bay". These do not agree with each other, and the city's pages could not be opened (they
redirect to an empty page), so the original wording is unverified. **Source status: summary.**

The Singapore study (Liu et al. 2017, **read**, in an archived copy: 16 stops in eight bay and kerb pairs, no heavy
congestion, peak hours, July 2014, 2,653 valid records) measured acceleration including re-entry delays of 11.35 s
(standard deviation 4.3 s) at bays against 9.73 s (1.9 s) at the kerb, and deceleration of 8.84 s against 8.53 s. The
same paper quotes the Ottawa survey as acceleration plus re-entry 4 to 5 s longer and deceleration 1 to 2 s longer at
bays, and London (2006) as re-entry delays reduced by 3 to 13% by converting bays to kerb stops. **The measured range
is therefore about 2 to 6 s per stop.**

**Verdict:** the simulation's 5.3 to 10.5 s is at the top of that range, and grows with traffic and dwell time; the
Singapore sites were chosen without heavy congestion. If the true cost of a bay to the bus is lower, the bay's
advantage in the results is larger than shown.

### 2. The time to merge back

What the simulation measures: from the end of boarding until the bus is fully back in the lane, including the
sideways movement. Over the 9,750 bay runs: mean 12.9 s, median 12.5 s, 90% under 16.2 s, 99% under 20.7 s, longest
37.4 s; 1.4% above 20 s, 1 run in 9,750 above 30 s. The mean grows from 11.4 s at 0.1 cars/s to 13.4 s at 0.3 cars/s and stays
there.

| Study | Where | What was timed | Result |
|---|---|---|---|
| TCRP web document 19, appendix C, **read** | San Francisco, Mission St, 25 mph, four lanes, 1999; 15 to 65 observations per row for the bay | doors closed until the bus starts moving | average 4 to 13 s by site and period (4, 4, 7, 13); minimum 1 s, maximum 9 to 52 s |
| Lin et al., Florida DOT / USF CUTR, 2013, **read** | one bus bay, Dale Mabry Hwy, Tampa (50 mph); 42 valid merges over two months | turn signal on until the bus's rear leaves the acceleration taper | average 36 s; 29 s when a car yielded (33% of merges), 39 s when the bus waited for a gap |

The definitions differ from ours and from each other: San Francisco stops the clock when the bus *starts moving*,
before the merge itself; Florida starts it at the turn signal and ends it at the end of the taper. We did not store
"end of boarding until the bus starts moving", so no like-for-like number exists yet. The Florida report states its
spread inconsistently (standard deviation 32 s overall, 13 s for yields, 13 s and 39 s for no-yields in different
places), so we do not quote it.

**Verdict:** the average is plausible next to San Francisco, a slow street like the one simulated, where a bus waits 4
to 13 s and then merges. The simulation has no long tail: real waits of 30 to 50 s occur (the Florida mean of 36 s
and San Francisco's maximum of 52 s), the simulation's longest is 28 s. A bus that rarely waits long makes the bay
look better than it is, so the bay's cost is probably a little understated. Also, the real wait is said to grow with the
adjacent traffic (Ottawa, summary; the transit capacity manual has an exhibit for it that we did not read); ours is
nearly flat from 0.3 cars/s on.

### 3. The queue behind a bus stopped in the lane

In the simulation the lane is the only lane. The largest number of stopped cars behind the bus while it stands:

| Dwell (s) | 0.1 cars/s | 0.3 | 0.5 |
|---|---|---|---|
| 10 | 1.1 | 2.8 | 3.6 |
| 15 | 1.7 | 4.4 | 5.8 |
| 20 | 2.2 | 6.2 | 8.3 |
| 45 | 4.9 | 16.0 | 22.3 |

San Francisco (**read**, four lanes with passing allowed): "the average number of vehicles in a queue was only one
vehicle with a maximum of four" outside the peak; one to six vehicles in the peak, three on average at the busiest
(nearside) stop; a queue formed behind one bus arrival in about every 2 to 17 (peak and non-peak, bay design, by site); and about one lane
change for every bus arrival: drivers go around. In the same study 62 to 72% of buses stopped in the lane even where a
bay existed (65 to 154 arrivals per row), because drivers avoid re-entry.

**Verdict:** for short stops and light traffic the simulation's 1 to 3 cars is what was observed. Above that the
simulation's queue grows far past anything observed, because on one lane nobody can pass. This confirms the main
caveat of the results page: the long-stop, dense-traffic cells, where the bay wins most clearly, describe a
single-lane road and say little about a street with a second lane. The San Francisco buses that avoid the bay
agree with the opinion that in a city the in-lane stop is the practical choice.

### 4. How many cars the road lets in

The requested inflow was 0.1 to 0.5 cars/s per lane, delivered on schedule (0.10 to 0.50 cars/s over the
150 s window). When a queue reaches the entry, the entry lets cars in at a median 2.3 s apart (mean 2.9 s): 0.34 cars/s,
1,231 per hour (20,741 entries measured). The standard base saturation flow of the Highway Capacity Manual is quoted
as 1,900 passenger cars per hour of green per lane, about 1.9 s per car (**summary**; the edition was not checked).
One study found base values from about 1,800 to 2,100 for exclusive left-turn lanes.

**Verdict:** the simulation's entry is about a third slower than the standard value, and its requested range
(360 to 1,800 per hour) overlaps real lane volumes, though the top of it cannot be delivered. A lower entry capacity
makes queues at the entry form earlier than they would in reality, which feeds the in-lane design's cost. Whether this
changes the winner of any cell has not been tested.

### 5. The cars' loss

The extra travel time per car in the lane design compared with the bay (seconds, mean over the same cars):

| Dwell (s) | 0.1 cars/s | 0.3 | 0.5 |
|---|---|---|---|
| 10 | 0.7 | −0.4 | −1.1 |
| 15 | 2.0 | 2.6 | 3.7 |
| 20 | 3.4 | 6.2 | 8.8 |
| 30 | 7.0 | 15.0 | 19.5 |
| 45 | 14.1 | 29.8 | 36.3 |

Ottawa's consultant is quoted (**summary**) with about 8 s of delay to cars per stop at the kerb against about 4 s
for a bus re-entering from a bay, a difference of about 4 s. The same review concluded that kerb stops give the lower
total person delay "under common traffic and ridership conditions", with about 9 person-minutes saved per bus trip.
The occupancies, the street layout and what "per stop" counts are unknown to us.

**Verdict:** the simulation's 2 to 4 s at a 15 s stop is the same size as Ottawa's 4 s. This is a coincidence of order of
magnitude, not a validation.

## What the simulation takes as input

### 6. Dwell times

London buses, TfL's own data (**read**, Freedom of Information release R851, 2019, routes 8, 26, 35 and others):
average dwell 9 to 16 s depending on the time of day. San Francisco's bay stops (**read**): 16 to 22 s on average, with
a range of 4 to 95 s. Portland's TriMet route 14 (cited in Fricker 2010, **read**): mean 12.42 s, standard deviation
9.23 s, 459 dwells. Models of dwell time (**summary**): 5 s plus 2.75 s per boarding or alighting passenger (Levinson),
and 2.7 s per boarding with a smart card against 4.6 s with cash.

**Verdict:** typical urban stops are 10 to 20 s, the lower half of the experiment's grid. The 30 and 45 s cells stand for
busy stops. The grid covers the reality, but the simulation uses a fixed dwell where real dwell is very variable
(standard deviation about three quarters of the mean in Portland), and the variation itself makes queues longer. Of all
the results, the ones for 10 to 20 s are therefore the ones that describe typical stops: with the default occupancies
the lane wins or ties there at most inflows, which is what the field practice of stopping in the lane suggests.

### 7. Is the in-lane stop quicker?

The experiment tried pairings in which the lane stop is shorter than the bay stop, on the thought that the bus stops
exactly at the kerb and the doors line up. The San Francisco bay-to-bulb comparison (**read**; a bulb is a stop in the
lane at an extended kerb) found the opposite: the average dwell at the bulb was 18 to 43 s against 16 to 22 s at the bay
(the report mentions supervisors talking to drivers as a possible cause). Singapore's paired stops (Liu et al. 2017, **read** in an archived copy: 16 stops in eight bay and kerb pairs, peak hours, July 2014) report 1.33 s per boarding or alighting passenger at the kerb against 1.52 s at a bay, and a fixed part of 6.5 s against 5.6 s, so ten passengers take 19.8 s against 20.8 s: about a second. Ottawa found no difference and London found 0.5 to 1 s per passenger saved by converting bays (both second-hand, through the Singapore paper). Two studies, two directions, and small differences.

No Israeli measurement of bus dwell time was found (only passengers' waiting times). **Verdict:** the assumption that a lane stop is much quicker is not supported by the evidence found; the Singapore difference is about a second. The pairing table of the
results page should be read as "what if", not as a finding.

### 8 and 9. People per car and per bus

**Israel, people per car.** Three figures, three bases. The Ministry of Transport's National Public Transport Authority summary (July 2021, p. 21, **read**) gives 1.52 (Tel Aviv metropolitan household travel survey, 2014, 3,000 households) and 1.44 (surveys 2010 to 2019 in the Jerusalem, Tel Aviv, Haifa and North, and Beer Sheva areas, 38,500 households). Walla (3 November 2019, page opened, **read**) writes that "according to Ministry of Transport data the average number of passengers in private vehicles in Israel is currently 1.2", without naming a report. Globes (6 March 2016, page opened, **read**) quotes the OECD International Transport Forum saying that a car carries "on average 1.2 people for about 50 minutes a day": a general statement about cars, not an Israeli measurement and without a definition. The Jerusalem Post (5 February 2020) is reported by search summaries to give 1.2 as well (**summary**; the body was not opened). Only the surveys rest on a described measurement. The gap may be a matter of trip type, as in the US (1.18 for work against 1.67 for all trips), but no Israeli source breaking it down by purpose was found, so this is a guess.

Cars (**read**, 2017 National Household Travel Survey, person-miles per vehicle-mile): 1.18 for trips to or from work,
1.67 for all trips, 1.82 for shopping, 2.1 for social trips. The FHWA uses 1.7. The simulation's 1.2 is a commuting value.
Buses (**read**, FHWA's factors from the 2016 National Transit Database, passenger-miles per vehicle revenue mile): 10.7
nationally, from 5.1 (Dallas-Fort Worth) to 16.8 (New York) in 33 metropolitan areas. The simulation's 50 is a very full
bus. It is an average over the whole route and day, not the load at a stop in the peak, so the truth at a given stop is
between the two.

Because the verdict is linear in the occupancies, it was recomputed from the stored runs (bay wins / lane wins / tie, out
of 40 cells: five inflows and dwell times of 0, 3, 6, 10, 15, 20, 30 and 45 s, the same dwell time in both designs):

| People per car | People per bus | Bay | Lane | Tie |
|---|---|---|---|---|
| 1.2 | 20 | 16 | 23 | 1 |
| 1.35 | 20 | 16 | 23 | 1 |
| 1.5 | 20 | 17 | 23 | 0 |
| 1.7 | 10.7 | 19 | 20 | 1 |
| 1.2 | 50 | 10 | 28 | 2 |

**Verdict:** the number of people in the bus decides more than the number in the car (the Israeli range of 1.2 to 1.5
moves the count by one cell). With dwell times down to 0 s the lane wins more cells than in the first experiment, whose
shortest stop was 10 s: very short stops cost the lane stop nothing and the bay stop the merge, and in the first
experiment's 10 to 45 s range the bay won most cells at an average bus load. The explorer
(`docs/tools/stop_design_explorer.he.html`) lets the reader choose all of these.

## What this means for the experiment's conclusions

1. **The direction of the main trade-off is supported.** A bay costs the bus a few seconds per stop; a stop in the lane
   costs the cars behind it, more with the length of the stop. Both effects appear in the field data we could read, at the
   same order of magnitude.
2. **The long-stop corner is not transferable.** Queues of 10 to 22 cars come from one lane without passing. Observed
   queues are 1 to 3 cars. The two-lane experiment is the most important next step.
3. **The occupancies and the dwell time decide many cells.** The explorer therefore lets the reader choose them, with
   the Israeli range for cars (1.2 to 1.5) and a rough 20 for a city bus as defaults.
4. **Two model gaps push the same way.** The simulation has no long waits for a gap, and it has no variation in dwell time.
   The first understates the bay's cost, the second understates the lane's. They do not cancel by design.
5. **Not tested here:** the arrival process (Poisson in the simulation, platooned by signals in cities); yielding to
   buses (Florida: 33% of merges); the simulation's lower entry flow.

## Next steps this suggests (not done)

- Store "end of boarding until the bus starts moving" for the bay runs, to compare with San Francisco on the same definition.
- Draw dwell times from a distribution (mean 12 to 15 s, standard deviation about 9 s) instead of one fixed value.
- Report the verdict for two occupancy pairs, a crowded and an average bus, side by side on the results page.
- Obtain Ottawa's full Genivar report (the city says it is available from the Clerk's office) and read the numbers
  directly.
- Run the two-lane version, where cars can pass.

## Sources

Read in full or in part:
- Lin, P.-S., Fabregas, A., Gunpinar, S., Perez-Angon, O., Behzadi, B. (2013). *Recommendations for Yield-to-Bus Traffic
  Control Devices and Bus Pullout Bays Design Characteristics.* Florida DOT, BDK85 977-33. <https://rosap.ntl.bts.gov/view/dot/23357/dot_23357_DS1.pdf>
- TCRP web document 19, *Appendix C: bus bay and bus bulb before-and-after study, San Francisco* (authors not stated in the extract we read).
  <https://onlinepubs.trb.org/onlinepubs/tcrp/tcrp_webdoc_19-b.pdf> (Tables C-5 and C-6 were read as images.)
- FHWA, *Average Vehicle Occupancy Factors for Computing Travel Time Reliability Measures and Total Peak Hour Excessive Delay Metrics.*
  <https://www.fhwa.dot.gov/tpm/guidance/avo_factors.pdf>
- FHWA, *2017 National Household Travel Survey: Summary of Travel Trends*, Table 16.
  <https://www.fhwa.dot.gov/policyinformation/documents/2017_nhts_summary_travel_trends.pdf>
- Transport for London, FOI release R851, *Stop Dwell Time* (2019). <https://foi.tfl.gov.uk/FOI-1919-2021/R851_Stop_Dwell_Time-2019.pdf>
- Fricker, J. D. (2010). *Bus dwell time analysis using on-board video* (cites Bertini and El-Geneidy for Portland).
  <https://engineering.purdue.edu/~ce560/HW/Bus_Dwell_Time_jdf.pdf>

- Liu, X., Yang, Y., Meng, M., Rau, A. (2017). *Impact of different bus stop designs on bus operating time components.* Journal of Public
  Transportation 20(1). <https://doi.org/10.5038/2375-0901.20.1.6> (read in an archived copy; it also summarises Ottawa, London and Beijing,
  which are therefore second-hand here).
- Israel, people per car: Ministry of Transport, National Public Transport Authority, *Key data on public transport*, July 2021, p. 21
  (<https://www.gov.il/BlobFolder/reports/special_reports/he/%D7%A8%D7%99%D7%9B%D7%95%D7%96%20%D7%A0%D7%AA%D7%95%D7%A0%D7%99%D7%9D%20%D7%9E%D7%A8%D7%9B%D7%96%D7%99%D7%99%D7%9D%20%D7%91%D7%AA%D7%97%D7%91%D7%95%D7%A8%D7%94%20%D7%94%D7%A6%D7%99%D7%91%D7%95%D7%A8%D7%99%D7%AA-%20%D7%99%D7%95%D7%9C%D7%99%202021.pdf>);
  Walla, 3 November 2019 (<https://www.walla.co.il/news/israel/3321228>); Globes, 6 March 2016 (<https://www.globes.co.il/news/article.aspx?did=1001108288>).
  The two articles were opened; neither names the report behind its 1.2.

Seen only as a summary or abstract page (verify before quoting):
- City of Ottawa, *Bus bays: operational and process review* (ACS2011-ICS-TRA-0010) and the Genivar executive summary, 2011.
  The addresses found by search now redirect to an empty page. Search summaries disagree on the bay's extra delay.
- Highway Capacity Manual saturation flow of 1,900 passenger cars per hour per lane: course notes and papers found by search; the manual itself was not opened.
- Levinson (1983) and smart-card boarding times, as quoted in <https://www.worldtransitresearch.info/research/4561> and related search results.
