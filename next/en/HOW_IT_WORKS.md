# How it works

This page explains the system from the road to the agent. Terms with a dotted underline show a short explanation
when you hover over them; click one to read a longer note at the bottom of the page, with a link back to where you
were. The [glossary](GLOSSARY.md) lists them all.

## 1. The world

- A single-lane urban road, 1000 m long, simulated in steps of [[dt|0.1 s]].
- A city bus (11.0 m × 2.5 m) drives in, pulls into a [[bay|bus bay]] at about 300 m, and stands there for
  [[boarding|boarding]] (15 s by default).
- When boarding ends, the **agent** takes over. It decides when and how to pull out and merge into the traffic
  lane. The merge is done when the bus is wholly in the lane.
- Cars arrive from the start of the road and follow each other. They yield to the bus once it is clearly
  entering the lane.

```
traffic ──► cars ─────────────────────┐
                                      ├──► one physics step (0.1 s) ──► frame log ──► checks and outcome
bus ──► state machine ──► the agent ──┘
        (MOVING, DECELERATING, IN_BAY, WAITING_TO_MERGE)
```

The Streamlit app, the training environment, the tests and the verification scripts all run this same engine.

## 2. The traffic

### Cars

Each car follows the [[idm|Intelligent Driver Model]], with its own parameters drawn per driver. There are five
classes:

| Class | Share | Top speed | Comfortable braking | Time headway | Reaction time |
|---|---|---|---|---|---|
| Compact | 30% | 14.5 m/s | 2.2 m/s² | 1.35 s | 0.45 s |
| Mid | 30% | 13.9 m/s | 2.0 m/s² | 1.50 s | 0.50 s |
| Large | 15% | 13.0 m/s | 1.8 m/s² | 1.70 s | 0.58 s |
| SUV | 15% | 13.5 m/s | 1.9 m/s² | 1.60 s | 0.55 s |
| Aggressive | 10% | 15.5 m/s | 2.5 m/s² | 1.00 s | 0.35 s |

Sizes follow real models (for example a Corolla for Compact). The values above are the class means; each driver is
sampled around them. The minimum gap is 2 m, and each driver has a politeness drawn from a Beta distribution: the
aggressive class yields least.

### One safe-speed law

An IDM driver reacts only every reaction time, so on its own it can drive into the car ahead between two
decisions. Instead of correcting that afterwards (the old "[[hand_of_god|Hand of God]]" corrections), every
follower's acceleration is bounded by one [[safe_speed|safe-speed law]]:

```
v_safe  = sqrt(v_leader² + 2·b·gap)         can still stop if the leader brakes
v_frame = v_leader + gap / dt               do not close more than the gap in one step
a       = max( min(a_driver, (min(v_safe, v_frame) − v) / dt), −9 m/s² )
```

Speed and position then follow from the acceleration. Nothing is assigned. If even 9 m/s² is not enough, the
vehicles touch and the contact is recorded as a collision, not hidden.

### Moving sideways

Every vehicle moves sideways with a [[bicycle|kinematic bicycle model]]: steering angle changes the heading, the
heading changes the sideways position, and steering is limited in angle and in rate. A steering controller aims
the vehicle at a target line using [[pure_pursuit|pure pursuit]]. Every vehicle also wobbles slightly in its lane
([[ou|lane drift]]).

### Arrivals

A car arrives with probability `rate × dt` at each step, but only if the entry is clear (0.5 s since the last car
and 15 m to it), and it enters at a speed from which it can still stop behind the car ahead. Arrivals during a
blocked entry are lost, not queued, so the delivered inflow is lower than the setting (see
[Limitations](LIMITATIONS.md), O20).

## 3. The bus and the bay

The bus is always in one of four states:

| State | Sideways | Along the road |
|---|---|---|
| `MOVING` | holds the lane centre | follows traffic |
| `DECELERATING` (last 50 m) | follows the kerb into the bay | brakes to stop exactly at a stop point, limited to 9 m/s² |
| `IN_BAY` | held | boarding for 15 s |
| `WAITING_TO_MERGE` | **the agent decides** | **the agent decides**; ends when the bus is at lateral position -0.25 m or further into the lane |

The stop point varies from run to run (a normal distribution around 300 m, clipped to 297-307 m), so the whole bus is
in the flat part of the bay with at least 8 m left to steer out. The bus steers with
[[pure_pursuit|pure pursuit]] in every state: with a look-ahead of 18 m in the lane, 6 m while pulling in, and
12 m while merging.

## 4. The agent

### What it sees

At every step the agent receives 11 numbers, built by one function for both the app and training
([[observation|the observation]]). They describe the merge itself and the **single nearest car** within 50 m ahead
or 20 m behind the bus front. The agent has no memory: each decision uses only these 11 numbers.

{{features_table}}

Perception noise is off in the app by default. When on, the noisy inputs get a slowly varying bias
([[ou|Ornstein-Uhlenbeck]]), not independent jitter, and the acceleration inputs are also low-pass filtered. The
[[governor|governor]] and the [[shield|shield]] always see the true values. Older brains used fewer inputs (4 or 7):
subsets of this list (the 4-input brain sees progress, heading, gap and relative speed), and the number is read from the brain file.

### What it does

