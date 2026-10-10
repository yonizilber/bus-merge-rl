import torch
import torch.nn as nn
import numpy as np
import random
import argparse
import os
import shutil
import time
from busmerge.paths import MODELS_DIR, REPO_ROOT
from busmerge.rl.env import BusMergeEnv


# Reward/crash-rule flags of the current run. train() sets them from the run tag so that the
# in-training evaluations judge episodes with exactly the rules the policy is trained under.
ENV_FLAGS = {"sat_penalty_enabled": False, "spongy_danger_zone_enabled": False, "commit_steer_weight": 8.0}
from busmerge.rl.ppo_agent import PPOAgent


def _ckpt_path(filename: str) -> str:
    return str(MODELS_DIR / filename)


def _agent_state_dim(agent) -> int:
    # ppo_agent uses actor_trunk; ppo_agent uses actor_mean.
    if hasattr(agent.policy, "actor_trunk"):
        return int(agent.policy.actor_trunk[0].in_features)
    return int(agent.policy.actor_mean[0].in_features)


def _configure_env_features(env, agent):
    dim = _agent_state_dim(agent)
    env.feature_dim = dim
    env.state_size = dim
    for flag, value in ENV_FLAGS.items():
        setattr(env, flag, value)


def evaluate_policy(agent, episodes=40, seed=123, verbose_shield=False, governor_disabled=False,
                    force_scenario_h=False):
    """Deterministic fixed-seed eval — rotates across all scenarios A-H for a balanced measurement.

    force_scenario_h=True pins every episode to Scenario H (bumper-to-bumper dense stream).
    Used for the 5 dense-stream fixed seeds so Gap@OK is meaningful: a brain that only waits
    for a 999 m clear road will score 0 % on these seeds and will not be promoted.
    """
    env = BusMergeEnv(eval_mode=True, governor_disabled=governor_disabled)
    _configure_env_features(env, agent)
    # _eval_scenario_seed is set fresh per episode inside the loop below.
    # Setting it once here caused all episodes to use the same traffic scenario
    # making eval results frozen across all epochs.
    import random as _rnd
    _rnd.seed(seed)
    # Pre-generate per-episode scenario seeds deterministically from the base seed.
    _episode_scenario_seeds = [_rnd.random() for _ in range(episodes)]

    successes, crashes, timeouts = 0, 0, 0
    shields = 0
    governor_vetos = 0
    shield_types = {"emergency_forward": 0, "emergency_stop": 0, "late_overlap": 0,
                    "adaptive_gap": 0, "high_pressure": 0}
    crash_bands = {"0.75-0.80": 0, "0.80-0.90": 0, "0.90-1.00": 0}
    comfort_brake_steps = 0   # car decel in [-6, -4) m/s²  — yielding, natural
    emergency_brake_steps = 0 # car decel < -6 m/s²          — panic stop, undesirable
    merge_steps_sum = 0
    # adaptive_gap diagnosis: track (progress_at_trigger, gap_at_trigger, rel_speed_at_trigger)
    ag_snapshots = []

    # ── Phase-2 macro telemetry ──────────────────────────────────────────
    # Average agent behaviour in the danger zone (progress>0.5)
    dz_gas_sum, dz_gas_steps = 0.0, 0
    dz_steer_sum = 0.0
    ttc_at_half_succ, ttc_at_half_crash = [], []  # TTC when progress first crosses 0.5

    action_volatility_sum = 0.0
    max_trailing_decel_sum = 0.0
    hesitation_sum = 0
    merge_steps_qod_sum = 0
    reversal_sum = 0
    peak_jerk_sum = 0.0
    gap_success_sum = 0.0
    veto_rate_sum = 0.0
    qod_n = 0
    for ep in range(episodes):
        random.seed(seed + ep)
        np.random.seed(seed + ep)
        torch.manual_seed(seed + ep)

        # Set a fresh scenario seed per episode so each episode gets a different
        # traffic configuration. Without this, all episodes use the same scenario
        # and eval results are frozen regardless of policy improvement.
        def _set_episode_scenario_seed(reroll_attempt: int = 0):
            if force_scenario_h:
                env._eval_scenario_seed = 0.99
            elif reroll_attempt == 0:
                env._eval_scenario_seed = _episode_scenario_seeds[ep]
            else:
                _rs = seed + ep + reroll_attempt * 10000
                _rnd.seed(_rs)
                env._eval_scenario_seed = _rnd.random()

        def _reroll_spawn(attempt: int):
            _rs = seed + ep + attempt * 10000
            random.seed(_rs)
            np.random.seed(_rs)
            _set_episode_scenario_seed(attempt)

        _set_episode_scenario_seed(0)
        state = env.reset_until_clear_spawn(max_retries=20, reroll_callback=_reroll_spawn)

        done = False
        steps = 0
        _crossed_half = False
        _ttc_half_pending = 999.0

        ep_info = {}
        while not done and steps < env.max_steps:
            with torch.no_grad():
                state_tensor = torch.FloatTensor(state).unsqueeze(0)
                action_mean, _, _ = agent.policy(state_tensor)
                # Deterministic eval removes sampling noise from checkpoint selection.
                action_value = action_mean.squeeze(0).numpy()

            next_state, _, done, ep_info = env.step(action_value)

            if env.last_governor_veto:
                governor_vetos += 1

            if env.last_intervened:
                shields += 1
                cond = env.last_shield_condition
                if cond in shield_types:
                    shield_types[cond] += 1
                if cond == "adaptive_gap":
                    gap, _, _, _, rel_speed, _ = env._scan_nearest_car()
                    progress = env._merge_progress()
                    ag_snapshots.append((ep, progress, gap, rel_speed, float(action_value[0])))

            _, _, car_accel, _, _, _ = env._scan_nearest_car()
            progress = float(next_state[0])  # Feature 0 = merge_progress
            if progress > 0.1:
                if car_accel < -6.0:
                    emergency_brake_steps += 1
                elif car_accel < -4.0:
                    comfort_brake_steps += 1

            # ── Phase-2: danger-zone macro sampling ──────────────────────
            if progress > 0.5:
                dz_gas_sum   += float(action_value[1])
                dz_steer_sum += float(action_value[0])
                dz_gas_steps += 1
                # Capture TTC the first time we cross progress=0.5 this episode
                if not _crossed_half:
                    _gap_now, _, _, _, _rel_spd, _ = env._scan_nearest_car()
                    _ttc_half = (_gap_now / _rel_spd) if (_gap_now > 0 and _rel_spd > 0.1) else 999.0
                    _crossed_half = True
                    # Will be assigned to success/crash list at episode end
                    _ttc_half_pending = _ttc_half

            state = next_state
            steps += 1

        merge_steps_sum += steps
        action_volatility_sum  += ep_info.get('action_volatility', 0.0)
        max_trailing_decel_sum += ep_info.get('max_trailing_decel', 0.0)
        hesitation_sum += ep_info.get('hesitation_steps', 0)
        merge_steps_qod_sum += ep_info.get('merge_steps', 0)
        reversal_sum += ep_info.get('reversal_count', 0)
        peak_jerk_sum += ep_info.get('peak_steer_jerk', 0.0)
        gap_success_sum += ep_info.get('gap_at_success', 0.0)
        veto_rate_sum += ep_info.get('governor_veto_rate', 0.0)
        qod_n += 1

        if env.last_success:
            successes += 1
            if _crossed_half:
                ttc_at_half_succ.append(_ttc_half_pending)
        elif env.last_crash:
            crashes += 1
            if _crossed_half:
                ttc_at_half_crash.append(_ttc_half_pending)
            p = env._merge_progress()
            if p < 0.80:
                crash_bands["0.75-0.80"] += 1
            elif p < 0.90:
                crash_bands["0.80-0.90"] += 1
            else:
                crash_bands["0.90-1.00"] += 1
        elif env.last_timeout:
            timeouts += 1

    ep = max(1, episodes)
    governor_veto_per_ep = governor_vetos / ep
    if verbose_shield and ag_snapshots:
        # Sample up to 10 examples to understand when adaptive_gap fires
        sample = ag_snapshots[:10]
        print(f"  [AG-DIAGNOSIS seed={seed}] {len(ag_snapshots)} total. "
              f"Sample (ep, progress, gap_m, rel_spd, pressure):")
        for s in sample:
            print(f"    ep={s[0]:2d}  prog={s[1]:.2f}  gap={s[2]:.2f}m  rel_spd={s[3]:.2f}m/s  pressure={s[4]:.3f}")
    return {
        "successes": successes,
        "crashes": crashes,
        "timeouts": timeouts,
        "shield_per_ep": shields / ep,
        "shield_types": shield_types,
        "comfort_brake_per_ep": comfort_brake_steps / ep,
        "emergency_brake_per_ep": emergency_brake_steps / ep,
        "avg_merge_time_s": (merge_steps_sum / ep) * env.dt,
        "governor_veto_per_ep": governor_veto_per_ep,
        "crash_bands": crash_bands,
        "dz_avg_gas":   (dz_gas_sum   / dz_gas_steps) if dz_gas_steps > 0 else None,
        "dz_avg_steer": (dz_steer_sum / dz_gas_steps) if dz_gas_steps > 0 else None,
        "ttc_at_half_succ_avg":  float(np.mean(ttc_at_half_succ))  if ttc_at_half_succ  else None,
        "ttc_at_half_crash_avg": float(np.mean(ttc_at_half_crash)) if ttc_at_half_crash else None,
        "ttc_at_half_succ_n":   len(ttc_at_half_succ),
        "ttc_at_half_crash_n":  len(ttc_at_half_crash),
        "action_volatility":  action_volatility_sum / max(1, qod_n),
        "max_trailing_decel": max_trailing_decel_sum / max(1, qod_n),
        "hesitation_steps":   hesitation_sum / max(1, qod_n),
        "merge_steps_qod":     merge_steps_qod_sum / max(1, qod_n),
        "reversal_count":      reversal_sum / max(1, qod_n),
        "peak_steer_jerk":     peak_jerk_sum / max(1, qod_n),
        "gap_at_success_avg":  gap_success_sum / max(1, qod_n),
        "governor_veto_rate_avg": veto_rate_sum / max(1, qod_n),
    }


