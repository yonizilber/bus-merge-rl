# Conclusions

Based on 19,500 simulated runs ([Measurements and research](EXPLORER.md)), a check against [field data](FIELD_DATA.md)
and the planning guidelines.

## Our conclusion

> **In urban travel, a bus stop in the lane is better.** The conclusion rests on the simulation and the research, and on
> one main assumption, which matters: **inside Israeli cities the stops are relatively short, up to about
> 12 s, more or less.** By the simulation, up to 12 s a stop in the lane is almost
> always better, and between 12 and 15 s it seems to depend on how heavy the traffic in the lane is.

We based the assumption on scattered measurements made for building this project. They are not published, and we found
no published Israeli measurement, so this is a heuristic assumption, not data. It fits how the Israeli system works
(validation by app or card, boarding at every door) and the averages measured abroad (9 to 16 s in London, 12.4 s in
Portland).

At such stops the simulation is clear. Up to 6 s the lane wins at any traffic and any bus load.
At 10 s it wins from 0.3 cars per second, and in lighter traffic the bay is better only when the bus carries fewer than
2 to 3 passengers. At 12 s, which was not run but computed from the
10 s and 15 s cells (as the explorer does), the bay is better only when the bus carries fewer than
5 to 11 passengers, depending on the traffic. At 15 s the traffic already
decides: the bay is better when the bus carries fewer than 8 passengers in light traffic (0.1 cars
per second) and fewer than 53 in dense traffic (0.5). These figures use 1.35
people per car and leave out the explorer's accuracy penalties, which only add to the bay's cost. The bay pays for
itself only with longer stops, dense traffic and a lightly loaded bus. **If the stops are longer than that, the
conclusion does not hold**, and the [explorer](EXPLORER.md) shows what happens then. And against the
[field data](FIELD_DATA.md), most of the simulation's limitations favour the bay, so when it says "the lane is better" it
is on firmer ground than when it says "the bay is better".

![Up to how many bus passengers the bay wins, by stop time, in light, medium and heavy traffic](../../../media/stop_design_break_even_bus.en.png)

