import numpy as np

from busmerge.safe_speed import follower_acceleration
from busmerge.rl.merge_constants import (
    BAY_FLAT_END_X, BUS_ALIGN_HEADING_DEG, BUS_BAY_LOOKAHEAD_M, BUS_CRAWL_SPEED_MS, BUS_LANE_LOOKAHEAD_M, MAX_BRAKE_MS2,
)
from dataclasses import dataclass
import random
from typing import Dict

@dataclass
class VehicleParams:
    # URBAN SETTINGS
    max_speed: float = 13.9      
    max_accel: float = 2.0       
    comfortable_brake: float = 2.0 
    min_gap: float = 2.0         
    time_headway: float = 1.5    
    length: float = 4.5          # REAL CAR LENGTH
    width: float = 1.9           # NEW: REAL CAR WIDTH
    delta: float = 4.0           

    # Human Factors
    base_reaction_time: float = 0.5 
    shock_reaction_time: float = 1.0 
    vehicle_class: str = "Mid"
    politeness_factor: float = 0.7   # 0=aggressive/no yield, 1=fully polite/max nudge
    wheelbase: float = 2.7           # metres between axles (bicycle model turning geometry)
    max_steer_angle_deg: float = 35.0    # peak rack angle (degrees) — physical hardware limit
    steer_rate_deg_per_s: float = 75.0   # how fast the steering wheel can rotate (deg/s)
    lane_keeping_noise: float = 0.08     # O-U σ for imperfect lane tracking (m)

CAR_PARAMS = VehicleParams()


def pure_pursuit_steer(lat_error: float, heading: float, wheelbase: float, look_ahead: float) -> float:
    """Steering angle that drives a vehicle onto a straight line ``lat_error`` metres to its side.

    Pure pursuit: aim at the point of the target line ``look_ahead`` metres ahead, expressed in the
    vehicle's own frame. The ``- look_ahead·sin(heading)`` term makes the vehicle counter-steer as its
    heading approaches the line, so it arrives parallel instead of overshooting it.
    """
    y_rel = lat_error * np.cos(heading) - look_ahead * np.sin(heading)
    return float(np.arctan2(2.0 * wheelbase * y_rel, look_ahead * look_ahead))

# Surprise filter: max |ΔY|/s on merge yield (0.5 → ~2 s from 0→1).
# Prevents IN_BAY → WAITING_TO_MERGE yield cliffs from becoming emergency brakes.
MAX_YIELD_SLEW_RATE = 0.5

# Real-world anchor points used for class ranges (Wikipedia model pages):
# - Compact reference: Toyota Corolla (E210) ~4.63 m x 1.78 m
# - Mid-size reference: Toyota Camry (XV70) ~4.88-4.91 m x 1.84 m
# - Large reference: Chevrolet Impala (Gen 10) ~5.11 m x 1.85 m
# - SUV reference: Honda CR-V (5th gen) / Toyota RAV4 (XA50) ~4.58-4.63 m x 1.855 m
CAR_CLASS_PROFILES: Dict[str, Dict[str, object]] = {
    "Compact": {
        "weight": 0.30,
        "length_range": (4.20, 4.55),
        "width_range": (1.74, 1.80),
        "max_speed": 14.5,
        "max_accel": 2.3,
        "comfortable_brake": 2.2,
        "time_headway": 1.35,
        "base_reaction_time": 0.45,
        "wheelbase": 2.62,          # Toyota Corolla E210: 2.64 m
        "max_steer_angle_deg": 38.0,    # short wheelbase → nimble steering
        "steer_rate_deg_per_s": 90.0,   # light car → fast wheel rotation
        "lane_keeping_noise": 0.06,     # typical suburban commuter
    },
    "Mid": {
        "weight": 0.30,
        "length_range": (4.60, 4.90),
        "width_range": (1.80, 1.88),
        "max_speed": 13.9,
        "max_accel": 2.0,
        "comfortable_brake": 2.0,
        "time_headway": 1.50,
        "base_reaction_time": 0.50,
        "wheelbase": 2.75,          # Toyota Camry XV70: 2.825 m
        "max_steer_angle_deg": 35.0,
        "steer_rate_deg_per_s": 75.0,
        "lane_keeping_noise": 0.08,
    },
    "Large": {
        "weight": 0.15,
        "length_range": (4.90, 5.20),
        "width_range": (1.86, 1.95),
        "max_speed": 13.0,
        "max_accel": 1.7,
        "comfortable_brake": 1.8,
        "time_headway": 1.70,
        "base_reaction_time": 0.58,
        "wheelbase": 2.92,          # Chevrolet Impala Gen10: 2.84 m
        "max_steer_angle_deg": 30.0,    # large car, limited turn-in
        "steer_rate_deg_per_s": 60.0,   # heavier steering system
        "lane_keeping_noise": 0.10,     # lazy lane-keeping in large sedans
    },
    "SUV": {
        "weight": 0.15,
        "length_range": (4.55, 4.75),
        "width_range": (1.84, 1.93),
        "max_speed": 13.5,
        "max_accel": 1.9,
        "comfortable_brake": 1.9,
        "time_headway": 1.60,
        "base_reaction_time": 0.55,
        "wheelbase": 2.68,          # Honda CR-V 5th gen: 2.662 m
        "max_steer_angle_deg": 33.0,
        "steer_rate_deg_per_s": 70.0,
        "lane_keeping_noise": 0.09,
    },
    # Phase 2 (C1): Aggressive driver — tailgater, fast reactor, tight headway.
    # Weight 0.10 → 1 in 10 spawned cars will behave aggressively.
    # This is the hardest adversarial case: if the agent handles this, normal cars are easy.
    "Aggressive": {
        "weight": 0.10,
        "length_range": (4.20, 4.55),   # Compact-sized
        "width_range":  (1.74, 1.80),
        "max_speed": 15.5,              # 11% above normal
        "max_accel": 2.8,
        "comfortable_brake": 2.5,
        "time_headway": 1.0,            # Tailgating (normal = 1.5s)
        "base_reaction_time": 0.35,     # Alert and fast
        "politeness_factor": 0.0,       # refuses to yield; only brakes at last moment
        "wheelbase": 2.62,              # Compact-based
        "max_steer_angle_deg": 40.0,    # sharp, reckless inputs
        "steer_rate_deg_per_s": 120.0,  # very fast wheel feedback
        "lane_keeping_noise": 0.15,     # erratic lane position
    },
}