def evaluate_policy_multi_seed(agent, episodes=40, seeds=(123, 456, 777), verbose_shield=False,
                               governor_disabled=False,
                               dense_seeds=(1001, 1002, 1003, 1004, 1005)):
    """Evaluate across normal seeds plus a set of dense-stream (Scenario H) seeds.

    dense_seeds always use force_scenario_h=True so the brain is tested on bumper-to-bumper
    traffic where no natural 999 m gap exists. A brain that only waits will score 0 % on these
    and cannot be promoted. Set dense_seeds=() to disable.
    """
    runs = [evaluate_policy(agent, episodes=episodes, seed=s,
                            verbose_shield=(verbose_shield and i == 0),
                            governor_disabled=governor_disabled)
            for i, s in enumerate(seeds)]
    # Append dense-stream runs
    for s in dense_seeds:
        runs.append(evaluate_policy(agent, episodes=episodes, seed=s,
                                    verbose_shield=False,
                                    governor_disabled=governor_disabled,
                                    force_scenario_h=True))
    # Aggregate shield type counts across seeds
    agg_types = {}
    for key in runs[0]["shield_types"]:
        agg_types[key] = sum(r["shield_types"][key] for r in runs)
    return {
        "successes": sum(r["successes"] for r in runs),
        "crashes": sum(r["crashes"] for r in runs),
        "timeouts": sum(r["timeouts"] for r in runs),
        "shield_per_ep": float(np.mean([r["shield_per_ep"] for r in runs])),
        "shield_types": agg_types,
        "comfort_brake_per_ep": float(np.mean([r["comfort_brake_per_ep"] for r in runs])),
        "emergency_brake_per_ep": float(np.mean([r["emergency_brake_per_ep"] for r in runs])),
        "avg_merge_time_s": float(np.mean([r["avg_merge_time_s"] for r in runs])),
        "governor_veto_per_ep": float(np.mean([r["governor_veto_per_ep"] for r in runs])),
        "crash_bands": {k: sum(r["crash_bands"][k] for r in runs) for k in runs[0]["crash_bands"]},
        "seed_count": len(seeds) + len(dense_seeds),
        "episodes_per_seed": episodes,
        "action_volatility": float(np.mean([r["action_volatility"] for r in runs])),
        "max_trailing_decel": float(np.mean([r["max_trailing_decel"] for r in runs])),
        "hesitation_steps": float(np.mean([r["hesitation_steps"] for r in runs])),
        "merge_steps_qod": float(np.mean([r["merge_steps_qod"] for r in runs])),
        "reversal_count": float(np.mean([r["reversal_count"] for r in runs])),
        "peak_steer_jerk": float(np.mean([r["peak_steer_jerk"] for r in runs])),
        "gap_at_success_avg": float(np.mean([r["gap_at_success_avg"] for r in runs])),
        "governor_veto_rate_avg": float(np.mean([r["governor_veto_rate_avg"] for r in runs])),
    }


