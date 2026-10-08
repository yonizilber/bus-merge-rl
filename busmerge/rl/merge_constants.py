"""
merge_constants.py — single source of truth for all constants shared between
the RL training environment (env.py) and the production
simulation (simulation.py).

Import with:
    from busmerge.rl.merge_constants import (BUS_MAX_SPEED, BAY_DEPTH, ...)   # from simulation.py
    from busmerge.rl.merge_constants import (BUS_MAX_SPEED, BAY_DEPTH, ...)       # from rl/ scripts

Any divergence between training and production that caused a brain to fail in
Streamlit (e.g. BUS_MAX_SPD was 8.33 in sim vs 11.1 in env) will be caught
automatically once both files import from here instead of hardcoding values.
"""

# ---------------------------------------------------------------------------
# Road / bay geometry
# ---------------------------------------------------------------------------
LANE_WIDTH   = 3.5      # m — width of the traffic lane
BAY_DEPTH    = -3.5     # m — lateral_offset when bus is fully in bay
BUS_WIDTH    = 2.5      # m — bus body width
BUS_LENGTH   = 11.0     # m — bus body length

# ---------------------------------------------------------------------------
# Bus longitudinal dynamics
# ---------------------------------------------------------------------------
BUS_MAX_SPEED   = 40.0 / 3.6   # m/s  (~11.1 m/s = 40 km/h)
MERGE_ACCEL_MAX = 2.0           # m/s² — max longitudinal acceleration during merge

# ---------------------------------------------------------------------------
# Governor kinematic parameters (must be identical in training and production)
# ---------------------------------------------------------------------------
GOVERNOR_T_HORIZON           = 1.0   # s — early-merge projection window
GOVERNOR_T_HORIZON_COMMITTED = 2.5   # s — committed-merge escape window
GOVERNOR_MAX_SAFE_DECEL      = 9.0   # m/s² — physical emergency-braking ceiling
GOVERNOR_STEER_THRESHOLD     = 0.15  # ignore steer intents below this in early merge
GOVERNOR_CLEAR_ROAD_GAP_M    = 50.0  # gap ≥ this (or no car) → governor/shield pass-through
GOVERNOR_BLOCKED_LANE_PROGRESS = 0.85  # gap < 0 below this → no merge steer (lane occupied)

# ---------------------------------------------------------------------------
# Car yield during bus merge — continuous blend (busmerge/rl/merge_yield.py)
# ---------------------------------------------------------------------------
YIELD_VIS_START   = 0.05   # merge_progress below → no yield (free flow)
YIELD_VIS_END     = 0.40   # merge_progress above → full IDM vs bus
YIELD_GAP_IGNORE  = 50.0   # m — beyond this, bus ignored (matches governor clear-road)
YIELD_GAP_RAMP_M  = 25.0   # m — distance ramp: full urgency when gap ≤ (IGNORE - RAMP) = 25 m
YIELD_GAP_CLOSE_M = 20.0   # m — safety floor: must yield when bus encroaches within this range
YIELD_PRESENCE_START = 0.08  # polygon overlap fraction → start presence-based yield
YIELD_PRESENCE_FULL  = 0.35  # polygon overlap → treat like full merge progress

# Virtual blinker — IN_BAY pre-signal (vehicle.py _merge_yield_factor)
# Cars treat the parked bus as faintly present so they bleed off speed
# before the dwell ends, avoiding the IN_BAY → WAITING_TO_MERGE velocity cliff.
YIELD_IN_BAY_PRESENCE   = 0.10  # subtle awareness throughout dwell (no phantom jams)
YIELD_BLINKER_PRESENCE  = 0.25  # "about to merge" signal in last N seconds of dwell
YIELD_BLINKER_DWELL_S   = 3.0   # seconds before dwell end when blinker ramps up

# Bus merge scan window (car.position − bus.position); train + simulation parity
BUS_MERGE_SCAN_AHEAD_M  = 50.0  # m — cars ahead of bus front (merge blockers)
BUS_MERGE_SCAN_BEHIND_M = 20.0  # m — cars behind bus front (trailing threat)

