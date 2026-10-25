# Glossary

The terms that the other pages underline with a dotted line. Hover over one (or tab to it) for a one-line
explanation; click it to pin the explanation and to expand it into the technical detail: the equations and how this
project implements them. The note at the bottom of each page has the same text, and its title leads back to the
place in the text you came from. This page has all the entries, fully expanded.

Common terms (reinforcement learning, reward, seed, and so on) are not defined here.

## Acceptance gate {#acceptance}
> A script that runs 100 episodes and fails a brain that merges too slowly, collides, or breaks any physical check.

`scripts/acceptance.py` runs 100 episodes at perception noise 0 and 0.15 on the same engine as the app. A brain passes
when it merges in every run (at least 98 with noise), has no collision, and its mean merge time is at most 15.0 s with a
95th percentile of at most 20.0 s. No shipped brain passes it yet: v13 meets the time limits but not the contact and
road-edge criteria.

## Actor-critic network {#actor_critic}
> The agent's neural network: an actor that chooses the two actions, and a separate critic that estimates how good the situation is.

The actor is the policy; the critic only helps training (it estimates the expected return, used to judge actions). When
the brain drives in the app or in a measurement, only the actor is used and it acts on its mean, so the same state always
gives the same action.

<!-- details -->
**Architecture** (`busmerge/rl/ppo_agent.py`). With $n$ inputs (11 for every brain that merges):

- **Actor trunk:** $n\to64\to64$ with $\tanh$ activations, shared by two heads.
- **Mean head:** $64\to2$ followed by $\tanh$, so each action mean lies in $[-1,1]$: the sideways target `steer` and the speed target `gas`.
- **Spread head:** $64\to2$ giving $\log\sigma$, clamped to $[-3,\,0.5]$ (so $\sigma\in[0.05,\,1.65]$). The spread depends on the state: the agent can be sure in familiar situations and keep exploring in new ones. It starts at $\sigma\approx0.5$.
- **Critic:** a separate network $n\to64\to64\to1$ (also $\tanh$) that outputs the expected return $V(s)$.

**The policy.** Each action is drawn from a Gaussian, $a\sim\mathcal N\big(\mu(s),\sigma(s)^2\big)$, during training. At run time the agent uses $a=\mu(s)$. The vehicle receives the action clipped to $[-1,1]$, but the training buffer stores the raw sample with its own log-probability (otherwise the PPO ratio is wrong at the limits; see the history of problems, case 25).

**A deliberate bias.** The bias of the `steer` mean is initialised to $+1$, so before any learning $\tanh(1)\approx0.76$: the untrained agent steers into the lane. Learning then has to teach it to hold back when a car is near, which has a direct gradient (a contact costs a lot), instead of having to discover the first successful merge by chance.

**Why two networks.** The critic's job (predict a value on the reward scale, which reaches thousands) and the actor's job (choose actions) need different features and scales; separating them avoids one overwhelming the other.

## Bicycle model (kinematic) {#bicycle}
> A car reduced to two wheels, the front one steering: the heading turns at speed × tan(steering angle) / wheelbase.

Every car and the bus move sideways this way. The steering angle changes the heading, the heading changes the sideways
position, and steering is limited in angle and in rate, so a vehicle cannot jump sideways. "Kinematic" means that only
geometry is modelled, with no tyre forces or mass.

<!-- details -->
**The model.** Let $\psi$ be the vehicle's heading relative to the road, $y$ its sideways position, $v$ its speed, $L$ its wheelbase (the distance between the axles) and $\delta$ the steering angle of the front wheel. Then

$$\dot\psi=\frac{v}{L}\tan\delta,\qquad \dot y=v\sin\psi .$$

A larger angle or a higher speed turns faster; a longer wheelbase turns slower. A vehicle moving straight ($\delta=0$) keeps its heading, and so keeps drifting sideways if $\psi\neq0$. This is why it matters to steer by the heading and not only by the sideways error (see [[pure_pursuit|pure pursuit]]).

**The steering wheel is not instantaneous.** The controller asks for an angle $\delta^{*}$, but the wheel turns at a bounded rate $r$ and within a bounded angle $\delta_{\max}$:

$$\delta_{k+1}=\delta_k+\operatorname{clip}\!\big(\delta^{*}-\delta_k,\;-r\,\Delta t,\;r\,\Delta t\big),\qquad |\delta^{*}|\le\delta_{\max}.$$

