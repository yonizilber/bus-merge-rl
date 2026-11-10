# History of problems

The [case study](CASE_STUDY.md) tells one story in full. This page is the rest of the list: the problems met
between the first prototype (early 2026) and today, why each happened, what was done and what it taught. Most of
them are not in the final code any more, but they explain why the code looks the way it does.

**Where this comes from.** The first nine months of the project were written down in the notes of the original
development repository (`bus_simulation`): the project diary, the fix log, the plans, the teleport reports and
the experiment baselines. That repository is separate and is not part of this one. Entries before October 2026
are taken from those notes as written, with their dates. **Their numbers were not re-measured here**, and a few of
the old notes were later found to describe code that did not exist (see case 20). The entries from October 2026
are measured in this repository and have an ID in the full bug list (`docs/reference/BUGS.md`).

**How to read the tables.** Each row is one problem: when it was found, what went wrong, the cause, what was
done, and the lesson. The last column names the source note.

## 1. Early training, March 2026

<!-- cards: Case -->

| # | What went wrong | Cause | What was done | Lesson | Source |
|---|---|---|---|---|---|
| 1 | In three training runs the policy never improved: the evaluation score was identical in every epoch for 100 epochs, and each run ended with a rollback to the old checkpoint | One crash on one seed, the same crash every epoch. The shield's late-overlap rule fired only below a 1.2 m gap, and a fast car covers that in two steps (0.1 s each). Widening it to 2.5 m still missed a case with a 2.6-3 m gap | The shield was widened and the training scenarios made harder. | A failure that repeats identically on one seed is a design problem, not a learning problem; no amount of PPO fixes it | `ROBUSTNESS_PLAN`, runs 1-3 (2026-03-30) |
| 2 | 4,910 "emergency stops" in 240 episodes (about 20 per episode) | A deadlock: the bus starts to merge, the car behind it brakes almost to zero and stops 0.2 m away, the shield answers with an emergency stop, the bus stays put, the car stays put. Both frozen | The shield now tells a passing car (speed 2 m/s or more: hold) from a deadlock (slower: creep forward). Emergency stops fell to 97 | A rule that freezes the bus can deadlock with a rule that freezes the car. | `ROBUSTNESS_PLAN`, run 1-2 |
| 3 | Good scores on three evaluation seeds (120 of 120) and worse on six (229 of 240) | Mild overfitting to a few fixed seeds. On 10 held-out "validation" seeds the result was 378 of 400 (94.5%), about the same | The set of evaluation seeds was widened. | This is where the idea of seeds that are never used for training or selection comes from, which is now the rule for every published number | `ROBUSTNESS_PLAN` |

## 2. Realism problems found by looking, April to May 2026

<!-- cards: Case -->

| # | What went wrong | Cause | What was done | Lesson | Source |
|---|---|---|---|---|---|
| 4 | The bus's heading showed 0° in every frame of the telemetry | The bus used the car's steering routine, which rewrote the bus's sideways speed after the merge logic had set it | First a workaround, then the proper fix: a flag that skips the car steering routine for the bus while it merges |  | `DIARY` (2026-04-15), `STATUS` audit |
| 5 | The 2D view drew the bus 1 m below the lane centre | The renderer used `presence_factor`, a lane-overlap ratio (0.71 for a centred bus), as if it were a coordinate | The drawing reads the logged sideways position. | Never use a derived ratio as a position | `DIARY` (2026-05-20) |
| 6 | A sudden speed drop when the bus started to brake into the bay, and an S-shaped path into the bay | The first frame asked for an IDM braking of -3 m/s² (a jerk in the telemetry), and the entry ramp reached 3.15 m of sideways offset within 20 m | A -1.5 m/s² floor and a 50 m ramp. (A third suspect, a "virtual leader leaking into the cars' IDM", was checked and was not a bug) | Check the suspect before fixing it: the third suspect was not a bug. | `DIARY`, Phase 5 |
| 7 | In a 240-episode crash study, all crashes were in the harder scenarios, in two kinds | **Frozen sitting duck (about 60%):** the governor held the bus with the bus already partly in the lane, and a car drove into it. **Escape too late (about 40%):** the governor commanded an escape at 53-61% progress, but the bus gains only 0.2 m/s per step and the car closes at 5-10 m/s | The governor got a retreat command and its look-ahead was raised from 1.0 to 2.5 s. The planned boost of the acceleration limit during an escape was never done | A rule that holds the bus half out into the lane is as dangerous as no rule. | `DIARY` (2026-05-24), `PROJECT_PLANS` G1, G2 |

