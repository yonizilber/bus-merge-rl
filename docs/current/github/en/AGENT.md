[Overview](README.md) · [Research question](RESEARCH.md) · [Measurements and research](EXPLORER.md) · [Conclusions](RESULTS.md) · [Field data](FIELD_DATA.md) · [World model](WORLD.md) · **Agent** · [Case study](CASE_STUDY.md) · [The app](APP.md) · [Changelog](CHANGELOG.md) · [Testing](TESTING.md) · [Limitations](LIMITATIONS.md) · [Glossary](GLOSSARY.md) · [עברית](../he/AGENT.md)

> **Read this on the website**, where the tabs switch in place and the interactive explorer works: [https://yonizilber.github.io/bus-merge-rl/en/AGENT.html](https://yonizilber.github.io/bus-merge-rl/en/AGENT.html)

# Agent

The **agent** is the bus driver for the one decision the [world model](WORLD.md) leaves open: when boarding in the bay
ends, when and how to pull out and merge into the lane. It is a neural network trained with reinforcement learning, and
it acts only through the world's physics.

**Version:** brain 0.13.0, the default and the only working version (see [Versions](#versions)).

## The decision loop

At every 0.1 s step, while the bus is in `WAITING_TO_MERGE`:

```
world state ──► observation (11 numbers) ──► policy network ──► action (steer, gas)
                                                                    │
                     governor (off by default) ──► safety shield ──► steering and speed controllers ──► world
```

## Observation space

The agent receives 11 numbers, built by one function for both the app and training
(the observation[^observation]). They describe the merge itself and the **single nearest car** within 50 m ahead of
or 20 m behind the bus front. The policy has no memory: each decision uses only the current observation.

<!-- cards: | input -->

| Input | Index | Meaning | Range (clipped to) | Normalisation | Perception noise (if enabled) |
|---|---|---|---|---|---|
| Progress | 0 | How far out of the bay the bus is: 0 in the bay (lateral position -3.5 m), 1 centred in the lane (0 m) | 0 to 1 | `x` | none: the bus knows its own position |
| Bus heading | 1 | The bus's angle to the road, positive when it points toward the lane | -0.54 to 0.54 rad (about ±31°) | `x / 0.54` | none: the bus knows its own heading |
| Gap | 2 | Distance from the bus's rear bumper to the nearest car's front bumper. Positive: the car is behind the bus. Negative: the car's front is already beside or ahead of the bus's rear. With no car in the scan window (50 m ahead, 20 m behind the bus front) it is set to 60 m | -10 to 60 m | `(x + 10) / 70` | grows in proportion to the gap |
| Lateral clearance | 3 | Lane width left beside the bus after the car's width and its sideways drift: 3.5 m − (bus lateral position + 1.25 m) − (car width − car sideways offset). Negative: the two overlap sideways | -2 to 4 m | `(x + 2) / 6` | grows in proportion to the gap |
| Car speed | 4 | Speed of the nearest car | 0 to 20 m/s | `x / 20` | grows with the square of the gap |
| Car acceleration | 5 | Acceleration of the nearest car (negative: braking) | -9 to 3 m/s² | `x / 9` | strong, plus a low-pass filter |
| Car width | 6 | Width of the nearest car | 1.70 to 2.05 m | `(x − 1.85) / 0.2` | tiny |
| Car length | 7 | Length of the nearest car (4.5 m when there is none) | 3.5 to 5.5 m | `(x − 4.5)` | tiny |
| Relative speed | 8 | Bus speed minus car speed (0 when there is no car) | -15 to 15 m/s | `x / 15` | grows with the square of the gap |
| Relative acceleration | 9 | Bus acceleration minus car acceleration, the bus acceleration taken from its speed change over the last step | -15 to 15 m/s² | `x / 15` | strong, plus a low-pass filter |
| Car heading | 10 | The nearest car's angle to the road (it drifts in its lane and moves over for the bus) | -0.15 to 0.15 rad (about ±8.6°) | `x / 0.15` | grows in proportion to the gap |

Perception noise[^noise] is off in the app by default. When enabled, the noisy inputs get a slowly varying bias (an
Ornstein-Uhlenbeck[^ou] process) rather than independent jitter, and the acceleration inputs are also low-pass
filtered. The governor[^governor] and the shield[^shield] always see the true values.

## Action space

Two continuous actions, each in [-1, 1]:
- **`steer`** sets the lateral target: -1 is the centre of the bay (-3.5 m), +1 the centre of the lane (0 m). A
  pure-pursuit[^pure_pursuit] controller then steers the bus there. The agent chooses *where*; the controller decides *how*.
- **`gas`** sets the target speed, `max(0, gas) × 11.1 m/s`. A proportional controller turns it into an acceleration
  between -3 and +2 m/s².

## Policy network

An actor-critic[^actor_critic] architecture. The actor (the policy) has two hidden layers of 64 tanh units, a mean
head for each action and a state-dependent standard deviation; a separate critic of the same shape estimates the value
of a state and is used only in training. At run time the agent acts on the mean, so it is deterministic.

## Training

The agent is trained with Proximal Policy Optimization (PPO)[^ppo]: rollouts of 2,000 steps, a clipping ratio of 0.2,
generalised advantage estimation (λ = 0.95, γ = 0.995), and Adam at a learning rate of 5·10⁻⁵. The training environment
adds only what is specific to training (scenario generators, the reward, telemetry); every physics step runs on the
same engine as the app. The training scenarios vary the traffic (a jam, slow urban traffic, a merge already under way,
fast flow, a platoon, dense traffic, and a queue like the app's) and randomise the start pose, the bus's power and
driver distraction.

## Reward function

| Term | Value | Purpose |
|---|---|---|
| Time | -1 per step | Penalise waiting without reason |
| Patience | +0.5 per step while stationary in the bay with the lane blocked | Reward waiting for a gap |
| Lateral progress | 55 × the lateral movement toward the lane, as a fraction of 3.5 m; halved when a car is 0-2 m behind | Reward leaving the bay |
| Closing risk | up to -25 per step when a car is within 12 m and the relative speed exceeds 0.5 m/s | Discourage merging into a car. **Known issue R1:** the sign is inverted; the term fires when the gap is opening |
| Safe steering | steer request × a safety factor (0 at a 6 m gap, 1 at 26 m or more) × a weight of 8 (30 once out of the bay, in the training of 0.13.0) | Encourage steering for the lane when it is safe |
| Governor hold | -4 × the steer request when the governor held the bus | Prevent the "always held, never merge" exploit |
| Shield intervention | -(20 + 60 × steer²) × strength | Discourage reliance on the shield |
| **Contact** | **terminal: -2,500 - 1,000 × min(progress / 0.75, 1)** for a body overlap above 0.01 m² | A contact is a crash, judged before success |
| **Success** | **terminal: +5,000** | The merge is complete |
| Timeout | terminal: -3,500 - 6,000 × (idle fraction)² | Idling a whole episode costs almost as much as a crash |

## Safety layers

Two rule-based layers sit between the policy and the vehicle:
- The governor[^governor] can veto a merge when a car is closing fast. It is **off** by default, and every shipped
  brain was trained without it.
- The safety shield[^shield] is always on and overrides the command in dangerous moments, for example with an
  emergency stop when the gap would close within one step. Every intervention is logged, shown in the app and penalised
  in training.

The measured performance is therefore that of the policy together with the shield; the app lists every shield
intervention so the two can be told apart.

## Evaluation

Every published number comes from one evaluation harness (`busmerge/evaluation.py`), used by the app, the tests, the
verification script and the scheduled gates. An episode ends in one of these outcomes:

| Outcome | Meaning |
|---|---|
| `merged` | The bus completed the merge after boarding |
| `collision` | The bus body touched a car body (polygon overlap[^contact_judge]) or rear-ended one |
| `off_road` | The bus body went below the kerb or the bay wall |
| `over_centre_line` | The bus body entered the opposing lane |
| `stuck_waiting` | The bus never completed the merge |

"Merged" is judged on traffic only; strict success[^strict] also requires no physics violation of any kind. Results
are reported on seeds never used for training or selection, with confidence intervals[^wilson].

## Versions

Brains follow [semantic versioning](CHANGELOG.md#versioning) with major version 0: no brain passes every acceptance
criterion yet. Each new training run is a new minor version. The files keep their original names.

| Version | File | Inputs | Trained on simulation | Status |
|---|---|---|---|---|
| **0.13.0** | `ppo_bus_brain_v13.pth` | 11 | 0.4.0 | ✔ **Working: the default.** 97.8% merged, 89.4% strict success on 1,000 unseen runs |
| 0.12.0 | not shipped (`exp7satv12*`) | 11 | 0.3.0 (prototype) | Not released: a fine-tune that did not improve |
| 0.11.0 | `ppo_bus_brain_v11_engine.pth` | 11 | 0.2.0 | ✘ Superseded. Learned to rely on the old steering defect; stops half way out of the bay |
| 0.10.0 | `ppo_bus_brain_exp7satv10_best.pth` | 11 | original repository | ✘ Superseded. Experimental reward; stops half way |
| 0.9.0 | `ppo_bus_brain_exp7satv9_best.pth` | 11 | original repository | ✘ Superseded. The original repository's default; stops half way |
| 0.8.0, 0.7.0, 0.4.0 | `exp7sat`, `exp7`, `exp4` | 11, 7, 4 | original repository | ✘ Not measured on the current simulation |

Only 0.13.0 should be used. The others are kept because they are the evidence for the [case study](CASE_STUDY.md) and
because tests use 0.11.0 to prove that the stall check can fail.

How each version did on the current simulation. Every row is a different set of unseen runs (the seeds column), so the
percentages of different rows are not over the same runs; the columns are explained on the [overview](README.md#the-result-a-bus-driver-that-behaves-like-a-real-one).
Each number is the share of that row's runs:

<!-- results:brain_table_semver (generated by scripts/publish_results.py; do not edit) -->
| Brain | Status | Seeds | Merged | Contact | Stuck | Strict success | Over centre line | Off road | Mean / p95 time |
|---|---|---|---|---|---|---|---|---|---|
| **0.13.0** | ✔ **Working** (default) | 2000-2999 | 97.8% | 2.2% | 0.0% | 89.4% | 0.0% | 8.7% | 13.3 / 16.7 s |
| 0.11.0 | ✘ Superseded: stops half way | 2000-2999 | 0.0% | 0.8% | 99.2% | 0.0% | 0.0% | 100.0% | – |
| 0.10.0 (best checkpoint) | ✘ Superseded: stops half way | 2000-2099 | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% | 100.0% | – |
| 0.9.0 (best checkpoint) | ✘ Superseded: stops half way | 2000-2099 | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% | 100.0% | – |
<!-- /results:brain_table_semver -->

## Code map

| Part | Module |
|---|---|
| The observation (one builder, used by the app and training) | `busmerge/rl/observation.py`, `feature_encoding.py` |
| The training environment and the reward | `busmerge/rl/env.py` |
| The network and PPO | `busmerge/rl/ppo_agent.py`, `busmerge/rl/train.py` |
| Governor and shield | `busmerge/rl/governor_logic.py` |
| The evaluation harness | `busmerge/evaluation.py` |
| The published numbers | `busmerge/results.py`, `results/` |

[^observation]: **Observation.** What the agent is told at every step: 11 numbers about the merge and the nearest car. One function, `busmerge/rl/observation.py::build_observation`, builds it for both the app and training. The full list, with ranges and scaling, is on the [Agent](AGENT.md) page. [more](GLOSSARY.md#observation)
[^noise]: **Perception noise.** Errors added to what the agent perceives, growing with distance, so that it cannot rely on exact numbers. Optional; off in the app. Only the agent's input is noisy; the physics checks, the governor and the shield always see the truth. The bus's own progress and heading are never noisy. The acceptance gate covers noise 0 and 0.15. [more](GLOSSARY.md#noise)
[^ou]: **OU process (Ornstein-Uhlenbeck).** A random wobble that is pulled back toward its centre: slowly varying noise, not jitter. Used here for lane drift and for perception errors. A pure random walk wanders off without limit. The Ornstein-Uhlenbeck process adds a pull toward the centre that grows with the distance, so the value wobbles around the centre, with a typical size and a memory of a few seconds. That is what a driver's imperfect lane keeping looks like, and what a persistent misjudgement of a distance looks like. [more](GLOSSARY.md#ou)
[^governor]: **Governor.** A rule layer that can veto the agent's merge when a car is closing fast. Switched off by default. It projects the closing speed of the nearest car forward and can hold the bus, block the merge steering, retreat, or command an escape. The shipped brains were trained without it, so it is off in the app. The [safety shield](GLOSSARY.md#shield) is separate and is always on. [more](GLOSSARY.md#governor)
[^shield]: **Safety shield.** A rule layer, always on, that overrides the agent's command in dangerous moments (for example an emergency stop). It looks at the nearest car's gap and closing speed. Its interventions are recorded and shown in the app, and in the training reward every intervention is penalised, so the agent does not learn to lean on it. [more](GLOSSARY.md#shield)
[^pure_pursuit]: **Pure pursuit.** A steering method: aim at the point on the target line a look-ahead distance ahead, in the vehicle's own frame, and steer along the arc that reaches it. Because the formula includes the vehicle's heading, the vehicle steers back as it approaches the line and arrives parallel to it, instead of crossing it. This is the controller that replaced the one that overshot every target. [more](GLOSSARY.md#pure_pursuit)
[^actor_critic]: **Actor-critic network.** The agent's neural network: an actor that chooses the two actions, and a separate critic that estimates how good the situation is. The actor is the policy; the critic only helps training (it estimates the expected return, used to judge actions). When the brain drives in the app or in a measurement, only the actor is used and it acts on its mean, so the same state always gives the same action. [more](GLOSSARY.md#actor_critic)
[^ppo]: **PPO (Proximal Policy Optimization).** A reinforcement-learning method that improves the policy in small, safe steps by limiting how far one update can move it. A rollout of 2,000 steps is collected; then the network is updated several times on it. Each update compares how likely every action is now with how likely it was when it was taken, and does not let that ratio move far from 1. [more](GLOSSARY.md#ppo)
[^contact_judge]: **Contact judge.** The test that decides whether two vehicles touched: the exact overlap area of their body polygons. Training and the acceptance gate use the same judge, with the same threshold (an overlap of more than 0.01 m² counts as contact) and the same order of precedence (contact is judged before success). [more](GLOSSARY.md#contact_judge)
[^strict]: **Strict success.** Merged, and in addition no physical anomaly: the bus stayed on the road, out of the opposing lane, with no contact or other violation. It is the honest measure. For brain 0.13.0 it is 89.4% of 1,000 unseen runs, against 97.8% merged. [more](GLOSSARY.md#strict)
[^wilson]: **Wilson interval.** A confidence interval for a percentage measured on a limited number of runs. For 100 runs, a result near 97% has a 95% interval of about ±6 points in the worst case, so two results that differ by a few points are not necessarily different. [more](GLOSSARY.md#wilson)

---

[Overview](README.md) · [Research question](RESEARCH.md) · [Measurements and research](EXPLORER.md) · [Conclusions](RESULTS.md) · [Field data](FIELD_DATA.md) · [World model](WORLD.md) · **Agent** · [Case study](CASE_STUDY.md) · [The app](APP.md) · [Changelog](CHANGELOG.md) · [Testing](TESTING.md) · [Limitations](LIMITATIONS.md) · [Glossary](GLOSSARY.md) · [עברית](../he/AGENT.md)
