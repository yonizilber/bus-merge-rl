# Case study: the agent that merged by exploiting its steering

**Summary.** The default PPO agent merged in 97.9% of 1,000 unseen runs. When every hidden correction
was removed from the simulation, the same runs showed the bus crossing the centre line in 100% of
them. The cause was a steering controller that overshot every target. The agent had learned to rely
on that overshoot: it asked to go only half way out of the bay and let the defect carry it into the
lane. With the controller fixed, the agent merged in 0% of runs. Retraining also required fixing two
bugs in the training loop. The retrained agent, v13, merges in 97.8% of runs with no centre-line
crossing; 89.4% of runs are clean by every physical check. This document records how all of this was
found, fixed and measured.

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
drifting in their lane or moving over for the bus (mostly the latter, see limitation O21), is now reported but not failed (`InvariantReport.notes`).

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

**Two attempts that failed, and why.**
- **First attempt:** v11, the corrected start poses and PPO buffer, the unchanged reward, 3 seeds. The
  mean steer command at the half-way state rose from 0.06 to about 0.2, then fell back to v11's value.
- **Second attempt:** a stronger reward to finish the merge once out of the bay (below). Again it rose,
  and again it fell back.

The cause was the training loop, not the reward. After 3 evaluations without a new best (30 epochs),
the trainer restores the best checkpoint. A run that starts at 0 successes has no best except its
starting weights, so every 30 epochs of learning were thrown away. The same mechanism rolled the
earlier v12 fine-tune back 7-8 times in 31 evaluations. Rollback is now a flag (`--rollback-patience`,
0 = off).

**The reward change.** The per-step term that pays for steering toward the lane while the gap is safe
had weight 8. Once the bus is out of the bay (progress ≥ 0.15), the weight is now 30: finish what you
started. Inside the bay, and with a car within 6 m, nothing changed, so the brain still has a reason
to wait for a gap.

**Third attempt, rollback off, 300 epochs, about 45 minutes** (four runs in parallel). Mean steer at
the half-way state (v11: 0.06; about 0.94 reaches the lane):

| Run | Epoch 50 | Epoch 100 | Epoch 150 | Result at epoch 300 |
|---|---|---|---|---|
| weight 8 (original reward) | 0.24 | 0.34 | 0.36 | still half way (highest lateral -0.86 m) |
| weight 30 | 0.43 | 0.79 | 0.83 | the whole bus in the lane in every run |
| weight 60, two seeds | 0.48-0.51 | 0.57-0.58 | 0.62-0.63 | stops at -0.28 to -0.32 m |

**The threshold.** At epoch 300 the weight-30 brain put the whole bus inside the lane in every run,
but stopped at a median of -0.13 m. The threshold for "merged" was -0.10 m, so 75 of 100 selection
runs counted as stuck. A 2.5 m bus centred at -0.25 m is wholly inside the 3.5 m lane, 0.25 m clear of
the kerb. The project owner moved the threshold to -0.25 m, defined in one place
(`merge_success.py`) and used by the engine, the evaluation and training. The change turned all 75
stuck runs into merges and added no violation.

**Result: v13** (weight 30, epoch 300). It was selected on seeds 1000-1099 (100 merged, 0 contact,
91 strict) and measured on the 1,000 unseen seeds 2000-2999:

<!-- results:case_study_table (generated by scripts/publish_results.py; do not edit) -->
| | v11, old steering | v11, honest steering | **v13**, honest steering |
|---|---|---|---|
| Merged (judged on traffic) | 97.9% | 0.0% | 97.8% |
| Contact with a car | 2.1% | 0.8% | 2.2% |
| Stuck | 0.0% | 99.2% | 0.0% |
| Bus over the centre line | 100.0% | 0.0% | 0.0% |
| Bus off the road | 50.5% | 100.0% | 8.7% |
| **Strict success** | 0.0% | 0.0% | 89.4% |
| Mean / p95 time from end of boarding to merged | 4.9 / 5.5 s | – | 13.3 / 16.7 s |
<!-- /results:case_study_table -->

The first column is the archived measurement made before the steering fix (commit `7b59caf`, merge
threshold -0.10 m); the other two run on the current code. The table is generated from `results/`.

The merge rate on traffic is unchanged; what changed is that it is now physical. The merge takes
almost three times as long. Even a scripted merge at full throttle, steering at once, takes 6.3 s
under honest steering. So the acceptance limits of 6.0 s mean and 7.0 s p95, set while the steering
overshot, cannot be met by any policy and have to be re-derived.

**Remaining failures (the input for the known limitations).**
- **Exit kerb corner (8.7%).** From the far end of the stop range (about 306-307 m) the brain steers
  out slowly, and the kerb corner at the end of the exit taper cuts into the bus's side. Scripted
  exits from the same stops are clean, so this is the brain, not the geometry.
- **Contact with a car (2.2%).** Pulling out while a car is alongside, as with every earlier brain.
- **Tilted at the threshold (3 of 1,000 runs).** The bus passed -0.25 m while still turned, with a rear
  corner over the kerb line. -0.25 m means wholly in the lane only when the bus is nearly parallel.
- **Cars over the centre line (report only).** It happened in 60% of runs, up to 0.93 m (13.7% with
  v11 under honest steering). The slower merge makes cars move over for the bus for longer. **Later found (2026-10-25, BUGS O21):** most
  of it is the overshoot of the cars' own steering law, which has no heading term (the bug this case study
  describes for the bus). With the nudge off it drops to 6% of runs.

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
5. **Audit the learner and the training loop, not only the reward.** The reward ranked a full merge
   far above stopping half way. But the PPO buffer was biased against the one action the fix
   required, and a rollback rule silently reset every attempt to its starting weights.
6. **A ranking is not a gradient.** That the optimal policy earns the most says nothing about whether
   learning can get there from where the agent is. A probe of the policy's mean action on fixed states
   showed in minutes what the in-training success rate (0/30 throughout) could not.