## 3. The gap between training and the app, late May 2026

For weeks the trained brain looked fine in training and poor in the Streamlit app (a 36 s average wait for a
merge, against 18 s in training). The investigation of 2026-05-26 and 27 found six separate causes. Each is a
case of the same pattern, called [[parity|parity]] in the glossary.

<!-- cards: Case -->

| # | What went wrong | Cause | What was done | Lesson | Source |
|---|---|---|---|---|---|
| 8 | The bus undershot every speed target | The brain was trained with a top speed of 11.1 m/s (40 km/h), the app had a hard-coded 8.33 m/s (30 km/h) | One shared constant. | A constant that two files share must be imported, never copied | `DIARY` (2026-05-26, bug 1) |
| 9 | The governor, when a car approached mid-merge, steered the bus back into the bay, erasing its progress | A safety rule that also changed an unrelated output (steering). The trained brain learned that a merge is always abandoned | The governor now holds (no gas, steering kept) and does so in both worlds | A safety rule should not change an output it is not about. | `DIARY` (bug 2) |
| 10 | The brain refused to move at the start of the merge | The app started the merge with the bus pointing 1.94° into the bay, training with 0°. That flipped the sign of the brain's `gas` output at the first step (-0.033 instead of +0.002). Found by feeding the exact input to the network by hand | The heading was reset at the start of the merge. (In October this reset itself was removed, and the merge starts from the pose the bus actually stopped in) | A difference in the very first step is the hardest parity bug. Probe the network with the exact input to find it. | `DIARY` (bug 3) |
| 11 | The brain waited for a completely empty road | Training scenarios had cars at 0-8 m/s, the app has 13 m/s traffic, so "a fast car means do not move". The arithmetic matched: a clear window appears 16% of the time, two are needed, so a wait of about 32 s, observed 36 s | A new training scenario with fast traffic | Check the arithmetic: here it predicted the observation almost exactly. | `DIARY` (bug 4) |
| 12 | Cars never yielded to the merging bus in the app, but did in training | The app made cars ignore the bus for the whole merge. The brain had learned to creep, which works only if cars yield | Cars yield from 20% progress. | Close the training-to-app gap before blaming the brain; here the brain was rational | `DIARY` (2026-05-27) |
| 13 | The brain found an exploit: always request a steer above the governor's threshold, get held, never move, never crash | The governor's hold cost nothing, so "always held, all timeouts" had no crashes. Training collapsed at epoch 20 | A penalty of 4 × the steer request when held | A safe action that costs nothing becomes an exploit. | `DIARY` (fix 6) |

## 4. The era of corrections, June to July 2026

The cars sometimes passed through each other or the bus, and every fix added a correction on top of the last.

<!-- cards: Case -->

