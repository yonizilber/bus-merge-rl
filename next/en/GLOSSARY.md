# Glossary

The terms the other pages underline with a dotted line. Hover over one (or tab to it) for a one-line
explanation. Click it to jump to a note at the bottom of the same page; the note has a link back to the
exact place you left. This page has the fuller entries, in alphabetical order.

## Acceptance gate {#acceptance}
> A script that runs 100 episodes and fails a brain that merges too slowly, collides, or breaks any physical check.

`scripts/acceptance.py` runs 100 episodes at perception noise 0 and 0.15 on the same engine as the app. A
brain passes when it merges in every run (at least 98 with noise), has no collision, and its mean merge time is at
most 15.0 s with a 95th percentile of at most 20.0 s. No shipped brain passes it yet: v13 meets the time limits
but not the contact and road-edge criteria.

## Actor-critic network {#actor_critic}
> A neural network with two outputs: the actor chooses the action, the critic estimates how good the situation is.

Here both share a trunk of two 64-unit layers with tanh activations. The actor outputs the mean of each of
the two actions (squashed to [-1, 1] by a tanh) and a spread that depends on the state; the critic outputs one
number, the expected return. During training the action is sampled around the mean, to explore. When the
brain drives in the app or in a measurement it uses the mean, so the same state always gives the same
action.

## Bay (bus bay) {#bay}
> The recess beside the lane where the bus stops: entry taper, a flat part, exit taper, one lane deep.

The drawn outline is one function, `geometry.bay_outline()`: the entry taper is 265-285 m, the flat part 285-315 m
and the exit taper 315-330 m, 3.5 m deep. The app, the GIF, the renderer and the physics checks all use that same
outline.

## Bicycle model (kinematic) {#bicycle}
> A car reduced to two wheels, the front one steering: heading changes at speed × tan(steering angle) / wheelbase.

Every car and the bus move sideways this way. The steering angle changes the heading, the heading changes the
sideways position, and the steering is limited in angle and in rate, so a vehicle cannot jump sideways.
"Kinematic" means that only geometry is modelled, with no tyre forces or mass.

## Boarding (dwell) {#boarding}
> The time the bus stands in the bay with passengers (15 s by default). It ends when the agent takes over.

"Time from the end of boarding" is how every merge time in these pages is measured, because that is the moment
the agent's decisions start to matter.

## Brain {#brain}
> The trained network, stored as a `.pth` file (a checkpoint). Names such as v13 identify versions.

A brain contains the actor-critic weights. The number of inputs (4, 7 or 11) is read from the file itself. All
the brains that merge in this project use 11.

## Clamp {#clamp}
> A correction by assignment: "if the value is beyond the limit, set it to the limit". It hides a problem instead of exposing it.

Clamps are why a bus could cross the centre line without any check noticing. The simulation used to have six
of them on positions and headings; all were deleted and replaced by checks that report the violation.

## CI (continuous integration) {#ci}
> GitHub Actions that run the linter and the whole test suite on every push.

The workflow is `.github/workflows/ci.yml`. A second workflow, `nightly.yml`, runs the [[nightly|nightly gates]].

## Contact judge {#contact_judge}
> The test that decides whether two vehicles touched: the exact overlap area of their body polygons.

Training and the acceptance gate use the same judge, with the same threshold (more than 0.01 m² counts as
contact) and the same order of precedence (contact is judged before success). It is computed on the rotated rectangles of
the two vehicles.

## Fine-tuning {#fine_tune}
> Continuing to train an existing brain, instead of starting from random weights.

v13 is v11 fine-tuned for 300 epochs under the corrected steering. Training from scratch with the same recipe
reached only 20-25 s per merge.

## GAE (generalized advantage estimation) {#gae}
> A way to estimate how much better an action was than expected, using the rewards of several following steps.

PPO needs that estimate for every step. Here λ = 0.95 and the discount γ = 0.995.

## Golden test {#golden}
> A test that stores a fingerprint of a run with a fixed seed and fails if a later change alters it.

The fingerprints are in `tests/golden/`. They protect a refactoring: if the engine or the training environment
behaves differently by even a tiny amount, the test shows it. A golden file may be regenerated only when the change
is intended and explained.

## Governor {#governor}
> A rule layer that can veto the agent's merge when a car is closing fast. Switched off by default.