def sample_vehicle_params(vehicle_class: str = None):
    """Sample one car profile so physics is not tied to a single car size."""
    if vehicle_class is None:
        classes = list(CAR_CLASS_PROFILES.keys())
        weights = [CAR_CLASS_PROFILES[c]["weight"] for c in classes]
        vehicle_class = random.choices(classes, weights=weights, k=1)[0]

    profile = CAR_CLASS_PROFILES[vehicle_class]
    length = random.uniform(*profile["length_range"])
    width = random.uniform(*profile["width_range"])

    # ── DRIVER PERSONALITY: all behaviour params sampled per individual ──────
    # Class profiles define the *centre* of each distribution.
    # The driver drawn from the same class can still be calm or excited that day.
    # This prevents the bus from learning fixed archetypes; it must drive safely
    # for ANY combination of steering speed, aggression and headway.

    # Politeness: Beta(2,2) → bell-shaped 0–1, centred ~0.5.
    # Aggressive archetype is drawn from Beta(1,6) → heavily skewed toward 0
    # (usually 0.0–0.25) but not literally clamped to 0.
    if vehicle_class == "Aggressive":
        politeness = float(np.random.beta(1.0, 6.0))       # almost always near 0, rarely ~0.3
    else:
        politeness = float(np.random.beta(2.0, 2.0))

    # Steering rate: LogNormal so it's always positive.
    # μ_log, σ_log chosen so the median equals the profile value and ±1σ spans
    # roughly ±25% of that value.
    _sr_mean = profile.get("steer_rate_deg_per_s", 75.0)
    _sr_sigma_log = 0.20                                    # CV ≈ 20 %
    steer_rate = float(np.clip(
        np.random.lognormal(np.log(_sr_mean), _sr_sigma_log),
        _sr_mean * 0.40, _sr_mean * 2.0))

    # Max steering angle: Normal, σ = 3°.
    _ma_mean = profile.get("max_steer_angle_deg", 35.0)
    max_steer = float(np.clip(
        np.random.normal(_ma_mean, 3.0),
        max(15.0, _ma_mean - 8.0), _ma_mean + 8.0))

    # Lane-keeping noise: LogNormal, σ_log = 0.20 (same relative spread).
    _lk_mean = profile.get("lane_keeping_noise", 0.08)
    lane_noise = float(np.clip(
        np.random.lognormal(np.log(_lk_mean), 0.25),
        _lk_mean * 0.30, _lk_mean * 3.0))

    params = VehicleParams(
        max_speed=profile["max_speed"],
        max_accel=profile["max_accel"],
        comfortable_brake=profile["comfortable_brake"],
        min_gap=2.0,
        time_headway=profile["time_headway"],
        length=length,
        width=width,
        delta=4.0,
        base_reaction_time=profile["base_reaction_time"],
        shock_reaction_time=max(0.9, profile["base_reaction_time"] + 0.5),
        vehicle_class=vehicle_class,
        politeness_factor=politeness,
        wheelbase=profile["wheelbase"],
        max_steer_angle_deg=max_steer,
        steer_rate_deg_per_s=steer_rate,
        lane_keeping_noise=lane_noise,
    )
    return vehicle_class, params

