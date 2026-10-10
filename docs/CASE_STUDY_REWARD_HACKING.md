# Case study: the agent that merged by exploiting its steering

**Summary.** The default PPO agent merged in 97.9% of 1,000 unseen runs. When every hidden correction
was removed from the simulation, the same runs showed the bus crossing the centre line in 100% of
them. The cause was a steering controller that overshot every target. The agent had learned to rely
on that overshoot: it asked to go only half way out of the bay and let the defect carry it into the
lane. With the controller fixed, the agent merged in 0% of runs. This document records how this was
found, how it was fixed, and what it took to retrain.

All numbers come from the same code the Streamlit app runs (`busmerge/evaluation.py`), on seeds
2000-2999 that were never used for training or selection, unless stated otherwise.

## 1. What the agent controls

While the bus leaves the bay, the agent outputs two numbers per 0.1 s step: `steer ∈ [-1, 1]` and
`gas`. `steer` is mapped to a **lateral target**: -1 is the bay centre line (y = -3.5 m), +1 is the
lane centre (y = 0). A steering controller turns that target into a steering angle, and a kinematic
bicycle model moves the bus. The agent therefore chooses *where* the bus should be, and the
controller decides *how* it gets there.

## 2. The number we believed

| Measurement | Result |
|---|---|
| Acceptance, 100 seeds (1000-1099) | 97 merged, 3 side contacts, no physics violations |
| Verification, 1,000 seeds (2000-2999), judged on traffic | **97.9% merged** (95% CI 96.8-98.6%), 2.1% contact |

The physics checks covered braking, speed, position jumps and overlaps between vehicles, and found
nothing.

## 3. Removing the clamps

The simulation still had six clamps: corrections by assignment that bounded the bus's lateral position
to [-3.5, 0.5] m, its heading to ±60°, and the cars' lateral position and lane drift. A clamp hides
whatever it bounds, so they were removed. The checks were extended instead: the road edges (kerb, bay
wall, centre line) and extreme headings. A run now counts as a strict success only if the bus merged
with none of these anomalies.

| Same 1,000 runs, v11 | Result |
|---|---|
| Strict success | **0%** |
| Bus over the centre line | 100% of runs: median 0.84 m, up to 2.34 m, for about 5 s, heading up to 21° |
| Bus over the kerb while pulling into the bay | 47% (up to 1.32 m) |
| Bus stopped past the end of the bay | 3% |

## 4. The defect

The merge step steered with

```
δ = atan2(lateral_error, max(v, 5))
```

This command has **no heading term**. The heading integrates the steering, and the lateral position
integrates the heading. With nothing damping the heading, the loop behaves like an undamped
oscillator: the bus reaches the target still turned toward it, carries on past it, and only then
starts to correct. The steering rate limit adds lag, which makes the overshoot larger still.

The fix is standard pure pursuit, which aims at the target line a look-ahead distance ahead, in the
vehicle's own frame:

```
y_rel = lateral_error·cos(ψ) − L_d·sin(ψ)
δ     = atan2(2·wheelbase·y_rel, L_d²)
```

The `−L_d·sin(ψ)` term counter-steers as the heading approaches the line, so the bus arrives parallel
to the line instead of crossing it. One function, `vehicle.pure_pursuit_steer`, now steers the bus in
every state.

## 5. The exploit

With the honest controller, the bus left the bay, travelled half way toward the lane, and stayed
there. The agent's commands, logged frame by frame (seed 2000), explain why:

| t (s) | lateral (m) | agent steer | lateral target (m) |
|---|---|---|---|
| 46.8 | -3.36 | 0.08 | -1.61 |
| 49.2 | -3.12 | 0.15 | -1.49 |
| 53.6 | -1.65 | 0.06 | -1.65 |
| 60.0 | -1.64 | 0.06 | -1.65 |

**The agent never asked for the lane.** It held a target of about -1.5 m, half way out of the bay.
Under the old controller, a command 1.9 m from the bay produced a swing that ended about 0.8 m beyond
the lane centre, and the run counted as merged the moment the bus passed y = -0.1. PPO had found the
cheapest command that produced a merge given the plant it was trained on, and the defect was part of
that plant.

Every brain was trained with the same controller, and every brain does the same thing:

| Brain | Seeds | Merged, honest steering | Stuck half way |
|---|---|---|---|
| v11 (default) | 1,000 | 0% | 99.2% (0.8% contact) |
| v10 | 100 | 0 | 100 |
| v9 | 100 | 0 | 100 |

So the 97.9% did not measure the agent alone. It measured the agent together with the defect.

## 6. Fixing the bus, not the agent