It projects the closing speed of the nearest car forward and can hold the bus, block the merge steering, retreat, or
command an escape. The shipped brains were trained without it, so it is off in the app. The [[shield|safety shield]] is separate and is
always on.

## "Hand of God" corrections {#hand_of_god}
> The old physics layer that kept cars apart by assignment: speed caps, position trims, frozen stops.

Under it, 68 of 100 acceptance runs contained braking beyond 9 m/s² and a contact the physics could not avoid was
hidden. Replaced on 2026-10-10 by the [[safe_speed|safe-speed law]]; the old code is at the git tag
`legacy-hand-of-god`.

## IDM (Intelligent Driver Model) {#idm}
> A car-following model: acceleration depends on the car's speed, its desired speed, and the gap and speed difference to the car ahead.

Treiber, Hennecke and Helbing proposed it in 2000. In this project every car has its own parameters, drawn per
driver: top speed, time headway, comfortable braking, minimum gap (2 m) and reaction time. There are five
classes (Compact, Mid, Large, SUV, Aggressive). The IDM is re-evaluated at the driver's reaction time, and
its acceleration is then limited by the [[safe_speed|safe-speed law]].

## Invariants (physics checks) {#invariants}
> Checks run on every simulated run for moments that cannot happen in reality.

`busmerge/invariants.py` looks for braking beyond 9 m/s², acceleration beyond 5 m/s², negative speed, backward
motion, position jumps, overlaps, a bus corner or kerb corner outside the road, a bus corner over the centre line,
and a heading beyond 60°. Cars crossing the centre line or the kerb are reported, not failed.

## Jerk {#jerk}
> The rate of change of acceleration, in m/s³. A real brake needs time to build up force, so jerk is bounded.

The test suite checks that jerk stays within bounds. One known limitation is that braking can start with a jerk of
about 100 m/s³, where a real brake system gives 30-60 (see the limitations page).

## Kerb corner {#kerb_corner}
> The point where the bay's exit taper meets the plain kerb. It points into the road.

If the bus steers out too slowly from the far end of the bay, this corner cuts into the bus's side. The checker
first missed it, because it compared only the four body corners with the road edge. Now the kerb corners are
tested against the body too.

## Merged {#merged}
> The bus is wholly in the lane (lateral position at least -0.25 m). Judged on traffic only.

"Merged" says nothing about the road edges: a merged bus may still have left the road on the way. That is what
[[strict|strict success]] adds.

## Nightly gates {#nightly}
> Quality checks that run on GitHub every night, on seeds that are used nowhere else.

`pytest --nightly -m nightly` runs the default brain on 200 unseen seeds (3000-3199) and requires at least 95% merged,
85% strict, no centre-line crossing and no other violation. It then sweeps four traffic inflows (0.2 to 0.8 cars/s) on
50 further seeds each. That is 400 runs on 250 different seeds. They are too slow to run on every push.

## Observation {#observation}
> What the agent is told at every step: 11 numbers about the merge and the nearest car.

One function, `busmerge/rl/observation.py::build_observation`, builds it for both the app and training. The
full list is on the [How it works](HOW_IT_WORKS.md) page.

## OU process (Ornstein-Uhlenbeck) {#ou}
> A random wobble that is pulled back toward the centre. It gives slowly varying, not jittery, noise.

It is used for lane drift (imperfect lane keeping, for every vehicle including the bus) and for the biases of the
agent's perception noise.

## Overshoot {#overshoot}
> A vehicle passes its target line before settling on it.

The original merge steering overshot every target, and the agent learned to rely on it. See the
[case study](CASE_STUDY.md).

## Parity (training and production) {#parity}
> Training and the app must run the same physics, observation and rules, otherwise the agent learns a world that does not exist.

Most of the early problems in this project were parity bugs: a different speed limit constant, a different
heading at the start of the merge, cars that yielded in training but not in the app. Now the training
environment steps the app's own engine, and a test checks that the two agree bit for bit.

## Perception noise {#noise}
> Optional errors added to what the agent perceives, growing with distance, so the agent cannot rely on exact numbers.

Only the agent's input is noisy; the physics checks, the governor and the shield always see the truth. The
bus's own progress and heading are never noisy. The app runs without noise unless you switch it on, and the acceptance gate covers noise 0 and 0.15.

## Plant {#plant}
> In control engineering, the thing that is controlled. For the agent: the vehicle and its steering controller.