# Physical limits shared by the vehicle model and the physics checks (busmerge.invariants)
MAX_BRAKE_MS2 = 9.0          # hardest braking a road vehicle can achieve (dry asphalt)

# Bus pulling into the bay: it stops only when road-parallel; while still angled it crawls
BUS_ALIGN_HEADING_DEG = 2.0  # heading within this counts as parallel to the kerb
BUS_CRAWL_SPEED_MS    = 1.5  # crawl speed while finishing the alignment past the stop point
BUS_STOPPED_SPEED_MS  = 0.05 # below this the bus counts as stopped

# Car stop-hold (bumper_kinematics) — implemented policy: Option A
CAR_STOP_HOLD_GAP_M      = 0.25  # engage hold when gap to bumper ≤ this and v low
HOLD_RELEASE_ADVANCE_M   = 0.15  # release hold when max_front advances this far past hold_x

# Bumper approach caps — avoid closing full min_gap in one frame (infinite-decel snaps)
BUMPER_APPROACH_FRAME_FRACTION = 0.6  # max fraction of remaining gap closable per step
BUMPER_OVERSHOOT_TRIM_M = 0.5  # max position snap per frame (micro-overshoot only)

# Lateral squeeze hysteresis (vehicle.py) — prevents Reacting/Squeezing state flutter
SQUEEZE_ENTER_URGENCY = 0.12  # enter squeeze above this (m lane deficit)
SQUEEZE_EXIT_URGENCY  = 0.02  # exit squeeze only below this (Schmitt trigger)

# Legacy aliases (telemetry / docs)
MERGE_YIELD_PROGRESS_MIN = YIELD_VIS_START
MERGE_YIELD_PRESENCE_MIN = YIELD_VIS_START
MERGE_YIELD_HEADING_DEG  = 3.0
MERGE_YIELD_DIST_MAX     = YIELD_GAP_IGNORE

# ---------------------------------------------------------------------------
# State vector normalisation ranges  (feature index → [clip_min, clip_max, norm])
# Each tuple: (clip_min, clip_max, norm_divisor_or_shift_divisor)
# ---------------------------------------------------------------------------
#   p_n   = merge_progress                               [0, 1]       as-is
#   ang_n = bus_heading_rad / 0.54                       [-0.54, 0.54]
#   lon_n = (lon_dist + 10) / 70                         [-10, 60]
#   lat_n = (lat_clearance + 2) / 6                      [-2, 4]
#   spd_n = car_speed / 20                               [0, 20]
#   acc_n = car_accel / 9                                [-9, 3]
#   wid_n = (car_width - 1.85) / 0.20                   [1.70, 2.05]
#   len_n = (car_length - 4.5) / 1.0                    [3.5, 5.5]
#   rs_n  = rel_speed / 15                              [-15, 15]
#   ra_n  = rel_accel / 15                              [-15, 15]
#   ca_n  = car_heading_rad / 0.15                      [-0.15, 0.15]

STATE_CLIP = {
    "merge_progress":  (0.0,   1.0),
    "bus_heading_rad": (-0.54, 0.54),
    "lon_dist":        (-10.0, 60.0),
    "lat_clearance":   (-2.0,  4.0),
    "car_speed":       (0.0,   20.0),
    "car_accel":       (-9.0,  3.0),
    "car_width":       (1.70,  2.05),
    "car_length":      (3.5,   5.5),
    "rel_speed":       (-15.0, 15.0),
    "rel_accel":       (-15.0, 15.0),
    "car_heading_rad": (-0.15, 0.15),
}

STATE_NORM = {
    "merge_progress":  (0.0,   1.0),      # (shift, divisor)
    "bus_heading_rad": (0.0,   0.54),
    "lon_dist":        (10.0,  70.0),
    "lat_clearance":   (2.0,   6.0),
    "car_speed":       (0.0,   20.0),
    "car_accel":       (0.0,   9.0),
    "car_width":       (1.85,  0.20),
    "car_length":      (4.5,   1.0),
    "rel_speed":       (0.0,   15.0),
    "rel_accel":       (0.0,   15.0),
    "car_heading_rad": (0.0,   0.15),
}