This delay is part of what makes a badly designed controller overshoot.

**How we implemented it.** One function, `Vehicle.apply_steering`, moves every vehicle in every state, one step of $\Delta t=0.1$ s at a time: limit $\delta$ by the rate, update $\psi\mathrel{+}=\frac{v}{L}\tan\delta\,\Delta t$, set $\dot y=v\sin\psi$ and integrate. Progress along the road uses the speed only ($x\mathrel{+}=v\,\Delta t$).

| | Wheelbase $L$ | Steering limit $\delta_{\max}$ | Steering rate $r$ |
|---|---|---|---|
| Cars (five classes, per driver) | 2.6 - 2.9 m | 30° - 40° | 60 - 120 °/s |
| Bus | 7.0 m | 15° | about 25 °/s (drawn per run, 18 - 33) |

**Nothing is clamped.** The heading and the sideways position can take any value; if a vehicle steers off the road, the [[invariants|physics checks]] report it. Earlier versions clamped them, which hid the overshoot described in the case study.

**A simplification (limitation O11).** The body outline is drawn and tested rotated about its centre, whereas a real bus pivots near its rear axle, so the swing of the tail is exaggerated. It limits how sharply the bus may leave the bay.

## Brain {#brain}
> The trained network, stored as a `.pth` file (a checkpoint). Names such as v13 identify versions.

A brain contains the actor-critic weights. The number of inputs (4, 7 or 11) is read from the file itself. All the brains
that merge in this project use 11.

## Clamp {#clamp}
> A correction by assignment: "if the value is beyond the limit, set it to the limit". It hides a problem instead of exposing it.

Clamps are why a bus could cross the centre line without any check noticing. The simulation used to have six of them on
positions and headings; all were deleted and replaced by checks that report the violation.

## Contact judge {#contact_judge}
> The test that decides whether two vehicles touched: the exact overlap area of their body polygons.

Training and the acceptance gate use the same judge, with the same threshold (an overlap of more than 0.01 m² counts as
contact) and the same order of precedence (contact is judged before success).

<!-- details -->
**Bodies.** Each vehicle is a rectangle (length × width) placed with its front bumper at $x$, shifted sideways by its position *including lane drift*, and rotated by its heading. One function, `geometry.vehicle_corners`, builds the four corners for the app, the drawing, the checks and the training reward, so they cannot disagree.

**Overlap area.** The polygon of one body is clipped successively by the four half-planes of the other (the Sutherland-Hodgman method), and the area of what remains is computed with the shoelace formula:

$$A=\tfrac12\Big|\sum_{i}\big(x_i\,y_{i+1}-x_{i+1}\,y_i\big)\Big| .$$

**Threshold and order.** $A>0.01\ \mathrm{m^2}$ counts as contact. In training, contact ends the episode with a large penalty and is judged *before* success, exactly as in the acceptance gate: a merge that touches a car is not a success. Earlier, training judged only the nearest car and without lane drift, and its threshold differed from the gate's; that is why they disagreed on what a collision is.

## Golden test {#golden}
> A test that stores a fingerprint of a run with a fixed seed and fails if a later change alters it.

The fingerprints are in `tests/golden/`. They protect a refactoring: if the engine or the training environment behaves
differently by even a tiny amount, the test shows it. A golden file may be regenerated only when the change is intended
and explained.

## Governor {#governor}
> A rule layer that can veto the agent's merge when a car is closing fast. Switched off by default.

It projects the closing speed of the nearest car forward and can hold the bus, block the merge steering, retreat, or
command an escape. The shipped brains were trained without it, so it is off in the app. The
[[shield|safety shield]] is separate and is always on.

<!-- details -->
**Inputs.** The agent's `steer` and `gas`, the merge progress $p$, the gap $g$ and relative speed to the nearest car, and the closing speed $c=\max(0,-\dot g)$ ($\dot g$ is the relative speed). It returns either the command unchanged or a replacement, and a reason.

**Rules, in order** (`busmerge/rl/governor_logic.py`):

