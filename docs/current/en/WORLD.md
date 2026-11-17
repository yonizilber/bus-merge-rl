# World model

The project has two parts: the **world** (this page), a microscopic traffic simulation, and the **[agent](AGENT.md)**,
the bus driver that is trained in it. The world knows nothing about learning; the agent only ever acts through it.

**Version:** simulation 1.0.1 (the `busmerge` package). Terms with a dotted underline open an explanation, and a
technical one can be expanded into its equations and how this project implements them.

## At a glance

- A single-lane urban road, 1000 m long, simulated in fixed time steps of 0.1 s.
- Cars arrive at the start of the road, follow each other, and yield to the bus when it enters their lane.
- A city bus (11.0 m × 2.5 m) arrives, stops at a stop at about 300 m, boards passengers, and leaves. The stop time
  is a setting: 15 s in the app, 0 to 45 s in the experiment ([two ways to run](#two-ways-to-run-the-app-and-the-experiment)).
- Two stop designs ([scenarios](#scenarios)): **B**, a bus bay beside the lane (the bus must merge back), and **A**, a
  stop in the travel lane.

```
arrivals ──► cars (IDM + safe-speed law) ─────┐
                                              ├──► one physics step (0.1 s) ──► frame log ──► physics checks
bus ──► state machine ──► agent (scenario B) ─┘
```

The Streamlit app, the training environment, the tests and the verification scripts all run this one engine
(`busmerge/simulation.py`); a test checks that training and the app produce identical runs.

## Two ways to run: the app and the experiment

The engine is modular: the stop time, the traffic, how cars arrive and how long a run lasts are settings
(`SimConfig`), not part of the physics. **The app is for illustration only**: one run at a time, with its own
settings. Every result on a bay against an in-lane stop comes from the [experiment](RESEARCH.md), which runs the same
engine with other settings:

| Setting | The app (illustration) | The experiment (the results) |
|---|---|---|
| Stop time | 15 s by default, adjustable (5 to 30) | 0, 3, 6, 10, 15, 20, 30 or 45 s, fixed within a run |
| Traffic | 0.4 cars/s by default | 0.1 to 0.5 cars/s |
| Car arrivals | each step with a probability, up to 50 cars; an arrival while the entry is blocked is lost ([O20](LIMITATIONS.md)) | a Poisson schedule over the first 150 s, from its own random generator, so both designs see the same cars; a car that finds the entry blocked waits |
| Run length | up to 300 s | until every vehicle has left (cap 900 s; no run reached it) |
| People per vehicle | 1.35 per car and 20 per bus by default, only for the app's KPIs | not part of the run; a weight the reader chooses at analysis time |

## Car-following: the Intelligent Driver Model

Every car is an [[idm|IDM]] driver: its acceleration depends on its speed, the speed it wants, and the gap and speed
difference to the car ahead. Parameters are drawn per driver around the means of five classes:

| Class | Share | Desired speed | Comfortable deceleration | Time headway | Reaction time |
|---|---|---|---|---|---|
| Compact | 30% | 14.5 m/s | 2.2 m/s² | 1.35 s | 0.45 s |
| Mid | 30% | 13.9 m/s | 2.0 m/s² | 1.50 s | 0.50 s |
| Large | 15% | 13.0 m/s | 1.8 m/s² | 1.70 s | 0.58 s |
| SUV | 15% | 13.5 m/s | 1.9 m/s² | 1.60 s | 0.55 s |
| Aggressive | 10% | 15.5 m/s | 2.5 m/s² | 1.00 s | 0.35 s |

Vehicle dimensions follow real models (a Toyota Corolla for Compact, a Camry for Mid). The minimum gap is 2 m, and
each driver has a politeness drawn from a Beta distribution; the aggressive class yields least.

## Collision avoidance: one safe-speed law

An IDM driver re-plans only once per reaction time, so on its own it could close in on the car ahead between two
decisions. Instead of correcting the result afterwards, every follower's acceleration is bounded by one
[[safe_speed|safe-speed law]], the approach of the Gipps and Krauss models used in SUMO:

```
v_safe  = sqrt(v_leader² + 2·b·gap)         the follower can still stop if the leader brakes
v_frame = v_leader + gap / dt               it does not close more than the gap in one step
a       = max( min(a_driver, (min(v_safe, v_frame) − v) / dt), −9 m/s² )
```

Speed and position follow from the acceleration; nothing is ever assigned. If even 9 m/s² is not enough, the vehicles
touch and the contact is recorded as a collision. This law replaced, on 2026-10-10, a set of corrections by assignment
([[hand_of_god|"Hand of God"]]) that had hidden such cases.

## Lateral motion

Every vehicle moves sideways by a [[bicycle|kinematic bicycle model]]: the steering angle changes the heading, the
heading changes the lateral position, and the steering is limited in angle and in rate.
- **The bus** steers by [[pure_pursuit|pure pursuit]], which arrives at its target line without overshoot.
- **Cars** use a simpler law with no heading term. It overshoots every target, which is hidden only because cars move
  at most 0.5 m aside for the bus ([limitation O21](LIMITATIONS.md)).
- **Lane keeping** is imperfect for every vehicle: an [[ou|Ornstein-Uhlenbeck]] lane drift.

## Traffic arrivals

In both ways to run, a car enters only when the entry is clear (0.5 s and 15 m since the last car), at a speed from
which it can still stop behind the car ahead. The difference is what happens when it is not:

- **In the app** a car arrives with probability `rate × dt` at each step. Arrivals during a blocked entry are lost,
  not queued, so the delivered inflow is lower than the setting: about λ / (1 + 1.5·λ)
  ([limitation O20](LIMITATIONS.md)).
- **In the experiment** (`SimConfig.arrival_seed`) the arrivals follow a schedule drawn in advance, and a car that
  finds the entry blocked waits until it clears. The wait counts in its trip time, and no car is lost.

## The bus and the stop

The bus is always in one state of a small state machine:

| State | Lateral | Longitudinal |
|---|---|---|
| `MOVING` | holds the lane centre | follows traffic (IDM) |
| `DECELERATING` (last 50 m) | follows the kerb into the bay | brakes to stop exactly at the stop point, at most 9 m/s² |
| `IN_BAY` | held | boards passengers for the stop time that was set |
| `WAITING_TO_MERGE` | **chosen by the agent** | **chosen by the agent**; ends when the bus centre is at -0.25 m or further into the lane, i.e. wholly inside it |
| `STOPPED_IN_LANE` (scenario A) | held in the lane | boards passengers, then drives on |

The stop point varies from run to run (normal around 300 m, clipped to 297-307 m), so the whole bus is on the flat
part of the bay with at least 8 m left to steer out. The bay outline, the road edges and the kerb corners are defined
once (`busmerge/geometry.py`) and used by the physics, the drawings and the checks alike.

## Scenarios

| Scenario | Stop | Who drives the merge | Status |
|---|---|---|---|
| **B** (the default) | bus bay, entry taper 265-285 m, flat 285-315 m, exit taper 315-330 m | the trained agent | the scenario every published number uses |
| **A** | in the travel lane | no merge needed | a baseline. It resets the bus pose at the stop ([O5, O7](LIMITATIONS.md)). This was **not fixed**, and both experiments ran with it. The reset is lateral only (position in the lane, heading and steering) and leaves the position along the road untouched. Along the road there remains only the setting of a speed of 0.05 m/s or less to zero, as in the bay (O5) |

## Physics checks

Every run is checked for moments that cannot happen in reality ([[invariants|physics invariants]]): deceleration
beyond 9 m/s², acceleration beyond 5 m/s², negative speed, backward motion, position jumps, overlapping vehicles, the
bus leaving the road (exact polygons, including kerb corners), the bus crossing the centre line, and extreme headings.
A violation is reported with its time and vehicle; it is never corrected. Cars crossing the centre line or the kerb
are reported but not counted as failures: most of it comes from the cars' steering law (O21).

## Code map

| Part | Module |
|---|---|
| The engine: arrivals, the bus state machine, the physics step, the frame log | `busmerge/simulation.py` |
| Vehicles: IDM, the bicycle model, pure pursuit, the five classes, the bus | `busmerge/vehicle.py` |
| The safe-speed law | `busmerge/safe_speed.py` |
| Geometry: the bay outline, road edges, kerb corners, overlap area | `busmerge/geometry.py` |
| The physics checks | `busmerge/invariants.py` |
| Person-weighted measures (speed, people delivered) | `busmerge/simulation.py` (`AnalyticsEngine`) |