def _load_policy_weights(agent, path, strict=False):
    """Load weights into ``agent``; returns False if absent. With ``strict`` an architecture
    mismatch raises instead of silently starting from random weights."""
    if not os.path.exists(path):
        return False
    try:
        state_dict = torch.load(path, weights_only=True)
    except TypeError:
        state_dict = torch.load(path)
    try:
        agent.policy.load_state_dict(state_dict)
    except RuntimeError as e:
        if strict:
            raise ValueError(
                f"{path} does not fit a {_agent_state_dim(agent)}-feature policy "
                f"(check --feature-dim): {e}") from e
        print(f"  [bootstrap] Checkpoint architecture mismatch — starting fresh: {e}")
        return False
    return True


def _eval_episode_count(eval_episodes, eval_seeds, dense_seeds):
    return eval_episodes * (len(eval_seeds) + len(dense_seeds))


def train(
    epochs=100,
    batch_size=2000,
    eval_episodes=5,
    eval_seeds=(123, 456, 777),
    dense_seeds=(),
    eval_interval=50,
    skip_baseline_eval=False,
    no_bootstrap=False,
    ppo_updates=4,
    max_grad_norm=0.5,
    rollback_patience=3,
    entropy_coef=0.02,   # raised from 0.005 — need more exploration to escape wait-policy
    gae_lambda=0.95,     # Bug 1 fix: GAE trace-decay (0=TD(0), 1=Monte Carlo)
    lr=None,
    governor_disabled=False,
    run_tag="11feat",
    commit_steer_weight=8.0,
    # Curriculum learning (3-phase): fixes v7 exploration collapse.
    # Phase 1: pure easy road (Scenario G only).  Phase 2: gradual mix-in.
    # Phase 3: full normal traffic.  Set both to 0 to disable curriculum.
    curriculum_phase1_end=60,   # last epoch of Phase 1 (exclusive)
    curriculum_phase2_end=150,  # last epoch of Phase 2 (exclusive)
    feature_dim=11,
    traffic_first=False,
    seed=None,
):
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
    env = BusMergeEnv(governor_disabled=governor_disabled)
    env.feature_dim = feature_dim
    env.state_size = feature_dim
    # SAT ground-truth penalty: enabled only for the exp7sat run-tag
    env.sat_penalty_enabled = str(run_tag).startswith("exp7sat")
    env.spongy_danger_zone_enabled = str(run_tag).startswith("exp7satv10")
    env.commit_steer_weight = commit_steer_weight
    ENV_FLAGS.update(sat_penalty_enabled=env.sat_penalty_enabled,
                     spongy_danger_zone_enabled=env.spongy_danger_zone_enabled,
                     commit_steer_weight=commit_steer_weight)
    print(f"Safe-steer weight once out of the bay: {commit_steer_weight}")
    if env.sat_penalty_enabled:
        print("SAT ground-truth penalty ENABLED (exp7sat mode).")
    if env.spongy_danger_zone_enabled:
        print("Spongy Danger Zone ENABLED (v10 — SAT terminal > 3.0 m² only).")
    runtime_path = _ckpt_path(f"ppo_bus_brain_{run_tag}.pth")
    best_path    = _ckpt_path(f"ppo_bus_brain_{run_tag}_best.pth")
    _bootstrap_path = _ckpt_path("ppo_bus_brain_11feat_best.pth")
    _v8_bootstrap   = _ckpt_path("ppo_bus_brain_exp7sat_best.pth")
    _v9_bootstrap   = _ckpt_path("ppo_bus_brain_exp7satv9_best.pth")

    agent = PPOAgent(state_dim=feature_dim, filename=runtime_path, lr=lr)
    print(f"Feature dim: {feature_dim} | checkpoints: {runtime_path}")
    # Bootstrap from tagged best, then generic best (11-dim only), then runtime.
    if no_bootstrap:
        print("Random policy init (--no-bootstrap); not loading prior checkpoints.")
    elif _load_policy_weights(agent, best_path, strict=True):
        print(f"Loaded best-eval policy: {best_path}")
    elif (str(run_tag).startswith("exp7satv10")
          and _load_policy_weights(agent, _v9_bootstrap)):
        print(f"Bootstrapped from v9 baseline: {_v9_bootstrap}")
    elif (str(run_tag).startswith("exp7satv")
          and not str(run_tag).startswith("exp7satv10")
          and _load_policy_weights(agent, _v8_bootstrap)):
        print(f"Bootstrapped from v8 baseline: {_v8_bootstrap}")
    elif (feature_dim == 11 and run_tag != "11feat"
          and _load_policy_weights(agent, _bootstrap_path)):
        print(f"Bootstrapped from generic best: {_bootstrap_path}")
    else:
        agent.load()

    best_eval_crashes = float('inf')
    best_eval_timeouts = float('inf')
    best_eval_success = 0  # never treat 0-success eval as "improved" (was -1 with skip-baseline)
    best_eval_shields = float('inf')
    best_eval_emergency_brakes = float('inf')  # Smooth-merge quality metric
    no_improve_windows = 0

    _eval_n = _eval_episode_count(eval_episodes, eval_seeds, dense_seeds)
    print(
        f"Eval schedule: every {eval_interval} epoch(s), "
        f"{_eval_n} episodes per eval "
        f"({len(eval_seeds)} seeds × {eval_episodes} ep"
        + (f" + {len(dense_seeds)} dense" if dense_seeds else "")
        + "). Streamlit / smoke_test are the production gate."
    )

    # Initialize best-eval trackers from the ACTUAL quality of the loaded checkpoint.
    # Without this, any first eval result (even worse quality) would be saved as "best"
    # and overwrite a previously superior checkpoint.
    if skip_baseline_eval:
        print("Skipping baseline eval (--skip-baseline-eval). best_eval_success=0 (must get merges to save best).")
    else:
        print("Measuring loaded checkpoint quality before training...")
        _init_stats = evaluate_policy_multi_seed(
            agent, episodes=eval_episodes, seeds=eval_seeds,
            dense_seeds=dense_seeds, governor_disabled=governor_disabled)
        best_eval_crashes = _init_stats['crashes']
        best_eval_timeouts = _init_stats['timeouts']
        best_eval_success = _init_stats['successes']
        best_eval_shields = _init_stats['shield_per_ep']
        best_eval_emergency_brakes = _init_stats['emergency_brake_per_ep']
        _tot = _init_stats['episodes_per_seed'] * _init_stats['seed_count']
        print(f"Checkpoint baseline: Succ={best_eval_success}/{_tot} Crash={best_eval_crashes} "
              f"TO={best_eval_timeouts} Shield/Ep={best_eval_shields:.2f}")

    print("Starting PPO PyTorch Training with Analytics...")
    log_path = str(REPO_ROOT / "training_11feat.log")
    window_start      = time.time()
    window_crash_progs: list = []  # progress at each crash in this eval-interval window
    window_merge_steps: list = []  # steps taken for each successful merge
    window_succ_sum = window_crash_sum = window_to_sum = 0

    for epoch in range(epochs):
        if seed is not None:
            # Re-seed every epoch: the in-training evaluations reseed the RNGs, which would otherwise
            # make runs that differ only in --seed follow the same data stream after the first eval.
            random.seed(seed * 100003 + epoch)
            np.random.seed(seed * 100003 + epoch)
            torch.manual_seed(seed * 100003 + epoch)
        # --------------------------------------------------------------------
        # 3-PHASE CURRICULUM SCHEDULE  (v8 -- fixes v7 exploration collapse)