| # | What went wrong | Cause | What was done | Lesson | Source |
|---|---|---|---|---|---|
| 14 | Cars coasted at full speed on first seeing the bus; every car treated the bus as its leader; cars panic-braked 40-50 m away; cars drove through the merging bus; cars stacked at one position | Stacked yield layers, a "look-through" bug (a car ignored the bus and followed the car ahead of it), a gap of zero or less being treated as "no leader" | A series of fixes to the yield logic (versions v1 to v2.6), ending in one continuous blend | Stacked layers of yielding each add their own braking. | `MERGE_FIXES_LOG` (2026-06-03 to 06-07) |
| 15 | **The teleports.** A car jumped back 2 m at t = 46.8 s; another 6 m at 40.4 s; another 12 m at 39.2 s; the bus 4.5 m back at 42 s | Four different mechanisms, found in four reports: a stop-hold that snapped the car to the leader's bumper line (`position = min(position, max_front)`), the bumper line itself moving as the bus turned, a stale monotonic position, and a car alongside the bus mistaken for one ahead. **Each fix left the next path open.** | Four reports and versions v2.3 to v2.8. Only in October 2026 were all the position assignments deleted, with the safe-speed law | Fix the mechanism that allows the symptom (assigning positions), not one symptom at a time. | `CAR_TELEPORT_REPORT`, T40, `FIX_REVIEW`, `BUS_TELEPORT_T42`; BUGS P7 |
| 16 | A car went from 13.5 to 4.3 m/s in 0.1 s while its IDM acceleration was only -8.6 m/s² (the app called it an "accel paradox") | Two systems changed the speed one after the other: the IDM and the bumper cap. The bus was not a leader while in the bay and then suddenly became a full one | A virtual blinker (cars see the bus faintly during boarding), a rate limit on the yield, and three physics modes. The paradox was removed at its root with the one safe-speed law | Two systems changing one quantity produce a paradox. Keep one. | `PHYSICS_ENFORCEMENT_ARCHITECTURE`; BUGS P7 |
| 17 | The shipped checkpoint was a do-nothing bus, and a 200-epoch retrain gave 0% evaluation success | Five root causes. The main one: the "best checkpoint" selector saved a policy with 0 successes as best (a skipped baseline evaluation left the best score at -1). Others: a retrain bootstrapped from a wait-policy, a reward with too many conflicting terms, training and app maintained by hand | The selector requires at least one success. The app got a "Validate brain" button that runs a production smoke test. | Judge a checkpoint in the app, not by the training metric | `PPO_FIX_PLAN` (2026-06-02) |
| 18 | The brain merged only when it saw no car at all (the gap at success was always 999 m) | Training scenarios cleared the road within 18-26 s, so waiting always worked | Six redesigned scenarios in which the road never clears, a penalty for idling and a timeout penalty that grows with idleness | A training set in which waiting always works teaches only to wait. | `PROJECT_STATUS` (2026-05-25) |
| 19 | "9 of 30" on the final validation of both v8 and v9, while the app showed 10 of 10 | The training environment started with a queue of cars that sometimes overlapped the bus at the first step, so the run crashed at progress 0. A property of the training environment, not of the app | An experimental "spongy" v10 profile that punished overlap gradually. Not adopted. In October the number was traced to a crash rule that counted a car merely passing the bay as a collision (H4), and the two physics implementations were merged into one | A validation number from a different environment says little about the app. | `EXP7SAT_V8`, V9, V10 |
| 20 | The documents described code that did not exist | A full audit on 2026-07-26 found a feature table in the wrong order, a Weber-law noise formula with no such symbol in the code, a "Truck" class that does not exist, and a fix listed as open that had shipped. It also found four real bugs (a shield lunge overriding a governor hold, a bumper-cap order that differed between training and app, a reward curriculum that was never read, and a reward dead zone for overlaps below 1 m²) | The status document was rewritten against the code. | Documents drift; generate numbers and tables from the source | `PROJECT_STATUS` (2026-07-26) |

## 5. This repository, October 2026

From here on every problem was measured and fixed in this repository, with a test. The full list with evidence
is `docs/reference/BUGS.md`; these are the turning points.

<!-- cards: Case -->

