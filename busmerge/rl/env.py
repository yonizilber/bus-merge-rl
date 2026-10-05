import numpy as np
import random
from collections import deque


# ---------------------------------------------------------------------------
# SAT overlap area — used by the ground-truth safety reward (exp7sat only)
# ---------------------------------------------------------------------------

def _rect_corners(cx: float, cy: float, half_l: float, half_w: float,
                  angle_rad: float) -> np.ndarray:
    """Return (4,2) array of rectangle corners rotated by angle_rad."""
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    dx = np.array([ half_l,  half_l, -half_l, -half_l], dtype=np.float64)
    dy = np.array([ half_w, -half_w, -half_w,  half_w], dtype=np.float64)
    xs = cx + dx * c - dy * s
    ys = cy + dx * s + dy * c
    return np.stack([xs, ys], axis=1)


def _clip_polygon_by_half_plane(poly: np.ndarray,
                                a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Sutherland-Hodgman clip — keeps vertices on the right side of directed edge a→b.
    Our rectangles use clockwise winding, so interior = right of each edge (cross <= 0)."""
    if len(poly) == 0:
        return poly
    out = []
    n = len(poly)
    edge = b - a
    for i in range(n):
        cur = poly[i]
        nxt = poly[(i + 1) % n]
        # CW winding: inside = right of edge = cross product <= 0
        cur_inside = float(np.cross(edge, cur - a)) <= 0.0
        nxt_inside = float(np.cross(edge, nxt - a)) <= 0.0
        if cur_inside:
            out.append(cur)
        if cur_inside != nxt_inside:
            denom = float(np.cross(edge, nxt - cur))
            if abs(denom) > 1e-12:
                t = float(np.cross(edge, a - cur)) / denom
                out.append(cur + t * (nxt - cur))
    return np.array(out, dtype=np.float64) if out else np.empty((0, 2))


def _polygon_area(poly: np.ndarray) -> float:
    """Shoelace formula for a convex polygon (4+ vertices)."""
    if len(poly) < 3:
        return 0.0
    n = len(poly)
    xs, ys = poly[:, 0], poly[:, 1]
    return 0.5 * abs(
        float(np.dot(xs, np.roll(ys, -1)) - np.dot(ys, np.roll(xs, -1)))
    )


def compute_sat_overlap_area(bus_corners: np.ndarray,
                             car_corners: np.ndarray) -> float:
    """
    Area (m²) of the intersection of two convex rectangles.
    Returns 0.0 when they do not overlap.
    Uses Sutherland-Hodgman clipping of bus polygon against each edge of car.
    """
    clip = bus_corners.copy()
    n = len(car_corners)
    for i in range(n):
        if len(clip) == 0:
            return 0.0
        a = car_corners[i]
        b = car_corners[(i + 1) % n]
        clip = _clip_polygon_by_half_plane(clip, a, b)
    return _polygon_area(clip)

from busmerge.vehicle import Vehicle, Bus, BusState, CAR_PARAMS, sample_vehicle_params
from busmerge.rl.merge_constants import (
    BUS_WIDTH, BUS_LENGTH, LANE_WIDTH, BAY_DEPTH,
    BUS_MAX_SPEED as _MC_BUS_MAX_SPEED, MERGE_ACCEL_MAX as _MC_MERGE_ACCEL_MAX,
)

# ---------------------------------------------------------------------------
# Kinematic constants — imported from busmerge/rl/merge_constants.py (single source of truth)
# ---------------------------------------------------------------------------
STRAIGHTEN_ZONE = 5.0       # metres from stop: autopilot begins counter-steer


class BusMergeEnv:
    """
    Bus-merge RL environment — Phase C steering-first rewrite.

    Action space  : 2D continuous in [-1, 1]^2
                    action[0] = steer_intent  (+1 = full right / into lane)
                    action[1] = gas_intent    (+1 = full throttle, -1 = brake)

    State vector  : 11 features (see _encode_state docstring)

    Physics       : The bicycle model in Vehicle.update_physics() is the ONLY
                    thing that moves the bus.  No direct writes to
                    lateral_velocity, position, or velocity.

    Merge progress: Derived from actual lateral_offset, not a stored scalar.
                    merge_progress = clip((offset - BAY_DEPTH) / (-BAY_DEPTH), 0, 1)
                    0 = bus fully in bay, 1 = bus fully back in traffic lane.
    """

    # Physical limits — imported from merge_constants.py (single source of truth)
    BUS_MAX_SPEED   = _MC_BUS_MAX_SPEED
    MERGE_ACCEL_MAX = _MC_MERGE_ACCEL_MAX

    def __init__(self, eval_mode=False, governor_disabled=False):
        self.dt        = 0.1
        self.max_steps = 250   # 25 s max — halved so terminal rewards stay visible under discounting
        self.eval_mode = eval_mode
        self.governor_disabled = governor_disabled

        # Network dimensions (4 / 7 / 11 — set by scripts/train.py on experiment branch)
        self.feature_dim = 11
        self.state_size  = self.feature_dim
        self.action_size = 2   # (steer_intent, gas_intent)

        self.bus      = None
        self.vehicles = []
        self.current_step = 0
        self.last_intervened = False
        self.last_shield_condition = ""
        self.episode_shields = 0
        self.last_success = False
        self.last_crash   = False
        self.last_timeout = False

        # Domain-randomization controls set externally by train_ppo
        self.noise_sigma          = 0.0
        self.shield_penalty_scale = 1.0
        self._prev_bus_vel        = 0.0
        self.sat_penalty_enabled  = False   # True only for exp7sat run-tag
        self.spongy_danger_zone_enabled = False  # True only for exp7satv10 run-tag
        # Production-bridge mode (set by train_ppo in Phase 3): spawn
        # a Poisson queue matching SimulationEngine Scenario B instead of
        # static scenarios — closes the train-vs-production environment gap.
        self._production_bridge   = False
        self._prod_traffic_rate   = 0.4
        from busmerge.rl.feature_encoding import PerceptionNoiseState
        self._perception_noise = PerceptionNoiseState()

        # Active Governor state
        self.last_governor_veto    = False
        self.last_governor_reason  = ""
        self.episode_governor_vetos = 0
        self._governor_raw_steer   = 0.0

        # ── Telemetry history buffer (last 30 steps, ring buffer) ─────
        self._step_history: deque = deque(maxlen=30)
        self._crash_count = 0
        self._prev_action = np.zeros(2, dtype=np.float32)
        self._action_volatility_sum   = 0.0
        self._action_volatility_count = 0
        self._max_trailing_decel      = 0.0   # cumulative across all episodes this run
        # Extended QoD trackers
        self._hesitation_steps   = 0
        self._merge_started      = False
        self._merge_steps        = 0
        self._reversal_count     = 0
        self._progress_advancing = False
        self._prev_progress_rv   = 0.0
        self._peak_steer_jerk    = 0.0
        self._gap_at_success     = -1.0
        self._total_steps        = 0
        self._passive_steps      = 0   # steps: agent passive AND progress < 0.10
        self.reward_profile      = "core"  # "phase1" adds shaping for Scenario G curriculum

    # ------------------------------------------------------------------
    # Helper: lateral progress 0 (in bay) → 1 (in lane)
    # ------------------------------------------------------------------
    def _merge_progress(self):
        """Merge progress derived from actual lateral_offset of the bus."""
        return float(np.clip(
            (self.bus.lateral_offset - BAY_DEPTH) / (-BAY_DEPTH), 0.0, 1.0))

    # ------------------------------------------------------------------
    # State encoding
    # ------------------------------------------------------------------
    def _apply_sensor_noise(
        self,
        merge_progress: float,
        bus_heading_rad: float,
        lon_dist: float,
        lat_clearance: float,
        car_speed: float,
        car_accel: float,
        car_width: float,
        car_length: float,
        rel_speed: float,
        rel_accel: float,
        car_heading_rad: float,
        car_id=None,
    ):
        """Human perception noise (OU biases, train only). Governor/shield use truth."""
        if self.eval_mode or self.noise_sigma <= 0.0:
            return (
                merge_progress, bus_heading_rad, lon_dist, lat_clearance,
                car_speed, car_accel, car_width, car_length,
                rel_speed, rel_accel, car_heading_rad,
            )
        from busmerge.rl.feature_encoding import apply_sensor_noise
        return apply_sensor_noise(
            self.noise_sigma,
            merge_progress, bus_heading_rad, lon_dist, lat_clearance,
            car_speed, car_accel, car_width, car_length,
            rel_speed, rel_accel, car_heading_rad,
            noise_state=self._perception_noise,
            dt=self.dt,
            car_id=car_id,
        )

    def _encode_state(self, merge_progress, bus_heading_rad, lon_dist, lat_clearance,
                      car_speed, car_accel, car_width, car_length,
                      rel_speed, rel_accel, car_heading_rad):
        """
        Encode 11 features into a normalised state vector for the PPO network.

        Feature  0 : merge_progress     — 0=in bay, 1=in lane   [0, 1]
        Feature  1 : bus_heading_rad    — kinematic bicycle model heading [-0.54, 0.54] rad (31°)
        Feature  2 : lon_dist           — longitudinal gap bus-rear to car-front  [-10, 60] m
        Feature  3 : lat_clearance      — side gap between bus outer edge and car  [-2, 4] m
        Feature  4 : car_speed          — nearest car longitudinal speed [0, 20] m/s
        Feature  5 : car_accel          — nearest car acceleration [-9, 3] m/s²
        Feature  6 : car_width          — nearest car width [1.70, 2.05] m
        Feature  7 : car_length         — nearest car length [3.5, 5.5] m
        Feature  8 : rel_speed          — bus_vel − car_vel [-15, 15] m/s
        Feature  9 : rel_accel          — bus_accel − car_accel [-15, 15] m/s²
        Feature 10 : car_heading_rad    — nearest car bicycle-model heading [-0.15, 0.15] rad

        feature_dim selects 4-, 7-, or 11-dim output (see busmerge/rl/feature_encoding.py).
        """
        from busmerge.rl.feature_encoding import encode_features
        return encode_features(
            getattr(self, "feature_dim", 11),
            merge_progress, bus_heading_rad, lon_dist, lat_clearance,
            car_speed, car_accel, car_width, car_length,
            rel_speed, rel_accel, car_heading_rad,
            noise_sigma=0.0,
        )

    def _governor_check(self, steer_intent: float, gas_intent: float):
        from busmerge.rl.governor_logic import governor_check
        gap, _, _, _, rel_speed, nearest_car = self._scan_nearest_car()
        progress = self._merge_progress()
        return governor_check(
            steer_intent, gas_intent, progress, gap, rel_speed, nearest_car,
            disabled=self.governor_disabled,
        )

    def _scan_nearest_car(self):
        """Return nearest relevant car context in physical units (shared with simulation)."""
        from busmerge.rl.merge_yield import scan_nearest_car_for_merge
        return scan_nearest_car_for_merge(self.bus, self.vehicles)



    def _log_crash_diagnostics(self):
        """
        BLACK-BOX INCIDENT REPORT — printed to stdout every time a crash fires.
        Shows the last 30 steps (= 3 s) of telemetry so we can see exactly
        what the agent, governor, and trailing car were doing before impact.
        """
        h = list(self._step_history)
        n_rows = len(h)

        _last = h[-1] if h else {}
        print()
        _ec = chr(0x1f6a8)
        _tag = "(11-Feat Run #" + str(self._crash_count) + ")"
        print(_ec + " CRASH DETECTED " + _tag + " " + _ec)
        print(
            f"  [Geometry]   Progress: "
            f"{_last.get('progress', 0):.2f}"
            f" | Gap: {_last.get('gap_m', 0):.1f}m")
        print(
            f"  [Kinematics] Bus Spd: "
            f"{_last.get('bus_vel', 0):.1f}m/s"
            f" | Car Spd: "
            f"{_last.get('car_vel', 0):.1f}m/s"
            f" | Rel Spd: "
            f"{_last.get('rel_spd', 0):.1f}m/s")
        print(
            f"  [Agent]      "
            f"Last Steer: {_last.get('steer_agent', 0):.2f}"
            f" | Last Gas: "
            f"{_last.get('gas_agent', 0):.2f}")

        # ── Summary stats over visible window ──
        if n_rows >= 3:
            last3_gas_agent  = [r['gas_agent']    for r in h[-3:]]
            last3_steer_ag   = [r['steer_agent']  for r in h[-3:]]
            last3_car_decel  = [r['car_accel']    for r in h[-3:] if r['car_accel'] < 0]
            gov_veto_count   = sum(1 for r in h if r['gov_veto'])
            gov_reasons      = [r['gov_reason'] for r in h if r['gov_veto']]
            dz_entries       = [r for r in h if r['progress'] > 0.5]

            print(f"  SUMMARY over last {n_rows} steps:")
            print(f"    Agent last 3 steps — steer={[round(v,2) for v in last3_steer_ag]}  gas={[round(v,2) for v in last3_gas_agent]}")
            print(f"    Governor vetos in window: {gov_veto_count}  reasons={gov_reasons[:5]}")
            if last3_car_decel:
                print(f"    Car decels in last 3: {[round(v,2) for v in last3_car_decel]}  (max cap -9 m/s²)")
            else:
                print(f"    Car decels in last 3: NONE (car was NOT braking hard)")
            if dz_entries:
                ttcs_dz = [r['ttc_s'] for r in dz_entries if r['ttc_s'] < 999]
                min_ttc = min(ttcs_dz) if ttcs_dz else float('inf')
                avg_gas_dz = sum(r['gas_agent'] for r in dz_entries) / len(dz_entries)
                print(f"    In danger zone (progress>0.5): {len(dz_entries)} steps  "
                      f"min_TTC={min_ttc:.2f}s  avg_gas_agent={avg_gas_dz:.3f}")
        print()

    def reset(self):
        self.current_step  = 0
        self._prev_bus_vel = 0.0
        self.episode_shields = 0
        self.last_shield_condition = ""
        self.episode_governor_vetos = 0
        self.last_governor_veto     = False
        self.last_governor_reason   = ""
        self._step_history.clear()
        self._prev_action = np.zeros(2, dtype=np.float32)
        self._action_volatility_sum   = 0.0
        self._action_volatility_count = 0
        self._max_trailing_decel      = 0.0
        # Extended QoD trackers reset
        self._hesitation_steps   = 0
        self._merge_started      = False
        self._merge_steps        = 0
        self._reversal_count     = 0
        self._progress_advancing = False
        self._prev_progress_rv   = 0.0
        self._peak_steer_jerk    = 0.0
        self._gap_at_success     = -1.0
        self._total_steps        = 0
        self._passive_steps      = 0
        self._stagnation_steps   = 0   # steps stalled in partially-merged zone
        self._perception_noise.reset()

        # 1. Spawn Bus fully in the bay, waiting to merge.
        #    lateral_offset = BAY_DEPTH (-3.5 m) = physically inside the bay.
        #    heading_angle  = 0 (bus parked parallel to curb).
        #    lat_target     = 0 (destination: back in the traffic lane).
        self.bus = Bus(v_id=999, position=300.0, velocity=0.0, params=CAR_PARAMS)
        self.bus.state = BusState.WAITING_TO_MERGE
        from busmerge.rl.traffic_leaders import reset_bus_leader_geometry
        reset_bus_leader_geometry(self.bus)
        self.bus.merge_start_x = self.bus.position
        # --- PHYSICS INITIALISATION (bicycle model state) ---
        self.bus.lateral_offset  = BAY_DEPTH   # bus is in bay
        self.bus.lat_target      = 0.0         # destination: traffic lane centre
        # heading_angle / steer_angle / lateral_velocity are left at their
        # Vehicle.__init__ defaults (0.0) for the RL spawn; in the full simulation
        # they are inherited from the parking manoeuvre.
        # Keep _merge_progress for reward shaping / backward compat with production logs
        self.bus._merge_progress = 0.0

        # Sloppy Bay Entry: domain randomisation of bus spawn position.
        # Simulates imperfect bay entry by a real driver (training only).
        if not self.eval_mode:
            _lon_noise  = random.uniform(-2.0,  2.0)   # ±2 m longitudinal
            _lat_noise  = random.uniform(-0.4,  0.4)   # ±0.4 m lateral
            _hdg_noise  = random.uniform(-0.08, 0.08)  # ±0.08 rad (~4.6°)
            # Longitudinal: keep bus clearly inside flat bay section [285, 315]
            self.bus.position = float(np.clip(
                self.bus.position + _lon_noise, 285.0, 315.0))
            # Lateral: keep bus entirely inside the bay.
            #   Bus half-width ≈ 1.25 m; inner lane edge ≈ -1.75 m
            #   → centre must stay ≤ -3.0 m; outer bay wall ≈ -5.25 m
            #   → centre must stay ≥ -4.0 m
            self.bus.lateral_offset = float(np.clip(
                BAY_DEPTH + _lat_noise, -4.0, -3.0))
            # Heading: small initial misalignment, clipped symmetrically
            self.bus.heading_angle = float(np.clip(_hdg_noise, -0.08, 0.08))

        # Bus power variance (training only): ±20% on max merge speed authority.
        if not self.eval_mode:
            power_factor = random.uniform(0.80, 1.20)
            self.bus.max_merge_progress_step = 0.02 * power_factor

        # 2. Traffic scenario
        # Design rules:
        #   - Enough cars (incl. negative start positions) so the episode
        #     does NOT end with a permanently clear road in most scenarios.
        #   - Cars at negative positions arrive at t=(300-pos)/speed seconds.
        #   - eval_mode always uses Scenario F (dense fast stream).
        self.vehicles = []
        # Scenario G (warm-up): probability controlled by self._warmup_prob (float 0.0-1.0).
        # The training script sets _warmup_prob per epoch via a 3-phase curriculum:
        #   Phase 1 (epochs 0-phase1_end):       _warmup_prob = 1.0  -> always Scenario G
        #   Phase 2 (phase1_end-phase2_end):     _warmup_prob linear 1.0->0.0  (mixed)
        #   Phase 3 (phase2_end-end):             _warmup_prob = 0.0  -> full traffic
        # This fixes the v7 failure: the old 25% rate was swamped by 75% dense-traffic
        # episodes, so the agent never saw enough successes to learn the merge policy.
        # Production-bridge mode: simulate the Streamlit/SimulationEngine traffic queue.
        # When enabled (train sets _production_bridge=True in Phase 3),
        # skip static scenario placement and use _spawn_production_queue() instead.
        _use_prod_bridge = (not self.eval_mode
                            and getattr(self, '_production_bridge', False))

        _use_warmup = (not self.eval_mode
                       and not _use_prod_bridge
                       and random.random() < getattr(self, '_warmup_prob', 0.0))
        if _use_warmup:
            # Scenario 0 (empty road) when _zero_road_prob > 0: used in the very first
            # epochs so the brain sees "steer → success" with zero crash risk.
            # Falls back to Scenario G once this probability is set to 0.0.
            if random.random() < getattr(self, '_zero_road_prob', 0.0):
                scenario_roll = -2.0   # sentinel: Scenario 0 (empty road)
            else:
                scenario_roll = -1.0   # sentinel: Scenario G
        elif _use_prod_bridge:
            scenario_roll = -3.0   # sentinel: Scenario P (production bridge)
        elif self.eval_mode:
            # Rotate eval across A-F evenly (was always F)
            scenario_roll = getattr(self, '_eval_scenario_seed', random.random())
        else:
            scenario_roll = random.random()

        if scenario_roll < -2.5:
            # SCENARIO P: PRODUCTION BRIDGE (Phase 3 training only)
            # Simulates the car queue that builds up during a real Streamlit run:
            # ~45 s of Poisson arrivals at traffic_rate cars/s, then IDM-settled.
            # Removes the gap between training and production traffic geometry.
            _rate = getattr(self, '_prod_traffic_rate', 0.4)
            self._spawn_production_queue(traffic_rate=_rate)

        elif scenario_roll < -1.5:
            # SCENARIO 0: EMPTY ROAD (training only, first N epochs via _zero_road_prob)
            # Zero cars — crash is impossible.  Sole goal: steer into lane → +5000.
            # Teaches the brain that steer=1, gas=1 on an empty road is optimal.
            pass  # no vehicles to add

        elif scenario_roll < 0.0:
            # SCENARIO G: SPARSE WARM-UP (training only, first 60 epochs)
            # 2-4 cars at 40+ m spacing — guarantees a safe merge window.
            # Teaches the agent what success (+5000) feels like.
            num_cars = random.randint(2, 4)
            base_spacing = random.uniform(40.0, 70.0)
            for i in range(num_cars):
                dist = random.uniform(40.0, 80.0) + i * base_spacing
                _, sampled_params = sample_vehicle_params()
                speed = max(4.0, sampled_params.max_speed * random.uniform(0.35, 0.65))
                car = Vehicle(v_id=i, position=300.0 - dist, velocity=speed, params=sampled_params)
                self.vehicles.append(car)

        elif scenario_roll < 0.12:
            # SCENARIO A: HEAVY JAM (12%)
            # Near-standstill queue. Road does NOT clear in 50 s.
            num_cars = random.randint(8, 12)
            for i in range(num_cars):
                spacing = random.uniform(4.0, 8.0)
                dist = random.uniform(6.0, 12.0) + i * (spacing + 4.5)
                _, sampled_params = sample_vehicle_params()
                self._maybe_distract(sampled_params)
                speed = random.uniform(0.0, 1.5)
                car = Vehicle(v_id=i, position=300.0 - dist, velocity=speed, params=sampled_params)
                self.vehicles.append(car)

        elif scenario_roll < 0.30:
            # SCENARIO B: SLOW CITY STREAM (18%)
            # 14-20 cars, 4-8 m/s. Negative-position cars ensure fresh
            # arrivals throughout the 50 s episode.
            num_cars = random.randint(14, 20)
            base_spacing = random.uniform(10.0, 18.0)
            base_speed_mult = random.uniform(0.30, 0.55)   # ~4-8 m/s
            for i in range(num_cars):
                dist = random.uniform(6.0, 14.0) + i * base_spacing
                _, sampled_params = sample_vehicle_params()
                self._maybe_distract(sampled_params)
                speed = max(3.0, sampled_params.max_speed * base_speed_mult)
                car = Vehicle(v_id=i, position=300.0 - dist, velocity=speed, params=sampled_params)
                self.vehicles.append(car)

        elif scenario_roll < 0.50:
            # SCENARIO C: MID-MERGE RESILIENCE (20%)
            # Bus starts in bay (same as Streamlit); 4-8 cars at mixed speeds.
            num_cars = random.randint(4, 8)
            base_spacing = random.uniform(10.0, 22.0)
            for i in range(num_cars):
                dist = random.uniform(6.0, 20.0) + i * base_spacing
                _, sampled_params = sample_vehicle_params()
                self._maybe_distract(sampled_params)
                speed = max(3.0, sampled_params.max_speed * random.uniform(0.30, 0.90))
                car = Vehicle(v_id=i, position=300.0 - dist, velocity=speed, params=sampled_params)
                self.vehicles.append(car)

        elif scenario_roll < 0.65:
            # SCENARIO D: URBAN MAIN ROAD -- FAST FLOW (15%)
            # 16-22 cars, 29-50 km/h (8-13.9 m/s), negative positions for full-episode coverage.
            num_cars = random.randint(16, 22)
            base_spacing = random.uniform(20.0, 30.0)
            base_speed_mult = random.uniform(0.55, 0.85)   # ~8-13.9 m/s (max 50 km/h)
            for i in range(num_cars):
                dist = random.uniform(8.0, 16.0) + i * base_spacing
                _, sampled_params = sample_vehicle_params()
                speed = min(13.9, max(8.0, sampled_params.max_speed * base_speed_mult))
                car = Vehicle(v_id=i, position=300.0 - dist, velocity=speed, params=sampled_params)
                self.vehicles.append(car)

        elif scenario_roll < 0.82:
            # SCENARIO E: PLATOON BURST / POST-TRAFFIC-LIGHT (17%)
            # 3-4 tight groups separated by 60-120 m gaps.
            # Groups extend into negative positions -> 3-4 gap windows per episode.
            num_groups = random.randint(3, 4)
            v_id = 0
            current_dist = random.uniform(8.0, 18.0)
            for g in range(num_groups):
                group_size = random.randint(4, 6)
                within_spacing = random.uniform(8.0, 14.0)
                group_speed_mult = random.uniform(0.60, 0.95)
                for j in range(group_size):
                    dist = current_dist + j * (within_spacing + 4.5)
                    _, sampled_params = sample_vehicle_params()
                    self._maybe_distract(sampled_params)
                    speed = max(6.0, sampled_params.max_speed * group_speed_mult)
                    car = Vehicle(v_id=v_id, position=300.0 - dist, velocity=speed, params=sampled_params)
                    self.vehicles.append(car)
                    v_id += 1
                current_dist += group_size * (within_spacing + 4.5) + random.uniform(60.0, 120.0)

        elif scenario_roll >= 0.98:
            # SCENARIO H: BUMPER-TO-BUMPER DENSE STREAM (eval only, 5 fixed seeds)
            # Purpose: forces the brain to merge into yielded-car gaps rather than
            # waiting for a natural 999 m clear road. Without this scenario, eval
            # Gap@OK = 999 m and a do-nothing brain scores 800/800.
            # 22-28 cars, 8-12 m headway, 36-50 km/h (10-13.9 m/s).
            # No natural gap ever appears — brain must merge or timeout.
            num_cars = random.randint(22, 28)
            headway = random.uniform(8.0, 12.0)
            base_speed_mult = random.uniform(0.72, 0.88)
            for i in range(num_cars):
                dist = random.uniform(5.0, 9.0) + i * (headway + 4.5)
                _, sampled_params = sample_vehicle_params()
                speed = min(13.9, max(9.5, sampled_params.max_speed * base_speed_mult))
                car = Vehicle(v_id=i, position=300.0 - dist, velocity=speed, params=sampled_params)
                self.vehicles.append(car)

        else:
            # SCENARIO F: DENSE URBAN STREAM (18% training + all eval)
            # 20-26 cars, 36-50 km/h (10-13.9 m/s), 18-25 m spacing.
            # Spans bus stop back to ~-300 m -> NO clear-road window.
            # scenario_roll=1.0 (eval_mode) always lands here.
            num_cars = random.randint(20, 26)
            base_spacing = random.uniform(18.0, 25.0)
            base_speed_mult = random.uniform(0.70, 0.90)   # ~10-13.9 m/s (max 50 km/h)
            for i in range(num_cars):
                dist = random.uniform(8.0, 14.0) + i * base_spacing
                _, sampled_params = sample_vehicle_params()
                speed = min(13.9, max(9.0, sampled_params.max_speed * base_speed_mult))
                car = Vehicle(v_id=i, position=300.0 - dist, velocity=speed, params=sampled_params)
                self.vehicles.append(car)

        return self._get_state()

    def _spawn_production_queue(self, traffic_rate: float = 0.4,
                                 dwell_time: float = 15.0,
                                 approach_time: float = 30.0):
        """Simulate the car queue that would build up during a real production scenario.

        In Streamlit/SimulationEngine (Scenario B) the bus travels ~300 m
        (≈30 s at 10 m/s), then dwells ~15 s in the bay before the brain
        acts.  During those ~45 s, cars spawn at `traffic_rate` cars/s at x=0
        and travel toward x=300 m.  We reproduce that queue snapshot
        mathematically so training episodes see the same traffic geometry
        without the 45 s sim warmup cost.

        Method: place cars whose positions are consistent with Poisson arrivals
        at rate λ over `approach_time + dwell_time` seconds, then fast-forward
        their positions using their individual speeds.
        """
        total_time = approach_time + dwell_time
        # Expected number of cars that would arrive during total_time.
        expected = traffic_rate * total_time
        # Sample Poisson count (cap at 35 to avoid pathological overflows).
        n_cars = min(int(np.random.poisson(max(0.0, expected))), 35)
        if n_cars == 0:
            return

        # Spawn times: uniform on [0, total_time], sorted ascending.
        spawn_times = sorted(np.random.uniform(0.0, total_time, n_cars))
        # Position = distance traveled since spawn = speed × (total_time - spawn_time)
        v_id = 0
        for t_spawn in spawn_times:
            _, params = sample_vehicle_params()
            speed = float(np.clip(
                params.max_speed * np.random.uniform(0.5, 0.95), 4.0, 13.9))
            travel_time = total_time - t_spawn
            pos = speed * travel_time  # distance from x=0

            # Only keep cars that haven't passed the bus stop yet (x < 300 m)
            # and are within the scan window (x >= 300 - 300 = 0).
            if pos >= 300.0:
                continue   # already past the stop; skip

            x = pos  # absolute position (x=0 is road start)
            car = Vehicle(v_id=v_id, position=x, velocity=speed, params=params)
            self.vehicles.append(car)
            v_id += 1

        # Run IDM for a few ticks to let the queue settle (removes unrealistic
        # overlaps from the Poisson placement without zeroing gaps entirely).
        from busmerge.rl.traffic_leaders import resolve_car_leader
        for _ in range(5):
            self.vehicles.sort(key=lambda v: v.position, reverse=True)
            chain = self.vehicles[:]
            for idx, veh in enumerate(chain):
                veh._physics_mode = "training"
                leader, _ = resolve_car_leader(chain, idx, self.bus)
                veh.update_physics(self.dt, leader=leader, bus=self.bus)

    def reset_until_clear_spawn(self, max_retries: int = 20, reroll_callback=None):
        """Deprecated: the production-bridge reset no longer re-rolls away overlaps.

        Kept for call-site compatibility in train.py; now just calls
        reset() once and returns.  The agent must learn to wait through tight
        gaps, not avoid them.
        """
        return self.reset()

    def step(self, action_value):
        """
        action_value : np.ndarray shape (2,) or (1,2)  — [steer_intent, gas_intent] in [-1,1]
        """
        self.current_step += 1
        self.last_intervened = False
        self.last_shield_condition = ""
        self.last_success = False
        self.last_crash   = False
        self.last_timeout = False
        self.last_governor_veto   = False
        self.last_governor_reason = ""

        # ── 1. PARSE 2D ACTION ────────────────────────────────────────────────────
        # Flatten to 1D regardless of input shape
        action_arr = np.asarray(action_value, dtype=np.float32).flatten()
        _vol = float(np.sum(np.abs(action_arr - self._prev_action)))
        _steer_jerk = float(abs(action_arr[0] - self._prev_action[0]))
        self._peak_steer_jerk = max(self._peak_steer_jerk, _steer_jerk)
        self._action_volatility_sum   += _vol
        self._action_volatility_count += 1
        self._prev_action = action_arr.copy()
        steer_intent = float(np.clip(action_arr[0], -1.0, 1.0))  # +1 = steer into lane
        gas_intent   = float(np.clip(action_arr[1], -1.0, 1.0))  # +1 = accelerate
        _raw_steer_agent = steer_intent   # agent's unmodified intent (for telemetry)
        _raw_gas_agent   = gas_intent

        # Map gas_intent → target speed: symmetric linear mapping.
        # -1.0 → 0.0 m/s (full stop), 0.0 → half speed, +1.0 → BUS_MAX_SPEED.
        # Eliminates the dead zone where all [-1,0) mapped to zero speed,
        # which froze the bicycle model and wasted half the action space.
        speed_target = (gas_intent + 1.0) / 2.0 * self.BUS_MAX_SPEED

        # Map steer_intent → lateral target offset
        # steer_intent=+1 → lat_target=0 (traffic lane); steer_intent=-1 → lat_target=BAY_DEPTH
        lat_target = steer_intent * 0.0 + (1.0 - abs(steer_intent)) * self.bus.lateral_offset
        # Simpler linear mapping: +1 pushes fully into lane, -1 stays in bay
        lat_target = np.interp(steer_intent, [-1.0, 1.0], [BAY_DEPTH, 0.0])

        self._prev_bus_vel = self.bus.velocity

        # ── 1b. ACTIVE GOVERNOR (predictive kinematic check) ────────────────────
        # Store the agent's raw intent BEFORE any override so the reward
        # penalty is proportional to how dangerous the requested action was.
        self._governor_raw_steer = steer_intent
        _gov_safe, steer_intent, gas_intent, _gov_reason = \
            self._governor_check(steer_intent, gas_intent)
        if not _gov_safe:
            self.last_governor_veto   = True
            self.last_governor_reason = _gov_reason
            self.episode_governor_vetos += 1

        # ── 2. SAFETY SHIELD (shared busmerge/rl/governor_logic.py) ───────────────────────
        from busmerge.rl.governor_logic import apply_safety_shield
        nearest_gap, nearest_speed, _, nearest_width, rel_speed, nearest_car = self._scan_nearest_car()
        raw_steer  = steer_intent
        raw_gas    = gas_intent
        progress = self._merge_progress()
        steer_intent, gas_intent, shield_cond = apply_safety_shield(
            steer_intent, gas_intent, progress, nearest_gap, rel_speed,
            nearest_speed, nearest_car, nearest_width,
            governor_reason=self.last_governor_reason, dt=self.dt,
        )
        self.last_shield_condition = shield_cond
        intervened = (
            shield_cond != ""
            or abs(raw_steer - steer_intent) > 1e-6
            or abs(raw_gas - gas_intent) > 1e-6
        )
        self.last_intervened = intervened
        if intervened:
            self.episode_shields += 1
        intervention_strength_steer = abs(raw_steer - steer_intent) / max(abs(raw_steer), 1e-8)
        intervention_strength = float(np.clip(intervention_strength_steer, 0.0, 1.0))

        # ── 3. TRANSLATE SHIELD OUTPUT BACK TO AUTOPILOT TARGETS ─────────────────
        lat_target   = np.interp(steer_intent, [-1.0, 1.0], [BAY_DEPTH, 0.0])
        if gas_intent >= 0.0:
            speed_target = gas_intent * self.BUS_MAX_SPEED
        else:
            speed_target = 0.0

        # ── 4. APPLY TARGETS TO BUS (autopilot writes lat_target; bicycle does the rest) ──
        self.bus.lat_target = lat_target

        # Longitudinal autopilot: simple proportional controller on speed
        # accel = k*(speed_target - current_velocity), clamped to comfort bounds
        speed_error = speed_target - self.bus.velocity
        desired_accel = np.clip(2.0 * speed_error, -3.0, self.MERGE_ACCEL_MAX)
        # Override IDM during merge: set acceleration directly (bus is out of lane)
        self.bus.acceleration = desired_accel

        # ── 5. PHYSICS TICK ──────────────────────────────────────────────────────
        # Update bus physics (bicycle model — uses lat_target set above)
        from busmerge.rl.bumper_kinematics import limit_bus_to_cars_ahead, finalize_bus_bumper
        self.bus.velocity = max(0.0, self.bus.velocity + self.bus.acceleration * self.dt)
        limit_bus_to_cars_ahead(
            self.bus, self.vehicles, self.dt, allow_retreat=False,
        )
        self.bus.position += self.bus.velocity * self.dt
        finalize_bus_bumper(self.bus, self.vehicles)
        # Bicycle model for lateral motion
        max_steer  = np.radians(self.bus.params.max_steer_angle_deg)
        steer_rate = np.radians(self.bus.params.steer_rate_deg_per_s)
        lookahead   = max(self.bus.velocity * 1.0, 5.0)
        lat_error   = self.bus.lat_target - self.bus.lateral_offset
        delta_target = np.clip(np.arctan2(lat_error, lookahead), -max_steer, max_steer)
        steer_change = np.clip(delta_target - self.bus.steer_angle, -steer_rate * self.dt, steer_rate * self.dt)
        self.bus.steer_angle   += steer_change
        wheelbase = self.bus.params.wheelbase
        self.bus.heading_angle += (self.bus.velocity * np.tan(self.bus.steer_angle) / max(wheelbase, 0.1)) * self.dt
        self.bus.heading_angle  = np.clip(self.bus.heading_angle, -np.radians(60.0), np.radians(60.0))
        self.bus.lateral_velocity = self.bus.velocity * np.sin(self.bus.heading_angle)
        self.bus.lateral_offset  += self.bus.lateral_velocity * self.dt
        self.bus.lateral_offset   = np.clip(self.bus.lateral_offset, -4.5, 0.5)

        # O-U lane-keeping noise for bus
        _ou_rev = 0.4
        _ou_sig = getattr(self.bus.params, 'lane_keeping_noise', 0.05)
        self.bus.lane_drift = ((1.0 - _ou_rev * self.dt) * self.bus.lane_drift
                               + _ou_sig * np.sqrt(self.dt) * np.random.randn())
        self.bus.lane_drift = np.clip(self.bus.lane_drift, -0.20, 0.20)

        # Keep _merge_progress in sync for backward compat (production state machine, logs)
        self.bus._merge_progress = self._merge_progress()

        # Cars: same leader rules as simulation (bus in sorted chain + early yield)
        from busmerge.rl.traffic_leaders import resolve_car_leader
        chain = sorted(self.vehicles + [self.bus], key=lambda v: v.position, reverse=True)
        for idx, veh in enumerate(chain):
            if veh is self.bus:
                continue
            veh._physics_mode = "training"
            leader, _ = resolve_car_leader(chain, idx, self.bus)
            veh.update_physics(self.dt, leader=leader, bus=self.bus)

        # ── 6. COMPUTE REWARDS (simplified 5-term core) ──────────────────────────
        # Phase 4 simplification: removed ~15 overlapping shaping terms that
        # produced exploit collapses (hold→timeout, gap@OK=999 m).
        # Core terms only; add more only if training diverges.
        reward = -1.0   # Term 1: time penalty — always discourage waiting
        done   = False

        gap, car_speed, car_accel, car_width, rel_speed, _ = self._scan_nearest_car()
        self._max_trailing_decel = min(self._max_trailing_decel, car_accel)
        progress = self._merge_progress()
        state = self._get_state()

        # QoD trackers (unchanged — these are telemetry, not reward)
        self._total_steps += 1
        if not self._merge_started:
            if progress >= 0.01:
                self._merge_started = True
            else:
                self._hesitation_steps += 1
        if self._merge_started:
            self._merge_steps += 1
        _dp = progress - self._prev_progress_rv
        if _dp > 0.01:
            self._progress_advancing = True
        elif _dp < -0.01 and self._progress_advancing:
            self._progress_advancing = False
            self._reversal_count += 1
        self._prev_progress_rv = progress

        # Term 1b: patience reward — hold still when lane blocked at bay (v9)
        # Net -0.5/step (vs -1.0 idle panic) teaches wait-then-merge through overlaps.
        _raw_steer_wait = getattr(self, "_governor_raw_steer", 0.0)
        if (gap < 0.0 and progress < 0.15
                and self.bus.velocity < 0.5
                and abs(_raw_steer_wait) < 0.25):
            reward += 0.5

        # Term 2: lateral progress toward lane (always rewarded; halved when gap is unsafe)
        lateral_delta = self.bus.lateral_velocity * self.dt   # positive = into lane
        if lateral_delta > 0:
            _gap_scale = 0.5 if (0.0 <= gap < 2.0) else 1.0
            reward += lateral_delta / (-BAY_DEPTH) * 55.0 * _gap_scale

        # Term 3: closing-risk penalty (gap-based; replaces TTC+danger-zone+near-risk tangle)
        if 0.0 < gap < 12.0 and rel_speed > 0.5:
            gap_risk   = (12.0 - gap) / 12.0
            speed_risk = float(np.clip(rel_speed / 8.0, 0.0, 1.0))
            reward -= 25.0 * gap_risk * speed_risk

        # G1-hold deterrent: still needed to prevent "hold→timeout" exploit
        if self.last_governor_reason == 'governor_hold':
            reward -= 4.0 * abs(self._governor_raw_steer)

        # Shield penalty: scale set externally by train_ppo curriculum (0 during Phase 1
        # free exploration, ramped afterward). Ported from rl/env_wrapper.py:601-605.
        if intervened:
            reward -= (20.0 + 60.0 * (raw_steer ** 2)) * intervention_strength * self.shield_penalty_scale
            if self.last_shield_condition == "adaptive_gap":
                reward -= 40.0 * (raw_steer ** 2) * self.shield_penalty_scale

        # Passive steps tracker (used only for timeout penalty scaling)
        _is_passive = (_dp < 0.003 and progress < 0.15)
        if _is_passive:
            self._passive_steps += 1

        # Phase-1 profile: extra shaping on easy road only (set by train)
        if getattr(self, "reward_profile", "core") == "phase1":
            if 0.01 < _dp and progress < 1.0:
                reward += 30.0 * min(_dp, 0.05)
            if _is_passive:
                reward -= 2.0
            if 0.85 <= progress < 1.0:
                reward += 50.0

        # Safe-steer incentive: direct gradient on steer_intent when the road is clear.
        # Solves entropy collapse: the brain's steer mean converges to ~0 when crash
        # risk exists but steer=0 never triggers a crash.  This term creates a per-step
        # gradient that pulls the mean upward whenever it is safe to merge.
        # Active in both "core" and "phase1" profiles; scales with how safe the road is.
        _raw_steer = getattr(self, "_governor_raw_steer", 0.0)
        if gap > 6.0 and _raw_steer > 0.0 and progress < 1.0:
            _safe_scale = float(np.clip((gap - 6.0) / 20.0, 0.0, 1.0))   # 0 at 6m, 1 at 26m+
            reward += 8.0 * _raw_steer * _safe_scale

        # Cache presence factor for crash/terminal checks
        _pf = self.bus.presence_factor

        # ── SAT ground-truth overlap (exp7sat only; zero-cost when disabled) ──
        _sat_area = 0.0
        _sat_enabled = getattr(self, "sat_penalty_enabled", False)
        _spongy = getattr(self, "spongy_danger_zone_enabled", False)
        _, _, _, _, _, _nearest_for_sat = self._scan_nearest_car()
        if _sat_enabled and _nearest_for_sat is not None:
            _bus_corners = _rect_corners(
                float(self.bus.position),
                float(self.bus.lateral_offset),
                float(BUS_LENGTH) / 2.0,
                float(BUS_WIDTH) / 2.0,
                float(self.bus.heading_angle),
            )
            _car_lat = float(getattr(_nearest_for_sat, "total_lateral_offset", 0.0))
            _car_corners = _rect_corners(
                float(_nearest_for_sat.position),
                _car_lat,
                float(_nearest_for_sat.params.length) / 2.0,
                float(_nearest_for_sat.params.width) / 2.0,
                float(getattr(_nearest_for_sat, "heading_angle", 0.0)),
            )
            _sat_area = compute_sat_overlap_area(_bus_corners, _car_corners)

        # lon_dist for reward + features = bus_rear − car_front (same as `gap` above)
        _lon_dist = float(gap)

        # Term 4: terminal success (+5000)
        if progress >= 1.0:
            reward += 5000.0
            self._gap_at_success = gap
            done = True
            self.last_success = True

        # Term 5: SAT safety — v10 spongy danger zone vs v9 instant death
        elif _sat_enabled and _spongy:
            # Catastrophic crash: large polygon overlap only
            if _sat_area > 3.0:
                reward -= 2500.0 + 1000.0 * min(progress / 0.75, 1.0)
                done = True
                self.last_crash = True
            # Paint scrape: minor overlap — episode continues, steep continuous pain
            elif _sat_area > 0.0:
                reward -= 50.0 * _sat_area
            # Proximity repulsion: tight positive gap (car behind bus) during active merge
            if not done and 0.0 <= _lon_dist < 2.0 and progress > 0.1:
                reward -= 5.0

        elif _sat_enabled and _sat_area > 1.0:
            # v9 binary SAT terminal (exp7sat / exp7satv9 — unchanged)
            reward -= 2500.0 + 1000.0 * min(progress / 0.75, 1.0)
            done = True
            self.last_crash = True

        elif _sat_enabled and 0.0 < _sat_area <= 1.0:
            # Sideswipe-scale overlap below the v9 binary-terminal threshold — was a silent
            # dead zone (no gradient at all). Graded, non-terminal; mirrors the spongy
            # branch's per-m^2 magnitude above without touching that branch's own code path.
            reward -= 50.0 * _sat_area

        elif (not _sat_enabled
              and gap <= 0.0 and gap > -15.0):
            # Legacy 1-D rule, only for runs without SAT. With SAT enabled the polygon
            # overlap above is the sole crash judge: this rule reads presence_factor, whose
            # WAITING_TO_MERGE floor makes a bus parked in its bay count as "in lane", so a
            # car merely passing alongside the bay was scored as a collision.
            _bus_lat_edge = self.bus.lateral_offset + BUS_WIDTH / 2.0
            _bus_in_lane  = (_pf > 0.05
                             or _bus_lat_edge > 0.0
                             or self.bus.lateral_offset > -1.85)
            if _bus_in_lane:
                reward -= 2500.0 + 1000.0 * min(progress / 0.75, 1.0)
                done = True
                self.last_crash = True

        if self.current_step >= self.max_steps and not done:
            # Scale penalty with passivity: tried hard->-2000; idle all ep->-8000
            _waste_frac = min(1.0, self._passive_steps / self.max_steps)
            reward -= 3500.0 + 6000.0 * (_waste_frac ** 2)
            done = True
            self.last_timeout = True

        # ── Record this step in the rolling telemetry history ─────────
        _ttc_now = (gap / rel_speed) if (gap > 0.0 and rel_speed > 0.1) else float('inf')
        self._step_history.append({
            'step'         : self.current_step,
            'progress'     : round(progress, 4),
            'gap_m'        : round(gap, 3),
            'rel_spd'      : round(rel_speed, 3),
            'ttc_s'        : round(_ttc_now, 2) if _ttc_now < 999 else 999.0,
            'bus_vel'      : round(self.bus.velocity, 3),
            'bus_lat_vel'  : round(self.bus.lateral_velocity, 3),
            'bus_lat_off'  : round(self.bus.lateral_offset, 3),
            'bus_heading'  : round(self.bus.heading_angle, 4),
            'car_vel'      : round(car_speed, 3),
            'car_accel'    : round(car_accel, 3),
            'steer_agent'  : round(_raw_steer_agent, 3),
            'gas_agent'    : round(_raw_gas_agent, 3),
            'steer_exec'   : round(steer_intent, 3),
            'gas_exec'     : round(gas_intent, 3),
            'gov_veto'     : self.last_governor_veto,
            'gov_reason'   : self.last_governor_reason,
            'shield'       : self.last_shield_condition,
        })

        if self.last_crash:
            self._crash_count += 1
            self._log_crash_diagnostics()

        info = {}
        if done:
            _n = max(1, self._action_volatility_count)
            info['action_volatility']  = self._action_volatility_sum / _n
            info['max_trailing_decel'] = self._max_trailing_decel
            info['hesitation_steps']  = self._hesitation_steps
            info['passive_steps']     = self._passive_steps
            info['merge_steps']       = self._merge_steps
            info['reversal_count']    = self._reversal_count
            info['peak_steer_jerk']   = self._peak_steer_jerk
            info['gap_at_success']    = self._gap_at_success
            _vs = max(1, self._total_steps)
            info['governor_veto_rate'] = self.episode_governor_vetos / _vs
        return state, reward, done, info

    def _get_state(self):
        gap, nearest_speed, nearest_accel, nearest_width, relative_speed, nearest_car = self._scan_nearest_car()

        bus_heading_rad = self.bus.heading_angle  # direct from bicycle model
        progress        = self._merge_progress()

        # Angle-corrected lateral clearance at the bus outer edge
        bus_lat_edge   = self.bus.lateral_offset + BUS_WIDTH / 2.0
        car_lat_offset = getattr(nearest_car, 'total_lateral_offset', 0.0) if nearest_car else 0.0
        lat_clearance  = LANE_WIDTH - bus_lat_edge - (nearest_width - car_lat_offset)  # Bug 7 fix: no floor — AI sees full continuous lateral signal

        # Relative acceleration
        bus_vel_now = self.bus.velocity
        bus_accel   = (bus_vel_now - self._prev_bus_vel) / self.dt
        rel_accel   = bus_accel - nearest_accel

        car_length    = nearest_car.params.length if nearest_car else 4.5
        car_heading_rad = getattr(nearest_car, 'heading_angle', 0.0) if nearest_car else 0.0
        # Empty-road sentinels: explicit values so the encoded state reads "safe, no threat"
        # regardless of clip-range changes.  gap=60→lon_n=1.0; rel_speed=0→rs_n=0.0.
        if nearest_car is None:
            gap            = 60.0
            relative_speed = 0.0

        _car_id = nearest_car.id if nearest_car is not None else None
        return self._encode_state(
            *self._apply_sensor_noise(
                progress,
                bus_heading_rad,
                gap,
                lat_clearance,
                nearest_speed,
                nearest_accel,
                nearest_width,
                car_length,
                relative_speed,
                rel_accel,
                car_heading_rad,
                car_id=_car_id,
            )
        )

    def _maybe_distract(self, params):
        """15% chance a spawned car is 'distracted' — slower reaction time."""
        if not self.eval_mode and random.random() < 0.15:
            factor = random.uniform(1.5, 3.0)
            params.base_reaction_time   *= factor
            params.shock_reaction_time   = max(params.shock_reaction_time,
                                               params.base_reaction_time + 0.5)