*How to read it: the height of each line is the number of bus passengers at which the bay and the lane tie. With fewer
passengers on board, the bay wins; with more, the lane. In the green band, the short urban stops, the lines hug zero: the
lane wins at almost any bus load. Every number, for all five inflows, is in the table of
[chapter 3](EXPLORER.md#chapter-3-who-wins).*

### What it rests on

**This agrees with the approach that planning guidance takes today.** The Israeli guidelines are the only sources here
that support the conclusion directly, because they were written for Israeli streets:

- **Israel, Ministry of Transport and Ministry of Construction and Housing**, [*Guidelines for planning streets in cities:
  pedestrian traffic*](https://ilgbc.org/wp-content/uploads/2019/10/PedestrianTrafficPlanning.pdf) (October 2009; a copy hosted by the Israel Green Building Council), section 4.11.3, pp. 83 to 84: on urban streets (not roads) the stop should
  preferably be on a kerb extension (an "anti-bay"); without a parking lane "the bus will stop in the lane or in a bay";
  and "the fact that the bus stopping at the stop delays the traffic in that lane for a moment is a traffic-calming
  factor, and directly serves the preference required in city streets for public transport and pedestrians". On urban
  roads and bus lanes, the same section places stops mainly in bays.
- **Transport Today & Tomorrow**, [*Bus stops in the urban space: a guide for local authorities and planners*](https://www.transportation.org.il/sites/default/files/pirsum/tahanot_autobus.pdf) (2014),
  p. 8: the alternative preferred for public-transport users is a stop on an anti-bay, so that the bus need not
  leave the road to enter a bay and leave it, and without a parking lane a stop with no bay at all. Among the reasons
  for an anti-bay it lists a drop-off-only or pick-up-only stop, where "the bus does not linger".

### Inspiration from elsewhere

The other sources come from other conditions: a different number of lanes, traffic
signals, other definitions. They serve as inspiration and as a comparison with other situations, not as a validation of
our numbers. In most of them the lane comes out better, or no worse:

- **Germany**, the street design guidelines RASt 06 and EAÖ 2013, as quoted in a [City of Braunschweig paper](https://www.braunschweig.de/leben/stadtplan_verkehr/verkehrsplanung/Bauform-von-Bushaltestellen-2019.pdf)
  (February 2020; the guidelines themselves *cited by another source*). On a street with one lane in each direction and no
  overtaking, like ours, a stop in the lane is the default. By EAÖ it is "unproblematic" for traffic up to about 500 to
  710 vehicles an hour in one direction, depending on the bus frequency, and by RASt 06 up to 750. Bays are recommended
  there mainly on roads without buildings alongside and with speeds above 50 km/h. This is the road most like ours, but
  the threshold is an "unproblematic" criterion, not a measurement in seconds.
- **London**, a TRL study for TfL (before and after surveys, 2002 and 2003), [appendix C of TfL's 2006 guidance](https://nacto.org/wp-content/uploads/TfL-accessibile-bus-stop-design-guidance.pdf),
  pp. 56 to 57: filling in a bay to make a stop in the lane saved the bus time, and by the full report the benefit to
  bus passengers outweighs the cost to other road users. Since then TfL fills in bays on urban roads with a speed limit
  of 30 mph or less. The numbers, against the simulation: [field data](FIELD_DATA.md#1-what-the-bus-loses-in-a-bay).
- **Singapore**, [Liu et al., 2017](https://doi.org/10.5038/2375-0901.20.1.6): buses were delayed more at a bay than at the kerb. Streets with
  two lanes in each direction, and only the bus was measured ([field data](FIELD_DATA.md#1-what-the-bus-loses-in-a-bay)).
- **Croatia**, [Cvitanić, 2017](https://hrcak.srce.hr/file/275548): a calibrated simulation (CORSIM), one lane in each direction but next to
  a signalised junction, and stops of 15 or 30 s. Up to about 800 vehicles an hour there was no significant difference
  between a stop in the lane and a bay; above that the bay was better.
- **A VISSIM simulation**, [Dashdamirov et al., 2023](https://doi.org/10.1051/e3sconf/202340101070): the same question, on streets with 2 to 4 lanes
  and 80 to 180 buses an hour. The fewer the lanes and the more the buses, the more a stop in the lane slows the cars; on
  a four-lane street there is almost no difference. The stop time is not reported, and the bus's own delay was not
  measured.
- **TCRP Report 19**, [*Guidelines for the Location and Design of Bus Stops*](https://onlinepubs.trb.org/onlinepubs/tcrp/tcrp_rpt_19-b.pdf) (Transportation Research Board, 1996), p. 27
 : bus bays should be considered when, among other conditions, traffic is faster than 40 mph, the curb lane
  carries more than 250 vehicles in the peak hour, or "average peak-period dwell time exceeds 30 seconds per bus". It
  adds that drivers do not use bays above 1,000 vehicles per hour per lane, because the bus "must wait an unacceptable
  period of time to re-enter the travel lane". Our simulation draws its line in a similar place: the bay starts to win
  at stops of 15 to 30 s, depending on the traffic and the load.
- **Transport for London**, [*Accessible Bus Stop Design Guidance*](https://foi.tfl.gov.uk/FOI-0422-2223/Accessible%20Bus%20Stop%20Design%20Guidance%202017%20Final%20ABSDG.pdf) (revised edition, 2017), section 8, p. 35:
  "Bus bays (also known as lay-bys) can present operational problems for buses and they should only be used when there
  are compelling safety or capacity reasons." Kerb build-outs keep the bus in the traffic stream, "as the bus is not
  delayed waiting to rejoin the traffic stream" (p. 32), but should not be used where bus frequency or dwell times
  "will cause delay to following buses and significant delays to general traffic": the same trade-off as our long-stop
  corner.
- **San Francisco**, [TCRP Web Document 19, appendix C](https://onlinepubs.trb.org/onlinepubs/tcrp/tcrp_webdoc_19-b.pdf), on a four-lane street: most buses stopped in the lane even
  where a bay existed, because bus drivers avoid pulling back out
  ([field data](FIELD_DATA.md#3-the-queue-behind-a-bus-stopped-in-the-lane)).
- **NACTO**, [*Transit Street Design Guide*](https://nacto.org/publication/transit-street-design-guide/stations-stops/stop-configurations/in-lane-sidewalk-stop/) (*not checked against the source*): in-lane stops are preferred
  for transit, and filling in bus bays to make in-lane stops saves buses time.

## What comes next

1. Run the same experiment on two lanes, where cars may pass a bus stopped in the lane.
2. Extend the stop-time measurements at Israeli city stops, in bays and in the lane, and publish them, so that the
   assumption the conclusion rests on becomes data.
3. Add behaviours the simulation does not model, starting with cars parked in the bay, traffic lights and pedestrian crossings.
4. Draw the stop time from a distribution instead of a fixed value.
5. Repeat with a brain that touches cars less, to see how much of the bay's cost is the driver and how much the merge.

What the simulation does not model, and which way that tilts the result: [limitations](LIMITATIONS.md#the-stop-experiment).
Still, it is good to see that in our particular case the simulation agrees with the approach of the Israeli planning
guidelines, and with the direction of many guidelines and studies elsewhere.