#
        # Root cause of v7 failure: the old 25% Scenario-G probability was
        # swamped by 75% dense-traffic episodes each batch.  The agent saw
        # ~0 successful merges per gradient update and learned a wait-policy.
#
        #   Phase 1  (epochs 0 .. curriculum_phase1_end):
        #       _warmup_prob = 1.0  -> always Scenario G (2-4 cars, wide gaps).
        #       Agent learns basic steering and the +5000 success signal.
#
        #   Phase 2  (phase1_end .. phase2_end):
        #       _warmup_prob linearly 1.0 -> 0.0 (gradual mix-in of traffic).
        #       Agent learns to read gaps and time the merge.
#
        #   Phase 3  (phase2_end .. end):
        #       _warmup_prob = 0.0 -> normal full-density training.
        # --------------------------------------------------------------------

        # --- Noise sigma: gentle start, grows across all phases ---
        noise_sigma = 0.05 + (epoch / max(epochs - 1, 1)) * 0.25  # 0.05->0.30
        env.noise_sigma = noise_sigma

        # --- Warmup / empty-road curriculum (skip entirely when traffic_first) ---
        if traffic_first:
            _warmup_prob = 0.0
            env._warmup_prob = 0.0
            env._zero_road_prob = 0.0
            env.reward_profile = "core"
        else:
            if epoch < curriculum_phase1_end:
                _warmup_prob = 1.0           # Phase 1: always sparse / empty road
            elif epoch < curriculum_phase2_end:
                _p2_frac = ((epoch - curriculum_phase1_end)
                            / max(1, curriculum_phase2_end - curriculum_phase1_end))
                _warmup_prob = 1.0 - _p2_frac  # Phase 2: linear 1.0 -> 0.0
            else:
                _warmup_prob = 0.0          # Phase 3: full-density + production bridge
            env._warmup_prob = _warmup_prob
            env.reward_profile = "phase1" if _warmup_prob >= 1.0 else "core"
            # Phase 3: switch to production-bridge spawn (matches Streamlit traffic geometry).
            # Trains the agent on the same queue distribution it faces in SimulationEngine.
            env._production_bridge = (epoch >= curriculum_phase2_end)
            env._prod_traffic_rate = 0.4   # matches Streamlit default slider

            _zero_phase_end = min(15, max(1, int(curriculum_phase1_end * 0.25)))
            if curriculum_phase1_end <= 0:
                env._zero_road_prob = 0.0
            elif epoch < _zero_phase_end:
                env._zero_road_prob = 1.0 - (epoch / max(1, _zero_phase_end))
            else:
                env._zero_road_prob = 0.0

        if epoch == 0:
            _mode = "traffic-first (A–F mix)" if traffic_first else (
                f"curriculum P1<{curriculum_phase1_end} P2<{curriculum_phase2_end}"
            )
            print(f"Training traffic mode: {_mode} | warmup={env._warmup_prob:.2f} "
                  f"zero_road={env._zero_road_prob:.2f}", flush=True)

        # --- Effective entropy: boosted in Phase 1 to prevent early entropy
        #     collapse (std crashes before agent ever sees a success when all
        #     episodes are hard).  Decays to base entropy_coef by Phase 3. ---
        _phase1_entropy = max(entropy_coef, 0.10)  # at least 0.10 in Phase 1 (raised from 0.05)
        if traffic_first or curriculum_phase1_end <= 0:
            _eff_entropy = entropy_coef
        elif epoch < curriculum_phase1_end:
            _eff_entropy = _phase1_entropy
        elif epoch < curriculum_phase2_end:
            _p2_frac = ((epoch - curriculum_phase1_end)
                        / max(1, curriculum_phase2_end - curriculum_phase1_end))
            _eff_entropy = _phase1_entropy - _p2_frac * (_phase1_entropy - entropy_coef)
        else:
            _eff_entropy = entropy_coef

        # --- Shield penalty: suppressed in Phase 1 (free exploration). ---
        if traffic_first or curriculum_phase1_end <= 0:
            shield_scale = 1.5 * (epoch / max(1, epochs - 1))
        elif epoch < curriculum_phase1_end:
            shield_scale = 0.0
        else:
            _post = epoch - curriculum_phase1_end
            _post_epochs = max(1, epochs - curriculum_phase1_end - 1)
            shield_scale = 1.5 * (_post / _post_epochs)
        env.shield_penalty_scale = shield_scale

        state = env.reset_until_clear_spawn(max_retries=20)
        epoch_reward = 0
        steps = 0
        
        # --- NEW: Trackers for this batch ---
        successes, crashes, timeouts, shield_blocks = 0, 0, 0, 0
        episodes_completed = 0
        
        while steps < batch_size:
            raw_action, action_logprob = agent.choose_action(state)
            action_value = np.clip(raw_action, -1.0, 1.0)   # the vehicle gets the clipped command
            next_state, reward, done, _ = env.step(action_value)
            
            # --- NEW: Track exact events based on the reward logic in env_wrapper ---
            if env.last_intervened and not done:
                shield_blocks += 1
            if done:
                episodes_completed += 1
                if env.last_success:
                    successes += 1
                    window_succ_sum += 1
                    window_merge_steps.append(env.current_step)
                elif env.last_crash:
                    crashes += 1
                    window_crash_sum += 1
                    if env._step_history:
                        _cp = env._step_history[-1]['progress']
                        window_crash_progs.append(round(_cp, 3))
                elif env.last_timeout:
                    timeouts += 1
                    window_to_sum += 1
            
            agent.store_transition(state, raw_action, action_logprob, reward, next_state, done)
            
            state = next_state
            epoch_reward += reward
            steps += 1
            
            if done:
                state = env.reset_until_clear_spawn(max_retries=20)
                
        # --- PHASE 2: PPO UPDATE ---
        # For 2D actions, m[1] is numpy array shape (2,); m[2] is scalar logprob.
        states       = torch.FloatTensor(np.array([m[0] for m in agent.memory], dtype=np.float32))
        actions      = torch.FloatTensor(np.array([m[1] for m in agent.memory], dtype=np.float32))  # [batch, 2]
        old_logprobs = torch.FloatTensor(np.array([m[2] for m in agent.memory], dtype=np.float32)).unsqueeze(1)  # [batch, 1]
        rewards      = [m[3] for m in agent.memory]
        next_states  = torch.FloatTensor(np.array([m[4] for m in agent.memory], dtype=np.float32))
        dones        = [m[5] for m in agent.memory]

        # Bug 1 fix: GAE (Generalized Advantage Estimation)
        # delta_t = r_t + gamma * V(s_{t+1}) * (1-done) - V(s_t)
        # A_t     = delta_t + (gamma * lambda) * (1-done) * A_{t+1}
        # Bug 3 fix: normalize ADVANTAGES after GAE, NOT the raw returns.
        #   Old code normalized discounted_returns (scale ~[-1,1]) then
        #   subtracted state_values (scale ~[-1400,+5000]) -- dimensionally wrong.
        with torch.no_grad():
            _, _, state_values      = agent.policy(states)       # [batch, 1]
            _, _, next_state_values = agent.policy(next_states)  # [batch, 1]

        gae_adv = torch.zeros(len(rewards), 1)
        gae = 0.0
        for t in reversed(range(len(rewards))):
            not_done = 1.0 - float(dones[t])
            delta = (rewards[t]
                     + agent.gamma * next_state_values[t].item() * not_done
                     - state_values[t].item())
            gae   = delta + agent.gamma * gae_lambda * not_done * gae
            gae_adv[t, 0] = gae

        # Critic targets = unnormalized GAE returns (raw reward scale)
        returns    = (gae_adv + state_values).detach()
        # Actor signal = normalized advantages (zero-mean, unit-variance)
        advantages = (gae_adv - gae_adv.mean()) / (gae_adv.std() + 1e-7)

        for _ in range(ppo_updates):
            action_mean, action_std, current_state_values = agent.policy(states)
            dist = torch.distributions.Normal(action_mean, action_std)
            # new_logprobs: [batch, 2] — sum across action dims to get per-step logprob
            new_logprobs = dist.log_prob(actions).sum(dim=-1, keepdim=True)  # [batch, 1]
            
            ratios = torch.exp(new_logprobs - old_logprobs)
            surr1 = ratios * advantages
            surr2 = torch.clamp(ratios, 1 - agent.clip_ratio, 1 + agent.clip_ratio) * advantages
            actor_loss = -torch.min(surr1, surr2).mean()
            critic_loss = nn.MSELoss()(current_state_values, returns)
            # Entropy bonus: prevents policy from collapsing into a single strategy
            # and keeps the agent exploring different timing windows.
            entropy = dist.entropy().mean()
            loss = actor_loss + 0.5 * critic_loss - _eff_entropy * entropy
            
            agent.optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(agent.policy.parameters(), max_grad_norm)
            agent.optimizer.step()
            
        agent.memory.clear()

        # Per-epoch lightweight rollout summary (always printed)
        avg_score_ep = epoch_reward / max(episodes_completed, 1)
        crash_pct = f"{crashes}/{episodes_completed}" if episodes_completed > 0 else "n/a"
        print(f"Ep {epoch+1:3d}/{epochs} | rollout: {crash_pct} crash | shield: {shield_blocks} | score: {avg_score_ep:.0f}", flush=True)
        agent.save()  # always persist runtime ckpt for Streamlit; eval only gates best/promote

        # Periodic eval (light by default — see --eval-interval / --eval-episodes)
        if eval_interval > 0 and (epoch + 1) % eval_interval == 0:
            avg_score = epoch_reward / episodes_completed if episodes_completed > 0 else 0
            # Print adaptive_gap diagnosis on the very first eval only
            verbose = (epoch + 1 == eval_interval)
            eval_stats = evaluate_policy_multi_seed(
                agent, episodes=eval_episodes, seeds=eval_seeds,
                dense_seeds=dense_seeds,
                verbose_shield=verbose, governor_disabled=governor_disabled)
            total_eval_episodes = eval_stats["episodes_per_seed"] * eval_stats["seed_count"]
            
            print(f"\n--- Epoch {epoch + 1}/{epochs} ---")
            print(f"Stats  | Episodes: {episodes_completed} | Succ: {successes} | Crash: {crashes} | TO: {timeouts} | Shield: {shield_blocks}")
            print(f"Scores | Avg Score: {avg_score:.1f} | Actor Loss: {actor_loss.item():.3f} | Critic Loss: {critic_loss.item():.3f}")
            st = eval_stats['shield_types']
            print(
                "Eval  | "
                f"Succ: {eval_stats['successes']}/{total_eval_episodes} | "
                f"Crash: {eval_stats['crashes']} | TO: {eval_stats['timeouts']} | "
                f"Shield/Ep: {eval_stats['shield_per_ep']:.2f} "
                f"[ag={st['adaptive_gap']} hp={st['high_pressure']} lo={st['late_overlap']} "
                f"ef={st['emergency_forward']} es={st['emergency_stop']}] | "
                f"ComfortBrake/Ep: {eval_stats['comfort_brake_per_ep']:.2f} | "
                f"EmergencyBrake/Ep: {eval_stats['emergency_brake_per_ep']:.2f} | "
                f"MergeTime: {eval_stats['avg_merge_time_s']:.2f}s | "
                f"GovVeto/Ep: {eval_stats['governor_veto_per_ep']:.2f} | "
                f"Smooth: {eval_stats.get('action_volatility', 0):.3f} | "
                f"Crtsy: {eval_stats.get('max_trailing_decel', 0):.2f}m/s2 | "
                f"Hesit: {eval_stats.get('hesitation_steps', 0):.1f} | "
                f"MrgStp: {eval_stats.get('merge_steps_qod', 0):.1f} | "
                f"Rev: {eval_stats.get('reversal_count', 0):.2f} | "
                f"PkJrk: {eval_stats.get('peak_steer_jerk', 0):.3f} | "
                f"Gap@OK: {eval_stats.get('gap_at_success_avg', 0):.1f}m | "
                f"VetoRate: {eval_stats.get('governor_veto_rate_avg', 0):.3f} | "
                f"Seeds: {list(eval_seeds)}"
            )
            cb = eval_stats.get("crash_bands", {})
            if eval_stats["crashes"] > 0 and cb:
                print(
                    "CrashBands | "
                    f"p=0.75-0.80: {cb.get('0.75-0.80', 0):3d} | "
                    f"p=0.80-0.90: {cb.get('0.80-0.90', 0):3d} | "
                    f"p=0.90-1.00: {cb.get('0.90-1.00', 0):3d}"
                )
            dg = eval_stats.get("dz_avg_gas");   ds = eval_stats.get("dz_avg_steer")
            th_s = eval_stats.get("ttc_at_half_succ_avg");  th_sn = eval_stats.get("ttc_at_half_succ_n", 0)
            th_c = eval_stats.get("ttc_at_half_crash_avg"); th_cn = eval_stats.get("ttc_at_half_crash_n", 0)
            dg_str  = f"{dg:.3f}"  if dg  is not None else "n/a"
            ds_str  = f"{ds:.3f}"  if ds  is not None else "n/a"
            ths_str = f"{th_s:.2f}s (n={th_sn})" if th_s is not None else "n/a"
            thc_str = f"{th_c:.2f}s (n={th_cn})" if th_c is not None else "n/a"
            print(
                f"DangerZone | avg_gas={dg_str}  avg_steer={ds_str}  "
                f"TTC@half_succ={ths_str}  TTC@half_crash={thc_str}"
            )

            # Successes first; require at least one merge — 0/15 must never become "best".
            improved = False
            if (eval_stats['successes'] > 0
                    and eval_stats['successes'] > best_eval_success):
                improved = True
            elif eval_stats['successes'] > 0 and eval_stats['successes'] == best_eval_success:
                if eval_stats['crashes'] < best_eval_crashes:
                    improved = True
                elif eval_stats['crashes'] == best_eval_crashes:
                    if eval_stats['timeouts'] < best_eval_timeouts:
                        improved = True
                    elif eval_stats['timeouts'] == best_eval_timeouts:
                        if eval_stats['shield_per_ep'] < best_eval_shields:
                            improved = True
                        elif eval_stats['shield_per_ep'] == best_eval_shields:
                            if eval_stats['emergency_brake_per_ep'] < best_eval_emergency_brakes:
                                improved = True

            if improved:
                best_eval_crashes = eval_stats['crashes']
                best_eval_timeouts = eval_stats['timeouts']
                best_eval_success = eval_stats['successes']
                best_eval_shields = eval_stats['shield_per_ep']
                best_eval_emergency_brakes = eval_stats['emergency_brake_per_ep']

                os.makedirs(os.path.dirname(best_path), exist_ok=True)
                torch.save(agent.policy.state_dict(), best_path)
                print(f"Saved new best eval model -> {best_path}")
                no_improve_windows = 0
            else:
                no_improve_windows += 1

            # Promotion gate: require zero crashes AND at least 90 % success rate.
            # The old gate (crashes==0 only) shipped the do-nothing brain that scored
            # 0/N successes but also 0 crashes — exactly the observed Streamlit failure.
            _min_promote_succ = int(0.90 * total_eval_episodes)
            if (eval_stats['crashes'] == 0
                    and eval_stats['successes'] >= _min_promote_succ
                    and os.path.exists(best_path)):
                shutil.copy2(best_path, runtime_path)
                print(f"Promoted zero-crash ≥90%-success model -> {runtime_path}")

            # If evaluation regresses for several windows, roll back to best model.
            # rollback_patience 0 disables it: a run that starts with no successful evaluation would
            # otherwise be reset to its starting weights every `patience` evaluations.
            if rollback_patience and no_improve_windows >= rollback_patience and os.path.exists(best_path):
                _load_policy_weights(agent, best_path)
                no_improve_windows = 0
                print(f"Rollback triggered: restored policy from {best_path}")

            # rollout summary for this eval window -> training.log
            _wep = max(
                window_succ_sum + window_crash_sum + window_to_sum, 1)
            _elapsed = time.time() - window_start
            _e1 = epoch + 2 - eval_interval
            _e2 = epoch + 1
            _bands = {"a": 0, "b": 0, "c": 0, "d": 0}
            for _cp in window_crash_progs:
                if _cp < 0.1:    _bands["a"] += 1
                elif _cp < 0.5:  _bands["b"] += 1
                elif _cp < 0.75: _bands["c"] += 1
                else:            _bands["d"] += 1
            _mt = window_merge_steps
            _mt_avg = sum(_mt)/len(_mt) if _mt else 0.0
            _mt_min = min(_mt) if _mt else 0
            _mt_max = max(_mt) if _mt else 0
            _top = sorted(window_crash_progs, reverse=True)[:10]
            _t = _elapsed / _wep
            _block = (
                "\n=== EPOCHS %d-%d  (%ds, %.1fs/ep) ===\n"
                % (_e1, _e2, _elapsed, _t)
            )
            _block += (
                "  Rollout: %d eps | Succ: %d | Crash: %d | TO: %d\n"
                % (_wep, window_succ_sum, window_crash_sum, window_to_sum)
            )
            _block += (
                "  Crashes: %d | p<0.1: %d | 0.1-0.5: %d"
                " | 0.5-0.75: %d | >=0.75: %d\n"
                % (window_crash_sum,
                   _bands["a"], _bands["b"],
                   _bands["c"], _bands["d"])
            )
            if window_crash_progs:
                _block += "  top-10 p: %s\n" % str(_top)
            _block += (
                "  Merge: %d | avg %.1f steps | min %d | max %d\n"
                % (len(_mt), _mt_avg, _mt_min, _mt_max)
            )
            _es  = eval_stats["successes"]
            _ec  = eval_stats["crashes"]
            _et  = eval_stats["timeouts"]
            _esh = eval_stats["shield_per_ep"]
            _emt = eval_stats["avg_merge_time_s"]
            _block += (
                "  Eval: %d/%d S | %d C | %d TO"
                " | sh=%.2f mt=%.1fs\n"
                % (_es, total_eval_episodes,
                   _ec, _et, _esh, _emt)
            )
            with open(log_path, 'a') as _lf:
                _lf.write(_block)
            print(_block, end='')
            # reset window accumulators
            window_start = time.time()
            window_crash_progs.clear()
            window_merge_steps.clear()
            window_succ_sum = window_crash_sum = window_to_sum = 0

    # --- FINAL VALIDATION RUN ---
    # Uses a "held-out" seed set never seen during training or eval.
    from busmerge.rl.validation_constants import TRAINING_VALIDATION_SEEDS
    VALIDATION_SEEDS = TRAINING_VALIDATION_SEEDS
    print("\n--- Final Validation Run (held-out seeds, never optimised against) ---")
    if os.path.exists(best_path):
        _load_policy_weights(agent, best_path)
    val_stats = evaluate_policy_multi_seed(
        agent, episodes=eval_episodes, seeds=VALIDATION_SEEDS,
        dense_seeds=dense_seeds, governor_disabled=governor_disabled)
    val_total = val_stats['episodes_per_seed'] * val_stats['seed_count']
    st = val_stats['shield_types']
    print(
        f"Validation | "
        f"Succ: {val_stats['successes']}/{val_total} | "
        f"Crash: {val_stats['crashes']} | TO: {val_stats['timeouts']} | "
        f"Shield/Ep: {val_stats['shield_per_ep']:.2f} "
        f"[ag={st['adaptive_gap']} hp={st['high_pressure']} lo={st['late_overlap']} "
        f"ef={st['emergency_forward']} es={st['emergency_stop']}]"
    )
    if val_stats['crashes'] == 0 and val_stats['successes'] >= val_total * 0.98:
        print("Validation PASSED: agent generalises beyond eval seeds.")
    else:
        print("Validation WARNING: performance gap between eval and validation seeds — possible overfitting.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--eval-episodes", type=int, default=5,
                        help="Episodes per eval seed (default 5; was 40).")
    parser.add_argument("--eval-interval", type=int, default=50,
                        help="Run eval every N epochs (0=never during training). Default 50.")
    parser.add_argument("--dense-seeds", type=str, default="",  # disabled: all blocked at spawn
                        help="Comma-separated Scenario-H seeds (default: none during training).")
    parser.add_argument("--skip-baseline-eval", action="store_true",
                        help="Skip pre-training checkpoint measurement.")
    parser.add_argument("--no-bootstrap", action="store_true",
                        help="Do not load any prior .pth; train from random init.")
    parser.add_argument("--phase1-only", action="store_true",
                        help="Keep Scenario G curriculum for all epochs (no dense mix-in).")
    parser.add_argument("--ppo-updates", type=int, default=2)
    parser.add_argument("--max-grad-norm", type=float, default=0.5)
    parser.add_argument("--rollback-patience", type=int, default=10)
    parser.add_argument("--lr", type=float, default=None,
                        help="Override learning rate (default: PPOAgent default 5e-5)")
    parser.add_argument("--entropy-coef", type=float, default=0.005,
                        help="PPO entropy bonus coefficient (lower = less exploration)")
    parser.add_argument("--gae-lambda",   type=float, default=0.95,
                        help="GAE trace-decay lambda (0=TD(0), 1=Monte Carlo).")
    parser.add_argument("--eval-seeds", type=str, default="123,456,777",
                        help="Comma-separated eval seeds (default: 3 seeds).")
    parser.add_argument("--disable-governor", action="store_true", default=False,
                        help="Bypass governor predictive veto; agent relies on reactive shield only.")
    parser.add_argument("--feature-dim", type=int, default=11, choices=[4, 7, 11],
                        help="State vector size (experiment branch: try 7 or 4 first).")
    parser.add_argument("--run-tag", type=str, default="11feat",
                        help="Tag for checkpoint filenames (e.g. exp7, exp4).")
    parser.add_argument("--traffic-first", action="store_true", default=False,
                        help="Full traffic mix from epoch 0 (no empty road / Scenario G warmup).")
    parser.add_argument("--curriculum-phase1", type=int, default=60,
                        help="Last epoch (exclusive) of Phase 1 (pure Scenario G). Default 60.")
    parser.add_argument("--curriculum-phase2", type=int, default=150,
                        help="Last epoch (exclusive) of Phase 2 (linear mix-in). Default 150.")
    parser.add_argument("--fast-train", action="store_true",
                        help="Speed preset: skip baseline eval, eval every 100 ep, "
                             "3 ep × 1 seed during training (full validation still at end).")
    args = parser.parse_args()
    if args.fast_train:
        args.skip_baseline_eval = True
        if args.eval_interval == 50:   # only override if user left default
            args.eval_interval = 100
        if args.eval_episodes == 5:
            args.eval_episodes = 3
        if args.eval_seeds == "123,456,777":
            args.eval_seeds = "123"
        print("Fast-train preset: skip baseline, eval every 100 ep, 3×1 seed.")
    eval_seeds = tuple(int(x.strip()) for x in args.eval_seeds.split(",") if x.strip())
    dense_seeds = tuple(int(x.strip()) for x in args.dense_seeds.split(",") if x.strip())
    _p1 = args.epochs if args.phase1_only else args.curriculum_phase1
    _p2 = (args.epochs + 1) if args.phase1_only else args.curriculum_phase2
    if args.traffic_first:
        _p1, _p2 = 0, 0
        print(f"Traffic-first mode: scenarios A–F from epoch 0 (no empty-road warmup).")
    elif args.phase1_only:
        print(f"Phase-1-only mode: Scenario G for all {args.epochs} epochs (Streamlit gate still required).")
    train(
        epochs=args.epochs,
        batch_size=args.batch_size,
        eval_episodes=args.eval_episodes,
        eval_seeds=eval_seeds,
        dense_seeds=dense_seeds,
        eval_interval=args.eval_interval,
        skip_baseline_eval=args.skip_baseline_eval,
        no_bootstrap=args.no_bootstrap,
        ppo_updates=args.ppo_updates,
        max_grad_norm=args.max_grad_norm,
        rollback_patience=args.rollback_patience,
        entropy_coef=args.entropy_coef,
        gae_lambda=args.gae_lambda,
        lr=args.lr,
        governor_disabled=args.disable_governor,
        run_tag=args.run_tag,
        curriculum_phase1_end=_p1,
        curriculum_phase2_end=_p2,
        feature_dim=args.feature_dim,
        traffic_first=args.traffic_first,
    )