Two numbers, each in [-1, 1], at every step:
- **`steer`** is the sideways target: -1 is the middle of the bay (-3.5 m), +1 is the middle of the lane (0 m). The
  steering controller then drives the bus there. The agent chooses *where*; the controller decides *how*.
- **`gas`** is the speed target: `max(0, gas) × 11.1 m/s`. A proportional controller turns it into an acceleration
  between -3 and +2 m/s².

### The network

An [[actor_critic|actor-critic network]]: a shared trunk of two 64-unit layers (tanh), an actor head with a mean
for each action and a spread that depends on the state, and a critic head. In the app and in every
measurement the agent uses the mean, so it is deterministic.

### How it learns

The agent is trained with [[ppo|PPO]]: 2,000-step batches, ratio clip 0.2, [[gae|GAE]] (λ 0.95, γ 0.995) and
Adam with a learning rate of 5e-5. The training environment adds only what is specific to training (scenario
generators, the reward, telemetry); every physics step is run by the same engine as the app. The scenarios vary the
traffic: a jam, slow city traffic, a merge already under way, fast flow, a platoon, dense traffic, and a production-like
queue. Training also randomises the start pose, the bus power and driver distraction.

### The reward

The [[reward|reward]] is what the agent tries to maximise. Every term, as in `busmerge/rl/env.py`:

| Term | Value | Why |
|---|---|---|
| Time | -1 per step | Do not wait for nothing |
| Patience | +0.5 per step while standing still in the bay with the lane blocked | Waiting for a gap is right |
| Lateral progress | 55 × the sideways movement toward the lane, as a fraction of the 3.5 m; halved when a car is 0-2 m behind | Pay for leaving the bay |
| Closing risk | up to -25 per step when a car is within 12 m and the relative speed is above 0.5 m/s | Do not merge into a car. **Known issue R1:** the sign is inverted, it fires when the gap is opening |
| Safe steering | steer request × a safety scale (0 at a 6 m gap, 1 at 26 m or more) × a weight of 8 (in the v13 fine-tune: **30** once out of the bay, at progress 0.15 or more) | Steer for the lane when it is safe; "finish what you started" |
| Governor hold | -4 × the steer request when the governor held the bus | Prevents the "always held, never merge" exploit |
| Shield intervention | -(20 + 60 × steer²) × strength | Do not rely on the shield |
| **Contact** | **terminal: -2,500 - 1,000 × min(progress / 0.75, 1)** when the body overlap is above 0.01 m² | A contact is a crash, judged before success |
| **Success** | **terminal: +5,000** | Merged |
| Timeout | terminal: -3,500 - 6,000 × (the fraction of idle steps)² | Idling the whole run costs nearly as much as a crash |

### Two safety layers

Two rule layers sit between the agent and the vehicle:
- The [[governor|governor]] can veto the merge when a car is closing fast. It is **off** by default, and the
  shipped brains were trained without it.
- The [[shield|shield]] is always on and overrides the command in dangerous moments, for example an emergency stop
  when the gap would close within one step. Each intervention is recorded and shown in the app, and penalised
  in training.

This means the result you measure is the agent and the shield together. The reports separate them where they can:
the app lists every shield intervention.

## 5. How a run is judged

Every number in these pages comes from one harness, `busmerge/evaluation.py`, used by the app, the tests, the
verification script and the nightly gates. A run ends in one of these outcomes:

| Outcome | Meaning |
|---|---|
| `merged` | The bus completed the merge after boarding |
| `collision` | The bus body touched a car body ([[contact_judge|polygon overlap]]) or rear-ended one |
| `off_road` | The bus body went below the kerb or the bay wall |
| `over_centre_line` | The bus body entered the opposing lane |
| `stuck_waiting` | The bus never completed the merge |

"Merged" is judged on traffic only. [[strict|Strict success]] is a merge with none of the other anomalies. Besides the
outcome, [[invariants|physics checks]] look for every impossible moment: braking beyond 9 m/s², acceleration beyond
5 m/s², negative speed, backward motion, position jumps, overlaps, leaving the road, the centre line and extreme
headings. Cars that cross the centre line or the kerb (they do it when they move over for the bus) are reported but
not failed.

Results are measured on [[seed|unseen seeds]], with [[wilson|confidence intervals]]: at 100 runs, differences
of a few points are not significant.

## 6. Where things live in the code

| Part | Module |
|---|---|
| The engine: spawning, the bus state machine, the physics step, the frame log | `busmerge/simulation.py` |
| Vehicles: IDM, the bicycle model, pure pursuit, the five classes, the bus | `busmerge/vehicle.py` |
| The safe-speed law | `busmerge/safe_speed.py` |
| Geometry: the bay outline, road edges, kerb corners, overlap area | `busmerge/geometry.py` |
| The harness: run an episode, classify the outcome, the merge timeline | `busmerge/evaluation.py` |
| The physics checks | `busmerge/invariants.py` |
| The observation (one builder, used by both worlds) | `busmerge/rl/observation.py`, `feature_encoding.py` |
| The training environment and reward | `busmerge/rl/env.py` |
| PPO and the training loop | `busmerge/rl/ppo_agent.py`, `train.py` |
| Governor and shield | `busmerge/rl/governor_logic.py` |
| The published numbers | `busmerge/results.py`, `results/` |
| The dashboard | `streamlit_app.py` |
