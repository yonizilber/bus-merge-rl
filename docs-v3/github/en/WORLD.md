# World model

The project has two parts: the **world** (this page), a microscopic traffic simulation, and the **[agent](AGENT.md)**,
the bus driver that is trained in it. The world knows nothing about learning; the agent only ever acts through it.

**Version:** simulation 1.0.1 (the `busmerge` package). Terms with a dotted underline open an explanation, and a
technical one can be expanded into its equations and how this project implements them.

## At a glance

- A single-lane urban road, 1000 m long, simulated in fixed time steps of 0.1 s.
- Cars arrive at the start of the road, follow each other, and yield to the bus when it enters their lane.
- A city bus (11.0 m × 2.5 m) arrives, stops at a stop at about 300 m, boards passengers for 15 s, and leaves.
- Two stop designs ([scenarios](#scenarios)): **B**, a bus bay beside the lane (the bus must merge back), and **A**, a
  stop in the travel lane.

```
arrivals ──► cars (IDM + safe-speed law) ─────┐
                                              ├──► one physics step (0.1 s) ──► frame log ──► physics checks
bus ──► state machine ──► agent (scenario B) ─┘
```

The Streamlit app, the training environment, the tests and the verification scripts all run this one engine
(`busmerge/simulation.py`); a test checks that training and the app produce identical runs.

## Car-following: the Intelligent Driver Model

Every car is an IDM[^idm] driver: its acceleration depends on its speed, the speed it wants, and the gap and speed
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
safe-speed law[^safe_speed], the approach of the Gipps and Krauss models used in SUMO:

```
v_safe  = sqrt(v_leader² + 2·b·gap)         the follower can still stop if the leader brakes
v_frame = v_leader + gap / dt               it does not close more than the gap in one step
a       = max( min(a_driver, (min(v_safe, v_frame) − v) / dt), −9 m/s² )
```

Speed and position follow from the acceleration; nothing is ever assigned. If even 9 m/s² is not enough, the vehicles
touch and the contact is recorded as a collision. This law replaced, on 2026-10-10, a set of corrections by assignment
("Hand of God"[^hand_of_god]) that had hidden such cases.

## Lateral motion

Every vehicle moves sideways by a kinematic bicycle model[^bicycle]: the steering angle changes the heading, the
heading changes the lateral position, and the steering is limited in angle and in rate.
- **The bus** steers by pure pursuit[^pure_pursuit], which arrives at its target line without overshoot.
- **Cars** use a simpler law with no heading term. It overshoots every target, which is hidden only because cars move
  at most 0.5 m aside for the bus ([limitation O21](LIMITATIONS.md)).
- **Lane keeping** is imperfect for every vehicle: an Ornstein-Uhlenbeck[^ou] lane drift.

## Traffic arrivals

A car arrives with probability `rate × dt` at each step, but only when the entry is clear (0.5 s and 15 m since the
last car), at a speed from which it can still stop behind the car ahead. Arrivals during a blocked entry are lost, not
queued, so the delivered inflow is lower than the setting: about λ / (1 + 1.5·λ) ([limitation O20](LIMITATIONS.md)).

## The bus and the stop

The bus is always in one state of a small state machine:

| State | Lateral | Longitudinal |
|---|---|---|
| `MOVING` | holds the lane centre | follows traffic (IDM) |
| `DECELERATING` (last 50 m) | follows the kerb into the bay | brakes to stop exactly at the stop point, at most 9 m/s² |
| `IN_BAY` | held | boards passengers for 15 s |
| `WAITING_TO_MERGE` | **chosen by the agent** | **chosen by the agent**; ends when the bus centre is at -0.25 m or further into the lane, i.e. wholly inside it |
| `STOPPED_IN_LANE` (scenario A) | held in the lane | boards passengers, then drives on |

The stop point varies from run to run (normal around 300 m, clipped to 297-307 m), so the whole bus is on the flat
part of the bay with at least 8 m left to steer out. The bay outline, the road edges and the kerb corners are defined
once (`busmerge/geometry.py`) and used by the physics, the drawings and the checks alike.

## Scenarios

| Scenario | Stop | Who drives the merge | Status |
|---|---|---|---|
| **B** (the default) | bus bay, entry taper 265-285 m, flat 285-315 m, exit taper 315-330 m | the trained agent | the scenario every published number uses |
| **A** | in the travel lane | no merge needed | a baseline; it still resets the bus pose at the stop ([O5, O7](LIMITATIONS.md)), to be fixed before the [research comparison](RESEARCH.md) |

## Physics checks

Every run is checked for moments that cannot happen in reality (physics invariants[^invariants]): deceleration
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

[^idm]: **IDM (Intelligent Driver Model).** A car-following model: acceleration depends on the car's speed, its desired speed, and the gap and speed difference to the car ahead. Treiber, Hennecke and Helbing proposed it in 2000. Every car in the simulation is an IDM driver with its own parameters, and the bus follows the same model when it drives in the lane. [more](GLOSSARY.md#idm)
[^safe_speed]: **Safe-speed law.** One rule limits every follower's acceleration so it can still stop if its leader brakes. If even that is not enough, the vehicles touch and it is recorded. Speed and position then follow from the acceleration; nothing is assigned. It replaced the old corrections (["Hand of God"](GLOSSARY.md#hand_of_god)) and is the same idea as in the Gipps and Krauss car-following models (Krauss is the default of the SUMO simulator). [more](GLOSSARY.md#safe_speed)
[^hand_of_god]: **"Hand of God" corrections.** The old physics layer that kept cars apart by assignment: speed caps, position trims, frozen stops. Under it, 68 of 100 acceptance runs contained braking beyond 9 m/s² and a contact the physics could not avoid was hidden. Replaced on 2026-10-10 by the [safe-speed law](GLOSSARY.md#safe_speed); the old code is at the git tag `legacy-hand-of-god`. [more](GLOSSARY.md#hand_of_god)
[^bicycle]: **Bicycle model (kinematic).** A car reduced to two wheels, the front one steering: the heading turns at speed × tan(steering angle) / wheelbase. Every car and the bus move sideways this way. The steering angle changes the heading, the heading changes the sideways position, and steering is limited in angle and in rate, so a vehicle cannot jump sideways. "Kinematic" means that only geometry is modelled, with no tyre forces or mass. [more](GLOSSARY.md#bicycle)
[^pure_pursuit]: **Pure pursuit.** A steering method: aim at the point on the target line a look-ahead distance ahead, in the vehicle's own frame, and steer along the arc that reaches it. Because the formula includes the vehicle's heading, the vehicle steers back as it approaches the line and arrives parallel to it, instead of crossing it. This is the controller that replaced the one that overshot every target. [more](GLOSSARY.md#pure_pursuit)
[^ou]: **OU process (Ornstein-Uhlenbeck).** A random wobble that is pulled back toward its centre: slowly varying noise, not jitter. Used here for lane drift and for perception errors. A pure random walk wanders off without limit. The Ornstein-Uhlenbeck process adds a pull toward the centre that grows with the distance, so the value wobbles around the centre, with a typical size and a memory of a few seconds. That is what a driver's imperfect lane keeping looks like, and what a persistent misjudgement of a distance looks like. [more](GLOSSARY.md#ou)
[^invariants]: **Invariants (physics checks).** Checks run on every simulated run for moments that cannot happen in reality. A run is not judged only by its outcome. `busmerge/invariants.py` goes over the whole frame log and reports every impossible moment. Cars crossing the centre line or the kerb are reported but not failed (mostly the overshoot of their steering law when they move over for the bus, limitation O21). [more](GLOSSARY.md#invariants)