1. **Clear road:** no car within the scan window, or $g\ge50$ m: do nothing.
2. **A car alongside** ($g<0$: its front is already beside or ahead of the bus's rear). Before progress 0.85: block the sideways steering (keep the gas). If the bus is closing on it and has progress above 0.05: retreat (`steer`$=-1$). Otherwise hold the sideways position.
3. **Committed merge** ($p>0.5$): if the projected gap after $T=2.5$ s, $g-cT$, is $\le0$, or the braking that would be needed, $c^{2}/2(g-cT)$, exceeds 9 m/s², command an escape (`steer`$=+1$, `gas`$=+1$).
4. **Early merge:** only when the agent steers into the lane (`steer` $\ge0.15$): hold (no gas) if the braking needed now, $c^{2}/2g$, exceeds 9 m/s², if the gap would close within $T=1$ s, or if the braking needed at that point exceeds 9 m/s².

The governor is a design choice for safety; the shipped brains work without it, and a hold is penalised in training so that the agent does not learn to depend on it.

## "Hand of God" corrections {#hand_of_god}
> The old physics layer that kept cars apart by assignment: speed caps, position trims, frozen stops.

Under it, 68 of 100 acceptance runs contained braking beyond 9 m/s² and a contact the physics could not avoid was hidden.
Replaced on 2026-10-10 by the [[safe_speed|safe-speed law]]; the old code is at the git tag `legacy-hand-of-god`.

## IDM (Intelligent Driver Model) {#idm}
> A car-following model: acceleration depends on the car's speed, its desired speed, and the gap and speed difference to the car ahead.

Treiber, Hennecke and Helbing proposed it in 2000. Every car in the simulation is an IDM driver with its own parameters,
and the bus follows the same model when it drives in the lane.

<!-- details -->
**The model.** For a car with speed $v$ whose leader is a gap $s$ ahead (bumper to bumper) and drives at $v_\ell$:

$$a=a_{\max}\left[\,1-\left(\frac{v}{v_0}\right)^{\delta}-\left(\frac{s^{*}}{s}\right)^{2}\right],\qquad s^{*}=s_0+vT+\frac{v\,\Delta v}{2\sqrt{a_{\max}\,b}},\qquad \Delta v=v-v_\ell .$$

- $v_0$ is the speed the driver wants on an empty road, $a_{\max}$ the strongest acceleration, $b$ the comfortable braking, $T$ the time headway, $s_0$ the minimum gap, and $\delta=4$ sets how sharply acceleration fades near $v_0$.
- The term $1-(v/v_0)^{\delta}$ is the *free-road* part: accelerate until $v_0$.
- The last term is the *interaction* part. $s^{*}$ is the gap the driver wants at this speed: the standstill gap $s_0$, plus the distance covered during the headway $vT$, plus a braking term that grows when the car is closing in on its leader ($\Delta v>0$). When the real gap $s$ is smaller than $s^{*}$ the term exceeds 1 and the car brakes, the harder the closer.

**How we implemented it.**
- **Parameters** are drawn per driver around the means of five classes (see the table on the How it works page): $v_0$ 13.0 - 15.5 m/s, $a_{\max}$ 1.7 - 2.8 m/s², $b$ 1.8 - 2.5 m/s², $T$ 1.0 - 1.7 s, $s_0=2$ m, $\delta=4$.
- **Reaction time.** A driver recomputes the acceleration only every reaction time (0.35 - 0.58 s, plus or minus 0.1 s) and holds it in between. The result is never below $-9$ m/s².
- **The bus changes the situation.** While the bus pulls out, the minimum gap is enlarged to $s_0+3.5\,\min(p/0.22,\,1)$, where $p$ is the bus's presence (the share of the lane it covers, multiplied by 1.15 while merging), so cars leave more room. Cars also move over sideways by up to 0.5 m (times their politeness), and brake softly when the lane narrows.
- **Yielding blend.** While the bus merges, a car's acceleration is $a=(1-Y)\,a_{\text{free}}+Y\,a_{\text{IDM(bus)}}$, the free-road acceleration against the IDM with the *bus* as leader. $Y\in[0,1]$ grows with how far the bus has entered the lane and falls with the distance to it (ignored beyond 50 m). It may change by at most 0.5 per second (the "surprise filter"), so the start of a merge cannot cause a one-frame emergency stop. During the last 3 s of boarding a faint "virtual blinker" gives $Y$ a small value, so cars begin to ease off.
- **The IDM is a driver model, not a safety guarantee.** Between two recomputations a car can close in on its leader. The [[safe_speed|safe-speed law]] therefore limits the acceleration the IDM asks for.
- **A known limitation (O22): the functions are not pure.** Computing the acceleration also writes the squeeze flag (`is_squeezing`, through a Schmitt trigger) and the yield limiter (`last_applied_yield`), and a driver's reaction timer advances in the physics step. That is harmless while the engine asks once per car per frame, but it prevents "what-if" queries (what would my acceleration be in another lane?), which a lane-change model needs.

## Invariants (physics checks) {#invariants}
> Checks run on every simulated run for moments that cannot happen in reality.

A run is not judged only by its outcome. `busmerge/invariants.py` goes over the whole frame log and reports every
impossible moment. Cars crossing the centre line or the kerb are reported but not failed (mostly the overshoot of their steering
law when they move over for the bus, limitation O21).

<!-- details -->
| Check | Fails when |
|---|---|
| Braking | deceleration beyond 9.5 m/s² (the 9 m/s² limit plus a tolerance) |
| Acceleration | beyond 5 m/s² |
| Speed | negative |
| Backward motion | the position decreases |
| Position jump | $\big|\Delta x-v\,\Delta t\big|>0.5$ m |
| Overlap | any overlap between two bodies ([[contact_judge|contact judge]]) |
| Off the road | a bus corner below the kerb or the bay wall, or a kerb corner inside the bus body (tolerance 0.02 m) |
| Over the centre line | a bus corner in the opposing lane |
| Extreme heading | beyond 60° |

The position-jump check compares the actual displacement to what the speed explains. It would catch the "teleports" of the early versions: a displacement that the speed does not account for. The road-edge checks use the exact outline of the road and the bay, including the kerb corners, and were verified against a brute-force walk of the outline at 1 cm.

## Jerk {#jerk}
> The rate of change of acceleration, in m/s³. A real brake needs time to build up force, so jerk is bounded.

The test suite checks that jerk stays within bounds. One known limitation is that braking can start with a jerk of about
100 m/s³, where a real brake system gives 30 - 60 (see the limitations page).

<!-- details -->
$$j=\frac{\mathrm{d}a}{\mathrm{d}t}\;\approx\;\frac{a_{k+1}-a_k}{\Delta t}.$$

With $\Delta t=0.1$ s, an acceleration that goes from $0$ to $-9$ m/s² in one step has $j=90$ m/s³. A real braking system needs roughly 0.15 - 0.3 s to build up force, i.e. 30 - 60 m/s³. The simulation has no such lag, so the strict xfail test (limit 50 m/s³) documents it as limitation O18. Typical car jerk (99th percentile) is about 2 m/s³, so the problem is rare: about 25 frames in 5 runs.

## Kerb corner {#kerb_corner}
> The point where the bay's exit taper meets the plain kerb. It points into the road.

If the bus steers out too slowly from the far end of the bay, this corner cuts into the bus's side. The checker first
missed it, because it compared only the four body corners with the road edge. Now the kerb corners are tested against the
body too.

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

One function, `busmerge/rl/observation.py::build_observation`, builds it for both the app and training. The full list,
with ranges and scaling, is on the [How it works](HOW_IT_WORKS.md) page.

## OU process (Ornstein-Uhlenbeck) {#ou}
> A random wobble that is pulled back toward its centre: slowly varying noise, not jitter. Used here for lane drift and for perception errors.

A pure random walk wanders off without limit. The Ornstein-Uhlenbeck process adds a pull toward the centre that grows with
the distance, so the value wobbles around the centre, with a typical size and a memory of a few seconds. That is what a
driver's imperfect lane keeping looks like, and what a persistent misjudgement of a distance looks like.

<!-- details -->
**The equation.** For a quantity $X$ (a sideways error in metres, or a perception bias):

$$\mathrm{d}X=-\theta\,X\,\mathrm{d}t+\sigma\,\mathrm{d}W .$$

$\theta$ (1/s) is the strength of the pull toward 0; $\sigma\,\mathrm{d}W$ is random kicks (a Wiener process, white noise). The process has a *stationary* distribution, with standard deviation $\sigma/\sqrt{2\theta}$, and forgets its past with a time constant $1/\theta$.

**In the simulation** (step $\Delta t$, $\xi_k\sim\mathcal N(0,1)$, Euler-Maruyama):

$$X_{k+1}=(1-\theta\,\Delta t)\,X_k+\sigma\sqrt{\Delta t}\;\xi_k .$$

It is used three times:

1. **Lane drift of every vehicle.** $\theta=0.4$ s⁻¹, and $\sigma$ is the class's lane-keeping noise (Compact 0.06, Mid 0.08, Large 0.10, SUV 0.09, Aggressive 0.15 m/√s; the bus about 0.01). The typical size is therefore $\sigma/\sqrt{2\theta}\approx1.1\,\sigma$ (about 7 cm for a Compact, 17 cm for an Aggressive driver), with a memory of $1/\theta=2.5$ s. The drift is added to the sideways position, `total_lateral_offset`, which is what the contact judge and the road-edge checks use.
2. **The bus's active lane correction.** $\theta=0.5$ s⁻¹, $\sigma=0.03$, limited to ±0.10 m. Here the wobble is added to the *target line* of the bus, so the [[pure_pursuit|pure-pursuit]] controller actively steers to correct it, which gives small natural oscillations instead of an invisible shift. Active only while driving in the lane; it fades out during the bay entry and the merge so that they are precise.
3. **Perception noise of the agent**, see [[noise|perception noise]]: one bias per input, with the parametrisation $b_{k+1}=b_k-\kappa\,b_k\,\Delta t+\sqrt{2\kappa}\,\sigma_c\sqrt{\Delta t}\,\xi_k$, which makes the stationary standard deviation exactly $\sigma_c$ (and $\kappa=0.35$ s⁻¹).

**Why not white noise?** Independent noise at every step averages out over a few steps, and the agent would not have to be robust against anything. Real errors persist for seconds, which is what the OU memory gives.

## Overshoot {#overshoot}
> A vehicle passes its target line before settling on it.

The original merge steering overshot every target, and the agent learned to rely on it. See the
[case study](CASE_STUDY.md).

## Parity (training and production) {#parity}
> Training and the app must run the same physics, observation and rules, otherwise the agent learns a world that does not exist.

Most of the early problems in this project were parity bugs: a different speed limit constant, a different heading at the
start of the merge, cars that yielded in training but not in the app. Now the training environment steps the app's own
engine, and a test checks that the two agree bit for bit.

## Perception noise {#noise}
> Errors added to what the agent perceives, growing with distance, so that it cannot rely on exact numbers. Optional; off in the app.

Only the agent's input is noisy; the physics checks, the governor and the shield always see the truth. The bus's own
progress and heading are never noisy. The acceptance gate covers noise 0 and 0.15.

<!-- details -->
**Purpose.** A real driver does not know exact distances and speeds. Far objects are vague and near ones sharp, the speed of an approaching car is hard to judge until it is close, and errors persist for a few seconds. Training and testing with such errors makes the agent robust to them, and tells us how much it relies on precise numbers.

**The form.** Each input $c$ (gap, lateral clearance, car speed, ...) the agent receives is the true value plus a bias $b_c$, and the biases are [[ou|OU processes]]:

$$b_{c,k+1}=b_{c,k}-\kappa\,b_{c,k}\,\Delta t+\sqrt{2\kappa}\;\sigma_c\sqrt{\Delta t}\;\xi_k,\qquad \kappa=0.35\ \mathrm{s^{-1}},$$

with stationary standard deviation $\sigma_c$ and a memory of about 3 s. The biases are reset when the nearest car changes.

**The size $\sigma_c$** depends on the noise level $k$ (0 = off, 0.15 and 0.30 are used) and on the gap $g$ to the nearest car. With $d_{\rm lin}=\operatorname{clip}(|g|/50,\,0.05,\,1.2)$ and $d_{\rm spd}=\max\!\big((|g|/50)^{2},\,0.04^{2}\big)$:

| Input | $\sigma_c$ |
|---|---|
| gap | $10\,k\,d_{\rm lin}$ m |
| lateral clearance | $6\,k\,d_{\rm lin}$ m |
| car speed, relative speed | $5\,k\,d_{\rm spd}$ m/s |
| car acceleration, relative acceleration | $12\,k\,d_{\rm spd}+1.5\,k$ m/s², then low-pass filtered with weight 0.15 per step |
| car heading | $2\,k\,d_{\rm lin}$ degrees |
| car width, length | $0.1\,k$ m |

So distances grow vague in proportion to distance, and speeds quadratically (a looming object is hard to judge from far, easy from near). The bus's own progress and heading are exact: it knows its own pose.

## Plant {#plant}
> In control engineering, the thing that is controlled. For the agent: the vehicle and its steering controller.

An RL agent learns to use the plant it is given, defects included. See the [case study](CASE_STUDY.md).

## PPO (Proximal Policy Optimization) {#ppo}
> A reinforcement-learning method that improves the policy in small, safe steps by limiting how far one update can move it.

A rollout of 2,000 steps is collected; then the network is updated several times on it. Each update compares how likely
every action is now with how likely it was when it was taken, and does not let that ratio move far from 1.

<!-- details -->
**Objective.** Let $\pi_\theta(a\mid s)$ be the policy, $r_t(\theta)=\pi_\theta(a_t\mid s_t)/\pi_{\theta_{\rm old}}(a_t\mid s_t)$ the probability ratio of the action taken at step $t$, and $\hat A_t$ the advantage (how much better the action was than expected). The clipped objective is

$$L^{\rm CLIP}=\mathbb E_t\Big[\min\!\big(r_t\hat A_t,\ \operatorname{clip}(r_t,\,1-\epsilon,\,1+\epsilon)\,\hat A_t\big)\Big],\qquad \epsilon=0.2 .$$

If an action was good ($\hat A>0$), the gain stops once $r_t>1.2$; if it was bad, the loss stops once $r_t<0.8$. So one update cannot move the policy far, even if the batch looks very promising.

**Advantage (GAE).** With discount $\gamma=0.995$, trace parameter $\lambda=0.95$, value estimate $V$ and the end-of-episode flag $d_t$:

$$\delta_t=r_t^{\rm rew}+\gamma\,V(s_{t+1})(1-d_t)-V(s_t),\qquad \hat A_t=\delta_t+\gamma\lambda\,(1-d_t)\,\hat A_{t+1}.$$

$\lambda$ trades bias against variance: 0 uses one step, 1 uses the whole future. The advantages are normalised over the batch (zero mean, unit variance) before they are used; the critic's target is $\hat A_t+V(s_t)$.

**Total loss** minimised with Adam (learning rate $5\cdot10^{-5}$, gradient norm clipped to 0.5), four passes over each 2,000-step rollout:

$$L=-L^{\rm CLIP}+0.5\,\big(V_\theta(s_t)-\hat R_t\big)^{2}-c_H\,H\big[\pi_\theta\big],$$

where $\hat R_t$ is the critic's target and $H$ the entropy of the policy. The entropy bonus $c_H$ keeps the agent exploring: 0.02, and at least 0.10 in the first phase of training.

**What is specific here.** The agent's action is clipped before it is sent to the vehicle, but the *raw* sample is stored with its own log-probability. Storing the clipped one made $r_t\neq1$ before the first update for every action at the limit, which is exactly the action the corrected steering needs (history of problems, case 25).

## Property-based test {#property_test}
> A test that states a rule ("never brakes harder than 9 m/s²") and lets a library try thousands of generated cases.

The `hypothesis` library does the generating, and when it finds a counterexample it shrinks it to the smallest case. It
found the minimum-gap intrusion of the safe-speed law (limitation O19).

## Pure pursuit {#pure_pursuit}
> A steering method: aim at the point on the target line a look-ahead distance ahead, in the vehicle's own frame, and steer along the arc that reaches it.

Because the formula includes the vehicle's heading, the vehicle steers back as it approaches the line and arrives
parallel to it, instead of crossing it. This is the controller that replaced the one that overshot every target.

<!-- details -->
**Geometry.** Let $e$ be the sideways distance from the vehicle to the target line, $\psi$ the vehicle's heading relative to the line, and $L_d$ the look-ahead distance. In the vehicle's own frame (forward, sideways), the point of the line that is $L_d$ ahead lies at a sideways offset

$$y_r=e\cos\psi-L_d\sin\psi .$$

A circular arc that starts along the vehicle's heading and passes through that point has curvature $\kappa=2y_r/L_d^{2}$ (using that the point is at distance $\approx L_d$). The [[bicycle|bicycle model]] follows an arc of curvature $\kappa=\tan\delta/L$, so the steering angle is

$$\delta=\arctan\!\left(\frac{2\,L\,y_r}{L_d^{2}}\right),\qquad |\delta|\le\delta_{\max},$$

and the wheel then turns toward it at its bounded rate.

**The heading term is the point.** The second term of $y_r$, $-L_d\sin\psi$, makes the vehicle steer back when its heading already points toward the line. Without it (the first merge controller used $\delta=\arctan\big(e/\max(v,5)\big)$) the loop has no damping: the heading is the integral of the steering and the position the integral of the heading, so the vehicle reaches the line still turned toward it, carries on past it, and only then corrects. That is the overshoot at the heart of the [case study](CASE_STUDY.md).

**How we implemented it.** `vehicle.pure_pursuit_steer`, one function, steers the bus in every state; only $L_d$ and the target line change:

| State | Look-ahead $L_d$ | Target line |
|---|---|---|
| Driving in the lane | 18 m | the lane centre, plus the small [[ou|OU]] perturbation |
| Pulling into the bay | 6 m | the drawn kerb under the bus's front (`geometry.bay_pull_in_target`) |
| Merging | 12 m | the sideways target the agent chose: `steer` mapped from $[-1,1]$ to $[-3.5\,\mathrm m,\,0]$ |

A shorter look-ahead while merging swings the rear corner into the bay wall (because the model rotates about the body centre). Cars use a simpler aim, $\delta=\arctan\big(e/\max(v,5)\big)$ limited to $\delta_{\max}$, since they only make small sideways moves (up to 0.5 m). **This law has no heading term and overshoots every target** (limitation O21): a 0.5 m move overshoots by 100%, a 3.5 m move by 99-100% with a peak heading of 34-39°, and neither settles. The small moves hide it today; it would show in a lane change.

## Rollback rule {#rollback}
> During training: after several evaluations without improvement, go back to the best checkpoint so far.

A fine-tune that starts with no successful evaluation has no "best" except its starting weights, so the rule threw away
every 30 epochs of learning. It is now a flag (`--rollback-patience`), and it only restores a checkpoint that evaluated
with at least one success.

## Safe-speed law {#safe_speed}
> One rule limits every follower's acceleration so it can still stop if its leader brakes. If even that is not enough, the vehicles touch and it is recorded.

Speed and position then follow from the acceleration; nothing is assigned. It replaced the old corrections
([[hand_of_god|"Hand of God"]]) and is the same idea as in the Gipps and Krauss car-following models (Krauss is the
default of the SUMO simulator).

<!-- details -->
**The idea.** A follower must always be able to stop behind its leader, even if the leader then brakes comfortably. Let $s$ be the free gap (the leader's rear bumper minus the follower's front bumper, minus the follower's minimum gap $s_0$), $v$ and $v_\ell$ the speeds, and $b$ the follower's comfortable braking. If both brake at $b$, the follower stops after $v^{2}/2b$ and the leader after $v_\ell^{2}/2b$, so they do not touch if $v^{2}/2b\le s+v_\ell^{2}/2b$, that is

$$v\;\le\;v_{\rm safe}=\sqrt{v_\ell^{2}+2\,b\,s}.$$

**The step limit.** Within one simulation step $\Delta t$ the follower must not close more than the gap: $v\,\Delta t\le s+v_\ell\,\Delta t$, i.e.

$$v\;\le\;v_{\rm frame}=v_\ell+\frac{s}{\Delta t}.$$

**From a speed limit to an acceleration limit.** The driver (the [[idm|IDM]], or the bus's plan) asks for $a_{\rm drv}$. The law lets the vehicle reach at most the lower of the two limits in one step, and never brakes harder than the tyres allow:

$$a=\max\!\left(\min\!\Big(a_{\rm drv},\ \frac{\min(v_{\rm safe},\,v_{\rm frame})-v}{\Delta t}\Big),\ -9\ \mathrm{m/s^{2}}\right).$$

Then $v\leftarrow v+a\,\Delta t$ and $x\leftarrow x+v\,\Delta t$. If even $-9$ m/s² cannot avoid contact, the vehicles touch and the [[contact_judge|contact judge]] records it: a failure is shown, not hidden.

**How we implemented it.** One module, `busmerge/safe_speed.py`, serves every follower: the cars; the bus back in the lane; and the merging bus, against the nearest car *fully ahead* of it (a car alongside does not count: that conflict is sideways, and avoiding it is the agent's job). The same function decides at what speed a new car may enter the road, so it is never born in a state that needs impossible braking. $b$ is the follower's own comfortable braking, and $\Delta t=0.1$ s. Gipps and Krauss add a driver reaction time to the formula; here the reaction time is already modelled in the IDM.

**A known limitation (O19).** Vehicles are updated leader first, but $v_{\rm frame}$ assumes the leader moves during the follower's step. A follower can therefore get up to 0.55 m into its own 2 m minimum gap in rare cases (never into contact). A property-based test found the smallest case.

## Safety shield {#shield}
> A rule layer, always on, that overrides the agent's command in dangerous moments (for example an emergency stop).

It looks at the nearest car's gap and closing speed. Its interventions are recorded and shown in the app, and in the
training reward every intervention is penalised, so the agent does not learn to lean on it.

<!-- details -->
**Where it sits.** After the agent's command and the [[governor|governor]], before the vehicle moves. It is skipped on a clear road (no car in the scan window, or a gap of at least 50 m). With $g$ the gap, $\dot g$ the relative speed, $p$ the merge progress and $w$ the nearest car's width:

- **Emergency stop:** if the agent steers into the lane and the gap would close within one step ($g\ge0$ and $g+\dot g\,\Delta t\le0$ while closing), stop the steering and the gas.
- **Very close** ($0\le g<0.5$ m): if the merge is under way ($p\ge0.3$), go forward and finish; otherwise an emergency stop (a slow creep if the car is nearly still, which avoids a deadlock).
- **Late overlap:** at $p>0.65$ with a gap under 1.2 m and a relative speed (bus minus car) above 0.2 m/s, or $p>0.75$ with a gap under 2.5 m and a relative speed above 1.5 m/s, push forward out of the way.
- **Adaptive gap:** with $g_{\min}=4+2.2\,\max(0,\,w-1.8)$ m, when $g<g_{\min}$ and the relative speed is above 1.2 m/s, scale the steering by $1-0.85\,\rho$, where $\rho=(g_{\min}-g)/g_{\min}$ (unless the gap is opening safely).
- **High pressure:** steering above 0.65 with a relative speed above 2.5 m/s within $g_{\min}+6$ m: scale the steering by 0.35.
- **Push through:** if the bus is alongside a car ($g<0$) and more than 60% merged, keep going (steer and gas at least 0.5).

## Single source of truth {#ssot}
> Every fact (a constant, a formula, a shape) is defined once, and everything else uses it.

The bay outline, the road edge, the steering law, the observation, the merge rule and the published numbers each have
exactly one definition. A copy is treated as a bug, because copies drift apart.

## Strict success {#strict}
> Merged, and in addition no physical anomaly: the bus stayed on the road, out of the opposing lane, with no contact or other violation.

It is the honest measure. For v13 it is 89.4% of 1,000 unseen runs, against 97.8% merged.

## Strict xfail {#strict_xfail}
> A test for a known limitation: it keeps its honest assertion, must fail on that assertion, and turns red the day the behaviour changes.

Deleting the test or loosening its threshold would hide the limitation. With strict xfail it stays in the suite, next to
the code, and it cannot silently start passing or break for another reason.

## Wilson interval {#wilson}
> A confidence interval for a percentage measured on a limited number of runs.

For 100 runs, a result near 97% has a 95% interval of about ±6 points in the worst case, so two results that differ by a
few points are not necessarily different.

<!-- details -->
For $n$ runs of which a fraction $\hat p$ succeeded, the 95% Wilson interval is

$$\frac{\hat p+\dfrac{z^{2}}{2n}\;\pm\;z\sqrt{\dfrac{\hat p(1-\hat p)}{n}+\dfrac{z^{2}}{4n^{2}}}}{1+\dfrac{z^{2}}{n}},\qquad z=1.96 .$$

Unlike the plain "$\hat p\pm z\sqrt{\hat p(1-\hat p)/n}$", it stays inside $[0,1]$ and behaves well near 0% and 100%, which is where most of our results are. `scripts/verify_brain.py` reports it for every outcome; with $n=1000$ and $\hat p=0.978$ the interval is about 96.7% - 98.6%.
