"""
Lateral model debug tool — run with:  python test_lateral.py
Produces lateral_debug.png with 4 panels that let you inspect
the steering-first model and O-U lane drift for each car class.
"""

import numpy as np
import matplotlib.pyplot as plt
from busmerge.vehicle import Vehicle, Bus, sample_vehicle_params, CAR_PARAMS, BusState
import copy, random

CLASSES   = ["Compact", "Mid", "Large", "SUV", "Aggressive"]
N_SAMPLES = 5         # how many individual drivers to draw per class
DT        = 0.1       # simulation timestep (s)
T_MAX     = 6.0       # seconds to simulate
STEPS     = int(T_MAX / DT)

random.seed(42)
np.random.seed(42)

# ── Build a dummy bus for the squeezing trigger ──────────────────────────────
bp   = copy.deepcopy(CAR_PARAMS)
bus  = Bus(0, 300.0, 5.0, bp)
bus.state = BusState.WAITING_TO_MERGE

fig, axes = plt.subplots(4, len(CLASSES), figsize=(5 * len(CLASSES), 14),
                          sharex=True)
fig.suptitle("Lateral Model Debug — Steering-First + O-U Drift", fontsize=13, y=0.98)

for col, cls in enumerate(CLASSES):
    ax_steer   = axes[0][col]
    ax_heading = axes[1][col]
    ax_lat     = axes[2][col]
    ax_drift   = axes[3][col]

    ax_steer.set_title(cls, fontsize=11, fontweight='bold')

    for trial in range(N_SAMPLES):
        _, params = sample_vehicle_params(cls)
        car = Vehicle(trial + 1, 50.0, 10.0, params)
        car.is_squeezing = True

        t_arr     = np.arange(STEPS) * DT
        steer_arr = np.zeros(STEPS)
        head_arr  = np.zeros(STEPS)
        lat_arr   = np.zeros(STEPS)
        drift_arr = np.zeros(STEPS)

        for i in range(STEPS):
            car.update_physics(DT, bus=bus)
            steer_arr[i] = np.degrees(car.steer_angle)
            head_arr[i]  = np.degrees(car.heading_angle)
            lat_arr[i]   = car.lateral_offset
            drift_arr[i] = car.lane_drift

        label = f"pol={params.politeness_factor:.2f} sr={params.steer_rate_deg_per_s:.0f}"
        ax_steer.plot(t_arr,   steer_arr, alpha=0.7, label=label)
        ax_heading.plot(t_arr, head_arr,  alpha=0.7)
        ax_lat.plot(t_arr,     lat_arr,   alpha=0.7)
        ax_drift.plot(t_arr,   drift_arr, alpha=0.7)

    # Row labels (left column only)
    if col == 0:
        ax_steer.set_ylabel("Steer angle (°)")
        ax_heading.set_ylabel("Heading angle (°)")
        ax_lat.set_ylabel("Lateral offset (m)")
        ax_drift.set_ylabel("O-U lane drift (m)")

    ax_steer.legend(fontsize=5, loc='lower right')
    ax_drift.set_xlabel("Time (s)")

    for ax in (ax_steer, ax_heading, ax_lat, ax_drift):
        ax.grid(True, alpha=0.3)
        ax.axhline(0, color='k', linewidth=0.5)

plt.tight_layout(rect=[0, 0, 1, 0.97])
plt.savefig("lateral_debug.png", dpi=120)
print("Saved: lateral_debug.png")

# ── Print distribution summary ───────────────────────────────────────────────
print("\n=== Per-class distribution (N=200 samples each) ===")
np.random.seed(0); random.seed(0)
header = f"{'Class':<12}  {'politeness':>10}  {'steer_rate':>10}  {'max_steer':>10}  {'lane_noise':>10}"
print(header)
print("-" * len(header))
for cls in CLASSES:
    pols = []; srs = []; mss = []; lns = []
    for _ in range(200):
        _, p = sample_vehicle_params(cls)
        pols.append(p.politeness_factor)
        srs.append(p.steer_rate_deg_per_s)
        mss.append(p.max_steer_angle_deg)
        lns.append(p.lane_keeping_noise)
    print(f"{cls:<12}  {np.mean(pols):>6.2f}±{np.std(pols):.2f}"
          f"  {np.mean(srs):>6.1f}±{np.std(srs):.1f}"
          f"  {np.mean(mss):>6.1f}±{np.std(mss):.1f}"
          f"  {np.mean(lns):>6.3f}±{np.std(lns):.3f}")