class Vehicle:
    def __init__(self, v_id: int, position: float, velocity: float, params: VehicleParams = None):
        self.id = v_id
        self.position = position
        self.velocity = velocity
        self.acceleration = 0.0
        self.params = params if params else CAR_PARAMS
        self.vehicle_class = self.params.vehicle_class
        
        self.reaction_timer = 0.0
        self.last_presence_seen = 0.0
        self.is_squeezing = False
        # Lateral motion — Steering-First bicycle model (Driver Mind + Vehicle Body)
        self.lateral_offset = 0.0      # metres intentional nudge from lane centre
        self.lateral_velocity = 0.0    # m/s lateral speed (result of heading, not cause)
        self.steer_angle = 0.0         # current steering wheel angle (rad)
        self.lat_target = 0.0          # driver's desired lateral offset (m)
        self.heading_angle = 0.0       # vehicle body yaw (rad) — drives lateral_velocity
        self.lane_drift = 0.0          # O-U lane-keeping uncertainty (m)
        # Rate-limited yield actually used in IDM last step (Surprise Filter).
        self.last_applied_yield = 0.0

    def update_physics(self, dt: float, leader=None, bus=None):
        # --- 1. SQUEEZE EXIT LOGIC ---
        if self.is_squeezing:
            if bus:
                safe_pass_point = bus.position + bus.params.length + 5.0
                if self.position > safe_pass_point:
                    self.is_squeezing = False # Safe exit
            elif leader is None:
                self.is_squeezing = False

        # --- 2. REACTION TIMER ---
        self.reaction_timer -= dt
        if leader:
            current_presence = leader.get('presence', 1.0)
            # Layby merge: bus presence ramps gradually — do NOT freeze IDM for 1 s
            # ("shock" was causing Car decels: NONE while cars coast at full speed).
            _bus_merging = (
                bus is not None
                and getattr(getattr(bus, "state", None), "name", "") == "WAITING_TO_MERGE"
            )
            if (current_presence < 1.0 and current_presence > self.last_presence_seen
                    and not _bus_merging):
                diff = current_presence - self.last_presence_seen
                if diff > 0.1 and self.reaction_timer <= 0 and not self.is_squeezing:
                    self.reaction_timer += self.params.shock_reaction_time
            self.last_presence_seen = current_presence

        # --- 3. PHYSICS STEP ---
        # During WAITING_TO_MERGE the governor/brain owns acceleration; do not
        # let the IDM reaction-timer overwrite it.
        _is_merging_bus = (isinstance(self, Bus) and
                           getattr(self, "state", None) == BusState.WAITING_TO_MERGE)
        _merge_leader = (
            leader is not None and float(leader.get("presence", 1.0)) < 0.99
        )
        # Run IDM if raw yield woke up OR applied yield is still decaying toward 0.
        _bus_yield = (
            self._merge_yield_factor(bus) > 0.0
            or float(getattr(self, "last_applied_yield", 0.0)) > 1e-6
        )
        # Merge yield must run every frame — never skip IDM while yield factor is active.
        if ((self.reaction_timer <= 0 or _merge_leader or _bus_yield)
                and not _is_merging_bus):
            self.acceleration = self._calculate_idm_accel(leader, bus, dt=dt)
            if self.reaction_timer <= 0:
                self.reaction_timer = self.params.base_reaction_time + random.uniform(-0.1, 0.1)

        # Bus IDM overrides — state-specific (do not cap queue-follow braking at −1.5 m/s²).
        if isinstance(self, Bus) and leader is not None:
            if self.state == BusState.MOVING and leader.get("id", -1) != -1:
                # Main-road queue: same full IDM as cars (no comfortable-stop cap).
                self.acceleration = max(self._calculate_idm_accel(leader, bus, dt=dt), -9.0)
            elif self.state == BusState.DECELERATING:
                # Smooth approach to bay stop only — cap at comfortable brake.
                noisy_leader = dict(leader)
                raw_gap = max(0.1, leader['position'] - leader['length'] - self.position)
                gap_noise = np.random.normal(0.0, max(0.3, raw_gap * 0.02))
                noisy_leader['position'] = leader['position'] + gap_noise
                self.acceleration = max(self._calculate_idm_accel(noisy_leader, bus, dt=dt), -1.5)
                _idm_demand = float(np.clip(abs(self.acceleration) / 1.5, 0.0, 1.0))
                _sigma_micro = 0.02 + 0.06 * _idm_demand
                self.acceleration += float(np.random.normal(0.0, _sigma_micro))
                self.acceleration = max(self.acceleration, -1.5)
                # The comfortable plan above may not be enough to stop at the stop point;
                # the bay-stop law adds exactly the braking that is physically needed.
                self.acceleration = self.bay_stop_acceleration(self.acceleration)

        # Following a vehicle ahead (cars, and the bus once back in the lane): the driver's command
        # is limited by the safe-speed law (busmerge/safe_speed.py). Speed and position then follow
        # from the acceleration; nothing is assigned. The virtual stop leader of a bus pulling into
        # the bay (id -1) is handled by Bus.bay_stop_acceleration instead.
        _follows_leader = (
            leader is not None
            and leader.get("id", -1) != -1
            and (not isinstance(self, Bus) or self.state == BusState.MOVING)
        )
        if _follows_leader:
            self.acceleration = follower_acceleration(self, leader, self.acceleration, dt)

        self.velocity += self.acceleration * dt
        if self.velocity < 0:
            self.velocity = 0.0          # comes to rest; vehicles do not reverse
            self.acceleration = 0.0
        self.position += self.velocity * dt

        if not getattr(self, 'skip_lateral_steering', False):
            # ── STEERING-FIRST LATERAL MODEL ─────────────────────────────────────────
            # Decoupled: Driver Mind (intent) → Steering Wheel (hardware) → Bicycle Physics → Position
            is_bus = isinstance(self, Bus)
    
            # 1. DRIVER INTENT: cars compute from squeeze logic; bus lat_target is set
            #    externally by _handle_bus_logic (the "mind") before update_physics runs.
            if not is_bus:
                MAX_NUDGE = 0.5   # metres max intentional lateral nudge
                pol = getattr(self.params, 'politeness_factor', 0.7)
                self.lat_target = (MAX_NUDGE * pol) if (self.is_squeezing and bus is not None) else 0.0
    
            # Geometry constants used by both the steer controller and the bicycle model.
            wheelbase  = getattr(self.params, 'wheelbase', 2.7)
            max_steer  = np.radians(getattr(self.params, 'max_steer_angle_deg', 35.0))
            steer_rate = np.radians(getattr(self.params, 'steer_rate_deg_per_s', 75.0))
    
            # BUS ACTIVE LANE-CORRECTION ─────────────────────────────────────────────
            # A small OU process drives _lat_perturb, which is added to lat_target before
            # the pure-pursuit step.  The controller then steers to correct it, producing
            # natural oscillations around the intended path instead of invisible drift.
            #   • Only active during MOVING (straight driving) — suppressed during bay
            #     entry and merge so precise path-following is unaffected.
            #   • σ=0.03 m → steady-state std ≈ 3 cm, bounded ±10 cm.
            if is_bus:
                _OU_LAT_REVERT = 0.5   # s⁻¹ — faster reversion = quicker correction
                _OU_LAT_SIG    = 0.03  # m   — ~3 cm std at steady state
                if self.state == BusState.MOVING:
                    self._lat_perturb = ((1.0 - _OU_LAT_REVERT * dt) * self._lat_perturb
                                         + _OU_LAT_SIG * np.sqrt(dt) * np.random.randn())
                    self._lat_perturb = float(np.clip(self._lat_perturb, -0.10, 0.10))
                else:
                    # Decay to zero when not in straight-line driving so the bay
                    # entry and merge are not perturbed by residual lateral noise.
                    self._lat_perturb *= max(0.0, 1.0 - 5.0 * dt)
                effective_lat_target = self.lat_target + self._lat_perturb
            else:
                effective_lat_target = self.lat_target
    
            # 2. STEERING CONTROLLER
            if is_bus:
                # PURE PURSUIT: compute the steering command as the arc required to meet
                # the look-ahead point (bus.position + L_PP, lat_target) in the bus's own
                # body frame.  Because it subtracts the bus's current heading_angle, it
                # automatically generates counter-steer whenever the accumulated heading has
                # overshot the desired path angle — this is what keeps the bus parallel to
                # the kerb when parking without a separate straighten-zone.
                #
                # y_rel = (effective_lat_target - lateral_offset) * cos(ψ) − L_PP * sin(ψ)
                #   where ψ = heading_angle (negative = nose pointing into bay)
                # δ_cmd  = atan2(2 * L * y_rel,  L_PP²)
                #
                # When ψ < 0 and lateral error ≈ 0 (bus at bay depth):
                #   y_rel ≈ −L_PP * sin(ψ) > 0  →  δ_cmd > 0 (counter-steer back to road)
                look_ahead = (BUS_BAY_LOOKAHEAD_M if self.state == BusState.DECELERATING
                              else BUS_LANE_LOOKAHEAD_M)
                delta_target = np.clip(pure_pursuit_steer(effective_lat_target - self.lateral_offset,
                                                          self.heading_angle, wheelbase, look_ahead),
                                       -max_steer, max_steer)
            else:
                # Simple proportional look-ahead for cars.
                lookahead    = max(self.velocity * 1.0, 5.0)
                lat_error    = self.lat_target - self.lateral_offset
                delta_target = np.clip(np.arctan2(lat_error, lookahead), -max_steer, max_steer)
    
            # 3. MECHANICAL RESPONSE: steering wheel can only rotate at steer_rate (deg/s)
            steer_change = np.clip(delta_target - self.steer_angle,
                                   -steer_rate * dt, steer_rate * dt)
            self.steer_angle += steer_change
    
            # 4. BICYCLE MODEL: heading rate = v × tan(δ) / L
            #    Longer wheelbase → lower yaw rate for the same steering input
            self.heading_angle += (self.velocity * np.tan(self.steer_angle)
                                   / max(wheelbase, 0.1)) * dt
    
            # 5. POSITION UPDATE: lateral_velocity is now a RESULT of heading, not a cause
            self.lateral_velocity = self.velocity * np.sin(self.heading_angle)
            self.lateral_offset  += self.lateral_velocity * dt
            # No clamp: a vehicle that steers off the road is reported by busmerge.invariants.
    
            # ── LANE-KEEPING UNCERTAINTY (Ornstein-Uhlenbeck random drift) ─────────────
            # Models the fact that no driver holds exactly the lane centre.
            # Each class has its own noise level (aggressive wanders more, compact less).
            OU_REVERT = 0.4   # mean-reversion rate (s⁻¹): higher → snaps back faster
            noise_sig = getattr(self.params, 'lane_keeping_noise', 0.08)
            self.lane_drift = ((1.0 - OU_REVERT * dt) * self.lane_drift
                               + noise_sig * np.sqrt(dt) * np.random.randn())

    @property
    def total_lateral_offset(self):
        """Effective lateral offset: intentional nudge + passive lane-keeping drift."""
        return self.lateral_offset + self.lane_drift

    def _bus_encroachment(self, bus) -> float:
        from busmerge.rl.traffic_leaders import bus_encroachment_level
        return bus_encroachment_level(bus)

    def _merge_yield_factor(self, bus) -> float:
        if bus is None:
            return 0.0
        from busmerge.rl.merge_yield import compute_yield_factor, car_is_ahead_of_merging_bus, bus_gap_to_car_front
        bus_state_name = getattr(getattr(bus, "state", None), "name", "")
        if bus_state_name == "WAITING_TO_MERGE":
            ahead = car_is_ahead_of_merging_bus(bus, self)
            gap = bus_gap_to_car_front(bus, self)
            progress = float(getattr(bus, "_merge_progress", 0.0))
            # Geometric presence only — the synthetic 0.15 WAITING floor is for
            # PPO/governor, not for car yield (it caused phantom full-stop queues).
            presence = float(getattr(bus, "geometric_presence_factor", bus.presence_factor))
            if ahead:
                return 0.0
            # Alongside (gap ≤ 0): bus has committed — car must wait/yield, not
            # re-accelerate on "Clear Road" (export 2026-07-12 t≈39–41 regression).
            if gap <= 0.0:
                return compute_yield_factor(
                    max(progress, 0.30), gap, max(presence, 0.25), car_ahead=False,
                )
            # Still in bay, car still BEHIND: mild blinker-like pass-through yield.
            if (progress <= 0.05 and presence <= 0.08
                    and float(getattr(bus, "blinker_presence", 0.0)) <= 0.0):
                return compute_yield_factor(
                    0.0, gap, 0.10, car_ahead=False, is_blinker=True,
                )
            return compute_yield_factor(progress, gap, presence, car_ahead=False)
        if bus_state_name == "IN_BAY":
            presence = float(getattr(bus, "blinker_presence", 0.0))
            if presence <= 0.0:
                return 0.0
            ahead = car_is_ahead_of_merging_bus(bus, self)
            gap = bus_gap_to_car_front(bus, self)
            # is_blinker=True: low continuous Y, no encroachment floor.
            return compute_yield_factor(
                0.0, gap, presence, car_ahead=ahead, is_blinker=True,
            )
        return 0.0

    def _apply_squeeze_hysteresis(self, squeeze_urgency: float) -> None:
        """Schmitt trigger on lane-deficit — stops Reacting/Squeezing telemetry flutter."""
        from busmerge.rl.merge_constants import SQUEEZE_ENTER_URGENCY, SQUEEZE_EXIT_URGENCY
        u = float(squeeze_urgency)
        if self.is_squeezing:
            self.is_squeezing = u > SQUEEZE_EXIT_URGENCY
        else:
            self.is_squeezing = u > SQUEEZE_ENTER_URGENCY

    def _bus_leader_state(self, bus):
        from busmerge.rl.traffic_leaders import vehicle_leader_state
        return vehicle_leader_state(bus)

    def _idm_accel_core(self, leader, bus=None, apply_squeeze: bool = True) -> float:
        """Standard IDM (+ optional lateral squeeze) without merge-yield blend."""
        p = self.params
        target_speed = p.max_speed
        squeeze_brake_penalty = 0.0

        if leader is not None and apply_squeeze:
            presence = leader.get('presence', 1.0)
            gap = leader['position'] - leader['length'] - self.position
            if gap < 0.1: gap = 0.1
            
            # Calculate Braking Need
            req_brake = (self.velocity ** 2) / (2 * gap)

            # --- PRESSURE REACTION LOGIC ---
            
            if presence == 0.0:
                self.is_squeezing = False
            elif presence == 1.0:
                self.is_squeezing = False
            
            else:
                # DYNAMIC SQUEEZE CALCULATION
                lane_width = 3.5
                safety_gap = 0.5
                bus_width  = 2.5   # BUS_WIDTH
                bus_length = 11.0  # BUS_LENGTH
                # Pillar C: Geometric Awareness — sense from the bus REAR corner, not the centre.
                # When the bus is angled mid-merge, the rear extends LESS into the lane than
                # the centre does.  Using the centre overstates the threat by up to ~0.9 m at
                # peak yaw (13.1°), causing premature panic braking.
                if bus is not None:
                    bus_angle_rad = np.radians(bus.get_turn_angle_degrees())
                    bus_rear_lat = max(0.0, presence * bus_width
                                      - (bus_length / 2.0) * np.sin(bus_angle_rad))
                else:
                    bus_rear_lat = presence * bus_width  # fallback: flat-centre estimate

                # How much lane is the bus eating up (at its rear corner)?
                bus_occupancy = bus_rear_lat
                # How much space is left for the car?
                space_left = lane_width - bus_occupancy
                # How much space does this specific car need?
                space_needed = self.params.width + safety_gap

                # --- NEW: THE SOFT WALL ---
                squeeze_urgency = space_needed - space_left

                # Start reacting slightly BEFORE the exact boundary to avoid a hard wall.
                # soft_zone defines the transition region around squeeze_urgency == 0.
                soft_zone = 0.60  # meters
                urgency_norm = np.clip((squeeze_urgency + soft_zone) / (2.0 * soft_zone), 0.0, 1.0)
                smooth = urgency_norm * urgency_norm * (3.0 - 2.0 * urgency_norm)  # smoothstep

                # Gradual penalty: mild braking as lane tightens, stronger when physically blocked.
                base_soft_brake = -3.5 * smooth
                overflow = max(0.0, squeeze_urgency) / soft_zone
                extra_hard_brake = -5.5 * overflow
                squeeze_brake_penalty = max(-9.0, base_soft_brake + extra_hard_brake)

                self._apply_squeeze_hysteresis(squeeze_urgency)
                if not self.is_squeezing:
                    presence = 1.0
        elif leader is not None:
            presence = leader.get('presence', 1.0)
            gap = leader['position'] - leader['length'] - self.position
            if gap < 0.1:
                gap = 0.1
        else:
            presence = 1.0

        # --- STANDARD IDM MATH ---
        if self.velocity < 0.1:
            speed_ratio = 0
        else:
            speed_ratio = (self.velocity / target_speed)
        
        free_road_term = 1.0 - (speed_ratio ** p.delta)

        if leader is None:
            interaction_term = 0.0
        else:
            delta_v = self.velocity - leader['velocity']
            merge_intrusion = float(bus.presence_factor) if bus is not None else 0.0
            if bus is not None and getattr(bus.state, "name", "") == "WAITING_TO_MERGE":
                merge_intrusion = max(merge_intrusion, float(bus.presence_factor) * 1.15)
            intrusion_scale = min(merge_intrusion / 0.22, 1.0)
            effective_s0 = p.min_gap + 3.5 * intrusion_scale
            desired_gap = (effective_s0 +
                           (self.velocity * p.time_headway) +
                           (self.velocity * delta_v) / (2 * np.sqrt(p.max_accel * p.comfortable_brake)))
            interaction_term = (desired_gap / gap) ** 2
            leader_presence = presence
            interaction_term *= leader_presence

        accel = p.max_accel * (free_road_term - interaction_term)
        if apply_squeeze:
            accel += squeeze_brake_penalty
        return max(accel, -9.0)

    def _rate_limit_yield(self, raw_y_eff: float, dt: float) -> float:
        """Surprise Filter: slew |ΔY| ≤ MAX_YIELD_SLEW_RATE per second."""
        prev = float(getattr(self, "last_applied_yield", 0.0))
        max_step = MAX_YIELD_SLEW_RATE * max(float(dt), 1e-6)
        applied = min(float(raw_y_eff), prev + max_step)
        applied = max(applied, prev - max_step)
        applied = float(np.clip(applied, 0.0, 1.0))
        self.last_applied_yield = applied
        return applied

    def _calculate_idm_accel(self, leader, bus=None, dt: float = 0.1) -> float:
        """
        IDM with continuous merge-yield blend when a bus is WAITING_TO_MERGE.
        accel = (1 - Y_eff) * a_free + Y_eff * a_idm_vs_bus

        a_idm always targets the bus when yield is active — never a car further
        up the queue that would let the follower drive through the bus.

        Y_eff is rate-limited (Surprise Filter) so IN_BAY→WAITING jumps cannot
        produce a single-frame emergency brake.
        """
        raw_y_eff = self._merge_yield_factor(bus)
        y_eff = self._rate_limit_yield(raw_y_eff, dt)
        bus_state_name = getattr(getattr(bus, "state", None), "name", "") if bus is not None else ""
        bus_merging = (
            bus is not None
            and (
                bus_state_name == "WAITING_TO_MERGE"
                or (bus_state_name == "IN_BAY" and getattr(bus, "blinker_presence", 0.0) > 0.0)
            )
        )
        bus_leader = (
            leader is not None and float(leader.get("presence", 1.0)) < 0.99
        )

        if y_eff <= 0.0:
            if bus_leader:
                return self._idm_accel_core(None, bus, apply_squeeze=False)
            return self._idm_accel_core(leader, bus, apply_squeeze=True)

        if bus_merging:
            _bl = dict(self._bus_leader_state(bus))
            # When bus is IN_BAY (parked in bay, presence_factor=0), the leader-state
            # presence is 0 which zeros out IDM interaction_term.  Override to 1.0 so
            # the blinker yield actually produces a braking response.
            if bus_state_name == "IN_BAY":
                _bl["presence"] = 1.0
            a_idm = self._idm_accel_core(_bl, bus, apply_squeeze=True)
        else:
            a_idm = self._idm_accel_core(leader, bus, apply_squeeze=True)

        a_free = self._idm_accel_core(None, bus, apply_squeeze=False)
        return max((1.0 - y_eff) * a_free + y_eff * a_idm, -9.0)