| # | What went wrong | Cause | What was done | Lesson | ID |
|---|---|---|---|---|---|
| 21 | Training and the app disagreed on what a collision is, what a merge is and what the world looks like | Two implementations of the same physics | The training environment steps the app's own engine; one observation builder; one episode harness | One engine for training and for the app. | P1, H3, H4, H5 |
| 22 | The drawing and the crash test were shifted by half a vehicle length | The physics put the position at the front bumper, the drawing at the centre | One function builds every vehicle's body outline. A hidden overlap of 0.24 m² became visible | Define every convention once. | P2 |
| 23 | Every run contained impossible braking (the bus at about -50 m/s², cars at 16-24 m/s² right after appearing), and 68 of 100 runs braked beyond 9 m/s² | `velocity = 0` on arrival, a "crawl" floor, speed caps of up to 2.4 m/s per frame, position trims, frozen stops | Braking planned by physics, spawn speed from the safe-speed law, and **all** corrections removed in favour of one law. A failure is now a recorded collision | Plan braking by physics instead of assigning stops. | P3, P4, P7 |
| 24 | The app showed "merged in -36 s" | The merge was searched from time 0, and the bus starts in the lane | The search starts after boarding | Search for an event only after the state that can produce it. | H2 |
| 25 | Six hidden clamps. Removing them showed that the bus crossed the centre line in 100% of runs | The steering had no heading term and overshot every target; the agent had learned to rely on it | **The case study.** Pure pursuit, then a retrained brain (v13) | Look at the agent's commands, not only the outcome. | P10-P13, P16-P18 |
| 26 | The kerb could cut into the bus's side without the checker noticing | Only the four body corners were compared with the road edge | The kerb corners are tested against the body | The checker needs tests too. | P14 |
| 27 | Tables of results in four places went stale (the app still showed a result that had become false) | Hand-typed copies | All published numbers are generated from stored per-seed measurements, and a test fails if any page differs | Generate numbers; never type them. | H16 |
| 28 | Four things found by clicking through the app | No banner for leaving the road; a merge-zone view that ran to 231 s; a governor panel listing "disabled" frames as decisions; a "PPO + Governor" label with the governor off | Fixed, and the view now ends when the bus leaves the frame | Click through the app: the tests did not see these. | H15, H17, H18, H19 |
| 29 | The "400 seeds" nightly gate was described as 400 different seeds | It is 400 runs on 250 seeds (the four inflow levels reuse the same 50 seeds) | Corrected in these pages | Check how a number is counted before repeating it. | (docs) |
| 30 | Two limitations that a single lane did not show: the cars' steering law overshoots every target, and the IDM acceleration functions change state | The cars use the first controller of the bus, with no heading term (`atan2(lateral_error, max(v, 5))`), and their only sideways move is a 0.5 m nudge; the engine asks for an acceleration once per car per frame | Found by the project owner while researching a multi-lane extension; measured here (a 0.5 m step overshoots by 100%, a 3.5 m step reaches 34-39° of heading) and shown to cause most of the cars crossing the centre line (62% of runs, 6% without the nudge). Documented, not fixed | A defect that small inputs hide is still a defect: the same pattern as the bus steering, found in the cars. The cause of a symptom that was explained as "realism" had never been tested | O21, O22 |

## 6. Patterns

1. **Two copies of one thing drift apart.** A constant, a physics rule, a bay outline, a published number. Cases 8,
   9, 10, 12, 21, 22, 27. The remedy is one definition and a test that reads it.
2. **A correction hides a failure.** The bumper caps, the position snaps, the clamps, the pose reset. Cases 15, 16,
   23, 25. The remedy is to check and report, never to assign.
3. **Fix the cause, not the symptom.** Four teleport reports and six versions fixed the same symptom in turn. Case 15.
4. **Measure what the user sees.** A training metric said 0% while rollouts merged, and a validation said 9 of 30
   while the app said 10 of 10. Cases 17, 19.
5. **Look at the agent's commands, not just the outcome.** The outcome was "merged"; the commands said "go half
   way". Case 25.
6. **The documents are part of the system.** Cases 20, 27.