The fixes were confined to the bus. Cars crossing the centre line or the kerb, which they do while
drifting in their lane or moving over for the bus, is now reported but not failed (`InvariantReport.notes`).

- **Steering:** pure pursuit with the heading term. The look-ahead is 18 m in the lane, 6 m pulling
  in, and 12 m merging. The model rotates the bus about the centre of its body, so a shorter merge
  look-ahead swings the rear corner into the bay wall.
- **Pull-in:** the lateral target used to follow a ramp that started 50 m before the stop point,
  wherever that was. It is now read off the drawn road edge under the bus's front
  (`geometry.bay_pull_in_target`), like a driver tracking the kerb.
- **Stop range:** the stop point is clipped so that the whole bus is in the flat part of the bay
  (297-307 m), with 8 m left to steer out. The 8 m was measured: from a stop at 308 m, some exits touch
  the exit taper. The stop limit is the real end of the bay; it used to be the stop target + 15 m.
- **The checker had a gap:** it compared only the four body corners with the road edge. Where a taper
  meets the plain kerb, the kerb has a corner pointing into the road, and it can cut into a body side
  while all four body corners are on the road. Those kerb corners are now checked against the body.
- **One bay:** the app, the GIF and the renderer had three copies of the bay; the renderer's tapers
  were 10 m instead of 20/15 m. All three now draw `geometry.bay_outline()`, the outline the checker
  uses.

**Evidence that the physics allows a clean merge.** In 300 pull-ins with no agent, there was no frame
off the road; the bus stopped at its target, parallel and at bay depth, and braked at most at
2.4 m/s². A scripted exit (steer for the lane at once, constant throttle, ignoring traffic) was run
1,500 times:
- 0 frames off the road and 0 over the centre line
- heading at most 11°
- every run merged

## 7. Making retraining possible

Three things were checked before the fine-tune.

**Start poses.** The training environment placed the bus at 300 ± 2 m, ±0.4 m off the bay centre and
±4.6° off parallel, then clipped the result. Of 20,000 such poses, 14.6% put a corner past the bay
wall, and none covered the app's stop range (297-307 m). Start poses are now drawn over the stop range
and kept only if `geometry.road_edge_excess` (the function the checker uses) says the body is on the
road.

**The learner (PPO).** To reach the lane centre the agent must output `steer ≈ +1`, the edge of the
action range. The rollout computed the log-probability of the raw Gaussian sample (for example 1.3),
but stored the clipped action (1.0). The update then evaluated the log-probability of 1.0, so the PPO
ratio differed from 1 for every boundary action before any update. For good outcomes, the ratio's
clip removed the gradient; for bad outcomes, it was amplified. The bias pushed the agent away from
exactly the action it needed. The buffer now stores the raw sample, and only the command sent to the
vehicle is clipped.

**The reward.** Does it pay to reach y = 0 rather than stop half way? Fixed policies were run in the
training environment with the training settings, 150 episodes each:

| Policy | Mean return | Success | Timeout |
|---|---|---|---|
| Steer for the lane at once (ignores traffic) | +2,918 | 122 | 0 (28 contacts) |
| Hold half way (steer 0.1) | -3,763 | 0 | 146 |
| v11 | -3,822 | 0 | 144 |

The terminal bonus (+5,000) is paid only at y ≥ -0.1, a timeout costs 3,500-9,500, and a per-step
term rewards steering toward the lane while the gap is safe. The reward already ranks a full merge
about 6,700 above stopping half way, so it was left unchanged.

**The time limit.** Acceptance asks for a mean of at most 6.0 s from the end of boarding to merged, and
a p95 of at most 7.0 s. These limits were set while the steering overshot. Under honest steering, the
scripted exit at full throttle takes a mean of 6.32 s (p95 7.10 s). No policy can therefore pass the
time criteria as they stand; the limits need to be re-derived, which is a decision for the project
owner.

## 8. Fine-tune

*In progress; results will be added here.*

## 9. Lessons

1. **Measure without corrections.** Every clamp, cap and reset is a place where a failure can hide.
   Here the clamps were only the visible part. The overshoot itself was not clamped, but it was
   invisible until the road edges were checked.
2. **An RL agent optimises the plant it is given, defects included.** A success rate measured on a
   defective plant describes the pair, not the agent.
3. **Look at the commands, not only the outcomes.** The outcome (merged) looked right. The command
   (go half way) was the evidence.
4. **One source of truth for geometry.** The bay existed in three drawings and one physics model, and
   they disagreed. Training start poses, stop points, drawings and checks now share one module.
5. **Audit the learner as well as the reward.** The reward was fine; the PPO buffer was biased
   against the one action the fix required.
