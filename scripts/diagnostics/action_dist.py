"""
diag_action_dist.py -- Brain Wave Test
Loads latest PPOAgent checkpoint, runs 50-step episode,
prints raw Actor mean/std at every step before sampling.
Run:  python diag_action_dist.py [--ckpt PATH] [--seed N] [--steps N]
"""

import os, sys, argparse
import numpy as np
import torch
import random as _random

from busmerge.paths import MODELS_DIR
from busmerge.rl.ppo_agent import PPOAgent
from busmerge.rl.env import BusMergeEnv

CKPT_DIR = str(MODELS_DIR)
BUS_MAX_SPEED = 11.1  # m/s -- must match env


def get_latest_checkpoint():
    if not os.path.isdir(CKPT_DIR):
        raise FileNotFoundError("Checkpoint dir not found: " + CKPT_DIR)
    files = [f for f in os.listdir(CKPT_DIR) if f.endswith(".pth")]
    if not files:
        raise FileNotFoundError("No .pth files in checkpoints/")
    for tag in ["v6_best", "v6", "v5_best", "v5", "gov", "nogov"]:
        matches = [f for f in files if f.endswith("_" + tag + ".pth")]
        if matches:
            return os.path.join(CKPT_DIR, sorted(matches)[-1])
    return max([os.path.join(CKPT_DIR, f) for f in files], key=os.path.getmtime)

def run(ckpt_path, seed, n_steps):
    print("Checkpoint : " + ckpt_path)
    agent = PPOAgent(filename=ckpt_path)
    agent.load()
    agent.policy.eval()

    # Bug 5 fix: log_std is now state-dependent (actor_log_std_head).
    # Initial bias is -0.7 -> init std ≈ 0.497 for all states; diverges during training.
    log_std   = [round(float(agent.policy.actor_log_std_head.bias[i]), 4) for i in range(2)]
    std_vals  = [round(float(torch.exp(torch.tensor(x))), 4) for x in log_std]

    env = BusMergeEnv(eval_mode=True)
    np.random.seed(seed)
    _random.seed(seed)
    torch.manual_seed(seed)
    state = env.reset()

    print("Seed: %d  |  Steps: %d  |  gamma=%.4f" % (seed, n_steps, agent.gamma))
    print("actor_log_std=%s  std=%s" % (log_std, std_vals))

    hdr = "%3s  %7s %6s  %7s %6s  %7s  %7s %7s  %7s %8s  %6s  %4s  %7s"
    cols = ("Stp", "MeanS", "StdS", "MeanG", "StdG", "SpdTgt",
            "ASteer", "AGas", "BusVel", "LatVel", "Prog", "Gov", "Reward")
    print("")
    print(hdr % cols)
    print("-" * 95)
    mean_s_all, mean_g_all = [], []
    std_s_all,  std_g_all  = [], []
    step_count = 0

    for step in range(n_steps):
        state_t = torch.FloatTensor(state).unsqueeze(0)

        with torch.no_grad():
            action_mean, action_std, _ = agent.policy(state_t)

        ms = float(action_mean[0, 0])
        mg = float(action_mean[0, 1])
        ss = float(action_std[0, 0])
        sg = float(action_std[0, 1])
        spd_tgt = (mg + 1.0) / 2.0 * BUS_MAX_SPEED

        # deterministic: use raw mean, no sampling
        action = action_mean.squeeze().detach().cpu().numpy()
        action = np.clip(action, -1.0, 1.0)
        as_ = float(action[0])
        ag  = float(action[1])

        next_state, reward, done, _ = env.step(action)
        vel  = float(env.bus.velocity)
        lat  = float(env.bus.lateral_velocity)
        prog = float(env._merge_progress())
        gov  = "GOV" if env.last_governor_veto else "   "

        row = "%3d  %+7.3f %6.3f  %+7.3f %6.3f  %7.2f  %+7.3f %+7.3f  %7.3f %8.4f  %6.3f  %s  %7.1f"
        print(row % (step+1, ms, ss, mg, sg, spd_tgt, as_, ag, vel, lat, prog, gov, reward))

        mean_s_all.append(ms)
        mean_g_all.append(mg)
        std_s_all.append(ss)
        std_g_all.append(sg)
        state = next_state
        step_count = step + 1

        if done:
            if env.last_success:    outcome = "SUCCESS"
            elif env.last_crash:    outcome = "CRASH"
            else:                   outcome = "TIMEOUT"
            print("")
            print("  --> Episode ended at step %d: %s" % (step_count, outcome))
            break

    # Summary
    ms_a = np.array(mean_s_all)
    mg_a = np.array(mean_g_all)
    ss_a = np.array(std_s_all)
    sg_a = np.array(std_g_all)
    spd_targets = (mg_a + 1.0) / 2.0 * BUS_MAX_SPEED

    print("")
    print("=" * 65)
    print("DISTRIBUTION SUMMARY")
    print("=" * 65)
    print("")
    print("  STEER Mean:  avg=%+.4f  std=%.4f  [%+.4f, %+.4f]" % (ms_a.mean(), ms_a.std(), ms_a.min(), ms_a.max()))
    print("  GAS   Mean:  avg=%+.4f  std=%.4f  [%+.4f, %+.4f]" % (mg_a.mean(), mg_a.std(), mg_a.min(), mg_a.max()))
    print("")
    print("  STEER Std (exploration width): avg=%.4f" % ss_a.mean())
    print("  GAS   Std (exploration width): avg=%.4f" % sg_a.mean())

    pct_fwd = (mg_a > 0.0).mean() * 100
    print("")
    print("  Gas mean > 0 in %.1f%% of steps (implies forward intent)" % pct_fwd)
    print("  Average implied speed target: %.2f m/s" % spd_targets.mean())
    print("  Speed target range: [%.2f, %.2f] m/s" % (spd_targets.min(), spd_targets.max()))

    init_std = 0.497
    if abs(ss_a.mean() - init_std) < 0.05:
        print("")
        print("  WARNING: Steer std barely moved from init (%.4f ~= %.4f)" % (ss_a.mean(), init_std))
        print("           actor_log_std_head may not be learning (check per-step std in table above)")

    if mg_a.mean() > -0.5:
        print("")
        print("  OK: Mean gas=%+.4f  speed target=%.1f m/s" % (mg_a.mean(), spd_targets.mean()))
        print("      Bicycle trap resolved under new gas mapping.")
    else:
        print("")
        print("  WARNING: Mean gas=%+.4f  speed target=%.1f m/s" % (mg_a.mean(), spd_targets.mean()))
        print("           Still very negative. Needs more training.")

    print("=" * 65)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ckpt",  type=str, default=None)
    p.add_argument("--seed",  type=int, default=7)
    p.add_argument("--steps", type=int, default=50)
    args = p.parse_args()
    run(args.ckpt or get_latest_checkpoint(), args.seed, args.steps)


if __name__ == "__main__":
    main()