An RL agent learns to use the plant it is given, defects included. See the [case study](CASE_STUDY.md).

## PPO (Proximal Policy Optimization) {#ppo}
> A reinforcement-learning method that improves the policy in small, safe steps by limiting how far one update can move it.

A rollout of 2,000 steps is collected, and then the network is updated by comparing the probability of each action
now and when it was taken (the ratio). The ratio is clipped to 0.8-1.2 so that no single update changes the
policy too much. The optimizer is Adam with a learning rate of 5e-5.

## Property-based test {#property_test}
> A test that states a rule ("never brakes harder than 9 m/s²") and lets a library try thousands of generated cases.

The `hypothesis` library does the generating, and when it finds a counterexample it shrinks it to the smallest
case. It found the minimum-gap intrusion of the safe-speed law (limitation O19).

## Pure pursuit {#pure_pursuit}
> A steering method: aim at the point on the target line a look-ahead distance ahead, in the vehicle's own frame.

The formula includes the vehicle's heading, so the vehicle counter-steers as it nears the line and arrives
parallel to it, instead of crossing it. The look-ahead is 18 m in the lane, 6 m while pulling into the bay and 12 m
when merging. The bus's steering is limited to 15° and about 25°/s.

## Reward function {#reward}
> The number the agent receives after every step. It learns to maximise its sum.

Here: -1 per step, a payment for steering toward the lane when it is safe, +5,000 for merging and at least -2,500 for
contact. See the [How it works](HOW_IT_WORKS.md) page for every term.

## Reward hacking {#reward_hacking}
> The agent finds a way to get a high reward that the designer did not intend.

Here the agent asked to go only half way out of the bay and let a defect in the steering controller carry it
into the lane. See the [case study](CASE_STUDY.md).

## Rollback rule {#rollback}
> During training: after several evaluations without improvement, go back to the best checkpoint so far.

A fine-tune that starts with no successful evaluation has no "best" except its starting weights, so the rule threw
away every 30 epochs of learning. It is now a flag (`--rollback-patience`), and it only restores a checkpoint that
evaluated with at least one success.

## Safe-speed law {#safe_speed}
> One rule limits every follower's acceleration so it can still stop if the leader brakes. If even that is not enough, the vehicles touch and it is recorded.

`v_safe = sqrt(v_leader² + 2·b·gap)` (Gipps and Krauss style, as in the SUMO simulator), together with `v_leader + gap/dt`
so that no vehicle closes more than the gap in one step. Acceleration is also bounded by 9 m/s². Speed and position
then follow from acceleration; nothing is assigned.

## Safety shield {#shield}
> A rule layer, always on, that overrides the agent's command in dangerous moments (for example an emergency stop).

It looks at the nearest car's gap and closing speed. Its interventions are recorded and shown in the app. In the
training reward every intervention is penalised.

## Seeds (unseen seeds) {#seed}
> A seed fixes the random numbers of a run, so it can be replayed. "Unseen" seeds were never used for training or selection.

Ranges: 1000-1099 for choosing between candidate brains, 2000-2999 for the published numbers, 3000-3249 for the nightly
gates. In the app, "Fixed random seed" replays any of them.

## Single source of truth {#ssot}
> Every fact (a constant, a formula, a shape) is defined once, and everything else uses it.

The bay outline, the road edge, the steering law, the observation, the merge rule and the published numbers each have
exactly one definition. A copy is treated as a bug, because copies drift apart.

## Strict success {#strict}
> Merged, and in addition no physical anomaly: the bus stayed on the road, out of the opposing lane, with no contact or other violation.

It is the honest measure. For v13 it is 89.4% of 1,000 unseen runs, against 97.8% merged.

## Strict xfail {#strict_xfail}
> A test for a known limitation: it keeps its honest assertion, must fail on that assertion, and turns red the day the behaviour changes.

Deleting the test or loosening its threshold would hide the limitation. With strict xfail it stays in the
suite, next to the code, and it cannot silently start passing or break for another reason.

## Time step (dt) {#dt}
> The simulation advances in steps of 0.1 s.

Every acceleration, speed and position is updated once per step, and the agent decides once per step.

## Wilson interval {#wilson}
> A confidence interval for a percentage measured on a limited number of runs.

For 100 runs, a result near 97% has a 95% interval of about ±6 points in the worst case, so two results that differ by a few
points are not necessarily different.
