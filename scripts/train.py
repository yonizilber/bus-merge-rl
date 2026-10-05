#!/usr/bin/env python3
"""
Experiment-branch trainer: 4-, 7-, or 11-feature PPO (same env physics, smaller state).

Default: traffic-first training (full scenario mix A–F from epoch 0 — no empty road).

Examples:
  python -u scripts/train.py --epochs 80 --run-tag exp4
  python -u scripts/train.py --feature-dim 7 --epochs 80 --run-tag exp7
  python -u scripts/train.py --epochs 60 --phase1-only   # legacy sparse warmup
"""



from busmerge.rl.train import train  # noqa: E402
import argparse  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PPO bus merge — 4/7/11 features")
    parser.add_argument("--feature-dim", type=int, default=4, choices=[4, 7, 11])
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--run-tag", type=str, default=None,
                        help="Default: exp7 / exp4 / 11feat from feature-dim")
    parser.add_argument(
        "--phase1-only", action="store_true", default=False,
        help="Legacy: Scenario G / empty-road curriculum for all epochs.",
    )
    parser.add_argument(
        "--traffic-first", action="store_true", default=True,
        help="Full traffic A–F from epoch 0 (default). Use --no-traffic-first to disable.",
    )
    parser.add_argument(
        "--no-traffic-first", action="store_false", dest="traffic_first",
        help="Use 3-phase empty/sparse curriculum instead of traffic-first.",
    )
    parser.add_argument(
        "--no-bootstrap", action="store_true", default=False,
        help="Random init; default loads existing run-tag checkpoint if present.",
    )
    parser.add_argument("--eval-interval", type=int, default=10)
    parser.add_argument("--skip-baseline-eval", action="store_true", default=False)
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--entropy-coef", type=float, default=0.02)
    parser.add_argument("--dense-seeds", type=str, default="1001,1002,1003",
                        help="Scenario-H eval seeds during training (dense bumper traffic).")
    args = parser.parse_args()

    run_tag = args.run_tag or {4: "exp4", 7: "exp7", 11: "11feat"}[args.feature_dim]

    dense_seeds = tuple(int(x.strip()) for x in args.dense_seeds.split(",") if x.strip())

    if args.phase1_only and args.traffic_first:
        print("Note: --phase1-only overrides traffic-first (sparse curriculum).")
        args.traffic_first = False

    print(
        f"scripts/train.py: {args.feature_dim}-dim state | tag={run_tag} | "
        f"traffic_first={args.traffic_first} | phase1_only={args.phase1_only} | "
        f"no_bootstrap={args.no_bootstrap}"
    )

    if args.phase1_only:
        _p1 = args.epochs
        _p2 = args.epochs + 1
        _traffic = False
    elif args.traffic_first:
        _p1 = 0
        _p2 = 0
        _traffic = True
    else:
        _p1 = 60
        _p2 = min(150, args.epochs)
        _traffic = False

    train(
        epochs=args.epochs,
        batch_size=args.batch_size,
        eval_interval=args.eval_interval,
        skip_baseline_eval=args.skip_baseline_eval,
        no_bootstrap=args.no_bootstrap,
        entropy_coef=args.entropy_coef,
        run_tag=run_tag,
        curriculum_phase1_end=_p1,
        curriculum_phase2_end=_p2,
        feature_dim=args.feature_dim,
        traffic_first=_traffic,
        dense_seeds=dense_seeds,
    )