class Bus(Vehicle):
    def __init__(self, v_id, position, velocity, params):
        # Give the bus its own separate copy of the parameters so it doesn't overwrite the cars!
        import copy
        bus_params = copy.deepcopy(params) if params else copy.deepcopy(CAR_PARAMS)
        bus_params.length = 11.0 # REAL BUS LENGTH
        bus_params.width = 2.5   # NEW: REAL BUS WIDTH
        # Bus steering limits: large vehicle, professional driver.
        # steer_rate and lane_keeping_noise are sampled per-episode (LogNormal)
        # so that PPO must generalise across bus individuals, not memorise one vehicle.
        bus_params.wheelbase = 7.0              # long urban bus: rear-to-front axle
        bus_params.max_steer_angle_deg = 15.0   # professional driver, limited rack
        # steer_rate: median 25 °/s, CV≈10 % (tighter than cars — professional driver)
        bus_params.steer_rate_deg_per_s = float(np.clip(
            np.random.lognormal(np.log(25.0), 0.10), 18.0, 33.0))
        # lane_keeping_noise: median 0.05 m, CV≈15 %
        # lane_keeping_noise is now intentionally tiny: the OU perturbation is fed
        # into the pure-pursuit target (_lat_perturb below) so the driver actively
        # corrects it.  This residual represents actuator-level micro-wobble only.
        bus_params.lane_keeping_noise = float(np.clip(
            np.random.lognormal(np.log(0.01), 0.15), 0.005, 0.025))

        super().__init__(v_id, position, velocity, bus_params)
        self.state = BusState.MOVING
        self.stop_duration = 15.0
        self.target_stop_x = 300.0
        self.dwell_timer = 0.0
        self.wait_time = 0.0
        self._merge_progress = 0.0 
        self.merge_start_x = position
        self.max_merge_progress_step = 0.02
        # Active lane-correction OU state: perturbation added to lat_target so
        # pure pursuit actively steers back (visible small oscillations around centre).
        self._lat_perturb = 0.0
        # Virtual blinker — set by SimulationEngine during IN_BAY dwell.
        self.blinker_presence = 0.0   # synthetic presence fed to yield while IN_BAY
        self.signaling_merge = False  # True in last YIELD_BLINKER_DWELL_S of dwell
        # When True, update_physics skips the bicycle steering model.
        # Set by _handle_bus_logic during active manoeuvres so the
        # algorithmic trajectory (Pure Pursuit / PPO) is not corrupted
        # by the standard car physics lateral pass.
        self.skip_lateral_steering = False
        self._stop_served = False

    def bay_stop_acceleration(self, planned: float) -> float:
        """Longitudinal command while pulling in to stop (DECELERATING).

        Keeps the comfortable ``planned`` braking when it suffices, otherwise brakes exactly as
        hard as needed to stop at the stop point (v^2 / 2d). Past the stop point a bus that is
        still angled crawls on at a bounded acceleration until it is parallel, then stops. It never
        runs past the end of the bay, and no command exceeds the physical braking limit: speed and
        position always follow from the acceleration, they are never assigned.
        """
        v = max(float(self.velocity), 0.0)
        aligned = abs(self.heading_angle) <= np.radians(BUS_ALIGN_HEADING_DEG)
        to_stop = float(self.target_stop_x) - float(self.position)
        to_bay_end = BAY_FLAT_END_X - float(self.position)
        if to_stop > 0.0:
            # Reach the stop point at rest if already parallel, otherwise at crawl speed
            # (the alignment is then finished while crawling, without stopping first).
            v_end = 0.0 if aligned else BUS_CRAWL_SPEED_MS
            a = min(planned, -(v * v - v_end * v_end) / (2.0 * to_stop))
        elif not aligned:
            a = float(np.clip((BUS_CRAWL_SPEED_MS - v) / 0.5,
                              -self.params.comfortable_brake, self.params.max_accel))
        else:
            a = -float(self.params.comfortable_brake)
        if to_bay_end > 0.0:
            a = min(a, -v * v / (2.0 * to_bay_end))
        return max(a, -MAX_BRAKE_MS2)

    def set_stop_schedule(self, location, duration):
        self.target_stop_x = location
        self.stop_duration = duration

    def get_turn_angle_degrees(self):
        """Heading angle from the kinematic bicycle model (persistent state).
        When v=0 the heading stays exactly where it was — no snap to zero."""
        return float(np.degrees(self.heading_angle))

    def projected_length_along_x(self):
        """Projected longitudinal footprint when bus is rotated during tapers."""
        theta = np.radians(abs(self.get_turn_angle_degrees()))
        return (self.params.length * np.cos(theta)) + (self.params.width * np.sin(theta))

    @property
    def presence_factor(self):
        """Fraction of the traffic lane currently occupied by the bus (0=clear, 1=full block).

        Uses the maximum Y-coordinate of the bus's 4 rotated polygon corners so that
        tail-swing is correctly detected when the bus is angled.  This means a bus
        parked at -8° in the bay with its tail still poking into the lane will block
        cars exactly as much as its physical footprint demands — no approximation.

        Note: IN_BAY is no longer short-circuited to 0.0.  When the bus parks with a
        residual heading the tail corner may still reach the traffic lane; the polygon
        maths returns the correct small-but-nonzero value in that case and 0.0
        automatically once the bus is truly parallel to the kerb (heading ≈ 0°).

        WAITING_TO_MERGE floor: a minimum 0.15 presence is signalled as soon as the
        bus enters WAITING_TO_MERGE state (even before lateral movement begins).  This
        breaks the governor–yield deadlock: cars see the bus intending to merge and
        start yielding, giving the bus the gap it needs to actually move."""
        if self.state == BusState.STOPPED_IN_LANE:
            return 1.0
        _WAITING_PRESENCE_FLOOR = 0.15
        # Explicit 4-corner polygon computation.
        # Body-frame corners: (±half_l, ±half_w)
        # World y-coordinate: lateral_offset  +  corner_x*sin(θ)  +  corner_y*cos(θ)
        theta  = getattr(self, 'heading_angle', 0.0)
        c, s   = np.cos(theta), np.sin(theta)
        half_l = self.params.length / 2.0
        half_w = self.params.width  / 2.0
        lo     = self.lateral_offset
        # Y-coordinates of the four corners in the world (road) frame.
        corners_y = np.array([
            lo + half_l * s + half_w * c,   # front-left
            lo + half_l * s - half_w * c,   # front-right
            lo - half_l * s + half_w * c,   # rear-left
            lo - half_l * s - half_w * c,   # rear-right
        ])
        bus_max_y = float(np.max(corners_y))
        bus_min_y = float(np.min(corners_y))
        # Traffic lane spans [-1.75, +1.75]
        LANE_W   = 3.5
        overlap  = max(0.0, min(bus_max_y, LANE_W / 2) - max(bus_min_y, -LANE_W / 2))
        computed = float(np.clip(overlap / LANE_W, 0.0, 1.0))
        if self.state == BusState.WAITING_TO_MERGE:
            return max(computed, _WAITING_PRESENCE_FLOOR)
        return computed

    @property
    def geometric_presence_factor(self) -> float:
        """Lane occupancy from the bus polygon only — no WAITING_TO_MERGE floor.

        Used for car leader/yield decisions so a bay-parked bus (computed=0)
        does not phantom-block traffic via the synthetic 0.15 floor.
        The floored ``presence_factor`` remains for PPO/governor features.
        """
        if self.state == BusState.STOPPED_IN_LANE:
            return 1.0
        theta  = getattr(self, 'heading_angle', 0.0)
        c, s   = np.cos(theta), np.sin(theta)
        half_l = self.params.length / 2.0
        half_w = self.params.width  / 2.0
        lo     = self.lateral_offset
        corners_y = np.array([
            lo + half_l * s + half_w * c,
            lo + half_l * s - half_w * c,
            lo - half_l * s + half_w * c,
            lo - half_l * s - half_w * c,
        ])
        bus_max_y = float(np.max(corners_y))
        bus_min_y = float(np.min(corners_y))
        LANE_W = 3.5
        overlap = max(0.0, min(bus_max_y, LANE_W / 2) - max(bus_min_y, -LANE_W / 2))
        return float(np.clip(overlap / LANE_W, 0.0, 1.0))

from enum import Enum
class BusState(Enum):
    MOVING = 0
    DECELERATING = 1
    STOPPED_IN_LANE = 2
    IN_BAY = 3
    WAITING_TO_MERGE = 4