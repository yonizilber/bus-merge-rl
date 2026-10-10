import pandas as pd
import os
import random
import numpy as np
import torch
from typing import List
from busmerge.paths import DEFAULT_BRAIN
from busmerge.vehicle import Vehicle, Bus, BusState, CAR_PARAMS, sample_vehicle_params
from busmerge.config import SimConfig
from busmerge.rl.ppo_agent import PPOAgent
from busmerge.rl.feature_encoding import infer_state_dim_from_checkpoint
from busmerge.safe_speed import merging_bus_acceleration, safe_speed
from busmerge.rl.observation import build_observation
from busmerge.rl.merge_constants import (
    BAY_DEPTH as _MC_BAY_DEPTH,
    BUS_MAX_SPEED as _MC_BUS_MAX_SPEED,
    BUS_ALIGN_HEADING_DEG, BUS_STOPPED_SPEED_MS, SPAWN_MIN_SPEED_MS,
    MERGE_ACCEL_MAX as _MC_MERGE_ACCEL_MAX,
)

class SimulationEngine:
    def __init__(self, scenario="B", config: SimConfig = None, brain_path: str = None,
                 governor_disabled: bool = False, load_brain: bool = True):
        self.scenario = scenario
        self.cfg = config if config else SimConfig()
        self.governor_disabled = governor_disabled
        # Training hooks (unused by the app): an externally supplied (steer, gas) replaces the
        # brain's decision, `last_decision` reports what the governor/shield did with it, and
        # frame recording can be switched off for speed.
        self.external_action = None
        self.last_decision = None
        self.record_frames = True
        self.road_length = self.cfg.road_length
        self.dt = 0.1
        self.time = 0.0
        self.vehicles: List[Vehicle] = []
        self.frame_history = []
        self.follower_trace = []
        self._follower_trace_active = False
        self._follower_trace_car_id = None
        self._trace_prev_bus_x = None
        self._trace_prev_car_x = None
        self._trace_prev_car_v = None
        self._trace_prev_car_id = None
        self._frame_prev_x = {}
        self.global_id_counter = 0 
        self.cars_finished_count = 0
        self.last_spawn_time = 0.0
        self.traffic_rate = self.cfg.traffic_rate
        self.cars_spawned_count = 0
        self._pending_arrivals = 0
        
        # --- LOAD THE TRAINED PYTORCH BRAIN ---
        # brain_path overrides the default checkpoint; a missing file is an error.
        if load_brain:
            _ckpt = str(brain_path) if brain_path else str(DEFAULT_BRAIN)
            if not os.path.exists(_ckpt):
                raise FileNotFoundError(f"Brain checkpoint not found: {_ckpt}")
            self.active_brain_path = _ckpt
            self.feature_dim = infer_state_dim_from_checkpoint(_ckpt)
            self.brain = PPOAgent(state_dim=self.feature_dim, filename=_ckpt)
            self.brain.load(strict=True)
        else:
            self.active_brain_path = None
            self.feature_dim = 7
            self.brain = None
        self._prev_bus_vel = 0.0  # for rel_accel computation in brain state
        self._bus_heading_prev = 0.0
        self.heading_anomaly = False   # set True on first heading snap; also initialised in init_scenario
        self.noise_sigma = 0.0           # sensor noise std-dev; 0=off (set by caller)
        from busmerge.rl.feature_encoding import PerceptionNoiseState
        self._perception_noise = PerceptionNoiseState()

    def init_scenario(self):
        self.vehicles = []
        self.global_id_counter = 0 
        self.time = 0.0
        self._prev_bus_vel = 0.0
        self._bus_heading_prev = 0.0   # sniffer: heading at start of last step
        self.heading_anomaly = False   # set True for the rest of episode on first snap
        self.frame_history = []
        self.follower_trace = []
        self._follower_trace_active = False
        self._follower_trace_car_id = None
        self._trace_prev_bus_x = None
        self._trace_prev_car_x = None
        self._trace_prev_car_v = None
        self._trace_prev_car_id = None
        self._frame_prev_x = {}
        self._perception_noise.reset()
        self.cars_spawned_count = 0
        self._pending_arrivals = 0
        self.cars_finished_count = 0 
        
        # Spawn the bus at the start line (0.0).
        # Initial speed is uniformly sampled ±15 % around 10 m/s so that
        # different episodes produce different entry speeds and stop positions.
        spawn_speed = np.random.uniform(8.5, 11.5)
        bus = Bus(v_id=999, position=0.0, velocity=spawn_speed, params=CAR_PARAMS)

        # Stop position: nominal 300 m ± Gaussian σ=5 m (professional driver varies
        # aim point slightly).  Clipped to [BAY_FLAT_X0, BAY_FLAT_X1] = [285, 315] so the
        # bus always targets the flat section of the bay (never an out-of-bounds taper).
        stop_x = float(np.clip(np.random.normal(300.0, 5.0), 285.0, 315.0))
        bus.set_stop_schedule(stop_x, self.cfg.bus_dwell_time)
        
        self.vehicles.append(bus)

    def step(self):
        self.time += self.dt
        self._try_spawn_car()
        self.vehicles.sort(key=lambda v: v.position, reverse=True)
        the_bus = next((v for v in self.vehicles if isinstance(v, Bus)), None)

        from busmerge.rl.traffic_leaders import resolve_car_leader, resolve_bus_leader

        # Phase 1: bus state machine before car leader resolution (no 1-frame lag).
        for veh in self.vehicles:
            if isinstance(veh, Bus):
                self._handle_bus_logic(veh)
                if veh.state in [BusState.IN_BAY, BusState.STOPPED_IN_LANE]:
                    veh.velocity = 0.0
                    veh.acceleration = 0.0

        for i, veh in enumerate(self.vehicles):
            # Cars use resolve_car_leader (shared with training env) for full parity.
            # Bus leader is handled later per-state (DECELERATING uses virtual stop-leader;
            # WAITING_TO_MERGE sets lead_vehicle=None so IDM doesn't override governor).
            lead_vehicle = None
            if isinstance(veh, Bus):
                if veh.state == BusState.MOVING:
                    lead_vehicle = resolve_bus_leader(self.vehicles, i)
            elif i > 0:
                lead_vehicle, _ = resolve_car_leader(self.vehicles, i, the_bus)

            if isinstance(veh, Bus):
                if lead_vehicle:
                    gap = (
                        lead_vehicle["position"] - lead_vehicle["length"] - veh.position
                    )
                    veh.telemetry_leader = (
                        f"ID {lead_vehicle.get('id', '?')} (front-rear gap: {gap:.1f}m)"
                    )
                    veh._telemetry_front_gap = gap
                    lv_obj = next(
                        (u for u in self.vehicles if u.id == lead_vehicle.get("id")), None
                    )
                    if lv_obj is not None:
                        lv_y = getattr(lv_obj, "total_lateral_offset", 0.0)
                        bus_y = getattr(veh, "total_lateral_offset", 0.0)
                        veh._telemetry_lateral_gap = (
                            abs(lv_y - bus_y)
                            - (veh.params.width + lv_obj.params.width) / 2.0
                        )
                    else:
                        veh._telemetry_lateral_gap = float("nan")
                else:
                    veh.telemetry_leader = "Clear Road"
                    veh._telemetry_front_gap = float("nan")
                    veh._telemetry_lateral_gap = float("nan")
            elif not isinstance(veh, Bus):
                # Car Telemetry
                if lead_vehicle:
                    # Front-to-rear gap: rear of leader minus front of follower
                    # leader.position = leader's FRONT (centre in simulation, but leader.length
                    # is already subtracted here giving correct bumper-to-bumper)
                    gap = lead_vehicle['position'] - lead_vehicle['length'] - veh.position
                    veh.telemetry_leader = f"ID {lead_vehicle.get('id', '?')} (front-rear gap: {gap:.1f}m)"
                    veh._telemetry_front_gap = gap
                    # Lateral gap: side-to-side clearance between the two cars
                    lv_obj = next((u for u in self.vehicles if u.id == lead_vehicle.get('id')), None)
                    if lv_obj is not None:
                        lv_y  = getattr(lv_obj, 'total_lateral_offset', 0.0)
                        car_y = getattr(veh,    'total_lateral_offset', 0.0)
                        veh._telemetry_lateral_gap = abs(lv_y - car_y) - (veh.params.width + lv_obj.params.width) / 2.0
                    else:
                        veh._telemetry_lateral_gap = float('nan')
                else:
                    veh.telemetry_leader = "Clear Road"
                    veh._telemetry_front_gap   = float('nan')
                    veh._telemetry_lateral_gap = float('nan')
                
                if the_bus:
                    dist_to_bus = the_bus.position - veh.position
                    if dist_to_bus > 100.0 or dist_to_bus < 0 or the_bus.state == BusState.IN_BAY:
                        veh.telemetry_bus = "Out of Sight"
                    else:
                        veh.telemetry_bus = f"{the_bus.presence_factor:.2f}"
                else:
                    veh.telemetry_bus = "No Bus"

            # Frozen states: skip bicycle model.
            if isinstance(veh, Bus) and veh.state in (BusState.IN_BAY, BusState.STOPPED_IN_LANE):
                pass
            else:
                # PHYSICS SNIFFER: capture heading BEFORE physics so we can measure
                # the per-frame change and flag any super-physical snap.
                if isinstance(veh, Bus):
                    _heading_before = veh.heading_angle

                # For DECELERATING bus: virtual stationary leader at bus stop gives
                # the IDM a smooth braking target instead of a sudden snap-stop.
                # SCOPE: lead_vehicle is reset to None at the top of every loop iteration,
                # so this assignment only affects the Bus vehicle's own IDM calculation —
                # it CANNOT leak to cars even though lead_vehicle is a loop-local variable.
                if isinstance(veh, Bus) and veh.state == BusState.DECELERATING:
                    # Offset by min_gap so IDM converges to gap=min_gap AT the stop position.
                    stop_leader = {'id': -1, 'position': veh.target_stop_x + veh.params.min_gap,
                                   'velocity': 0.0, 'length': 0.0, 'presence': 1.0}
                    if lead_vehicle is None or (lead_vehicle['position'] - lead_vehicle['length']) > veh.target_stop_x:
                        lead_vehicle = stop_leader

                # WAITING_TO_MERGE: governor owns acceleration; IDM must not overwrite it.
                if isinstance(veh, Bus) and veh.state == BusState.WAITING_TO_MERGE:
                    lead_vehicle = None

                # 3. UPDATE PHYSICS (FOR EVERYONE!)
                # Physics order for WAITING_TO_MERGE bus must match training env exactly:
                #   lon (vel+pos) → finalize_bumper → lateral bicycle → THEN cars
                # Previously: lat (stale vel) → lon → cars → bumper — caused drift mismatch.
                if isinstance(veh, Bus) and veh.state == BusState.WAITING_TO_MERGE:
                    veh.acceleration = merging_bus_acceleration(veh, self.vehicles, veh.acceleration, self.dt)
                veh.update_physics(self.dt, lead_vehicle, bus=the_bus)

                # After longitudinal update: run lateral bicycle for merging bus
                # (uses NEW velocity from this frame — matching training env step order).
                if isinstance(veh, Bus) and veh.state == BusState.WAITING_TO_MERGE:
                    _max_steer  = np.radians(veh.params.max_steer_angle_deg)
                    _steer_rate = np.radians(veh.params.steer_rate_deg_per_s)
                    _lookahead  = max(veh.velocity * 1.0, 5.0)
                    _lat_err    = veh.lat_target - veh.lateral_offset
                    _delta_cmd  = float(np.clip(
                        np.arctan2(_lat_err, _lookahead), -_max_steer, _max_steer))
                    _d_steer    = float(np.clip(
                        _delta_cmd - veh.steer_angle,
                        -_steer_rate * self.dt, _steer_rate * self.dt))
                    veh.steer_angle   += _d_steer
                    veh.heading_angle += (
                        veh.velocity * np.tan(veh.steer_angle)
                        / max(veh.params.wheelbase, 0.1)) * self.dt
                    veh.heading_angle  = float(np.clip(
                        veh.heading_angle, -np.radians(60.0), np.radians(60.0)))
                    veh.lateral_velocity = veh.velocity * np.sin(veh.heading_angle)
                    veh.lateral_offset  += veh.lateral_velocity * self.dt
                    veh.lateral_offset   = float(np.clip(veh.lateral_offset, -4.5, 0.5))

                # PHYSICS SNIFFER: compare heading after update against the
                # maximum physically possible change (steer_rate × dt + 0.01 rad
                # tolerance for floating-point rounding).
                if isinstance(veh, Bus):
                    heading_change = abs(veh.heading_angle - _heading_before)
                    steer_rate_rad = np.radians(
                        getattr(veh.params, 'steer_rate_deg_per_s', 25.0))
                    max_allowed    = steer_rate_rad * self.dt + 0.01   # rad
                    if heading_change > max_allowed:
                        self.heading_anomaly = True
                        print(
                            f"[CRITICAL WARNING] Heading Snap Detected! "
                            f"t={self.time:.2f}s  Δψ={np.degrees(heading_change):.3f}°  "
                            f"(max allowed {np.degrees(max_allowed):.3f}°)"
                        )

        if self.record_frames:
            self._record_bus_follower_trace(the_bus)
            self._record_frame()
        self._remove_finished_cars()

    def _handle_bus_logic(self, bus: Bus):
        dist_to_stop = bus.target_stop_x - bus.position

        # ── STEERING-FIRST AUTOPILOT ─────────────────────────────────────────────
        # Set lat_target for the bicycle model in update_physics.
        # No direct writes to lateral_velocity or position for these states.
        # skip_lateral_steering: during active manoeuvres the
        # algorithmic trajectory must own the lateral axis — the
        # bicycle model running on v*sin(heading) ≈ 0 would
        # otherwise corrupt lateral_velocity and PPO state tracking.
        bus.skip_lateral_steering = (bus.state == BusState.WAITING_TO_MERGE)
        if bus.state == BusState.MOVING:
            bus.lat_target = 0.0                     # stay centred in lane
        elif bus.state == BusState.DECELERATING:
            if self.scenario == "A":
                # In-lane stop: stay centred — no bay pull-in (Scenario B only).
                bus.lat_target = 0.0
            elif 0.0 < dist_to_stop <= bus.entry_taper_length:
                # PATH LOOK-AHEAD: linear ramp from lat=0 at the taper entry point
                # (dist = entry_taper_length = 50 m, matching the DECELERATING trigger)
                # to lat=-3.5 at PATH_LOOK_AHEAD metres before the stop.
                # This starts the bay approach immediately when DECELERATING begins —
                # no intermediate re-alignment to lane centre (the S-curve bug).
                # The bus reaches full bay depth with 18 m to go, giving the 7 m
                # wheelbase enough road to straighten back to 0° heading.
                PATH_LOOK_AHEAD = 18.0
                ramp = bus.entry_taper_length - PATH_LOOK_AHEAD   # 32 m
                look_frac = (bus.entry_taper_length - dist_to_stop) / ramp
                bus.lat_target = max(-3.5, -3.5 * look_frac)
            elif dist_to_stop <= 0.0 and abs(bus.heading_angle) > np.radians(2.0):
                # PARKING CRAWL: bus has passed the nominal stop but is still
                # angled more than 2°.  Keep it at bay depth so the pure-pursuit
                # controller has a lateral target to steer against while the
                # 7 m wheelbase finishes straightening.
                bus.lat_target = -3.5
            else:
                # dist_to_stop <= 0 and heading < 2°: bus aligned in bay,
                # one transitional frame before IN_BAY takes over.
                bus.lat_target = -3.5
        elif bus.state in (BusState.IN_BAY, BusState.STOPPED_IN_LANE):
            bus.lat_target = bus.lateral_offset       # hold position (v=0 → frozen)
        elif bus.state == BusState.WAITING_TO_MERGE:
            bus.lat_target = 0.0   # destination: traffic lane centre

        # 1. ARRIVAL LOGIC
        if (bus.state == BusState.MOVING and 0 < dist_to_stop < 50
                and not getattr(bus, "_stop_served", False)):
            bus.state = BusState.DECELERATING
        
        # The bus arrives when it has physically come to rest near the stop point (its braking is
        # computed in Bus.bay_stop_acceleration); in the bay it must also be parallel to the kerb.
        _stopped = bus.velocity <= BUS_STOPPED_SPEED_MS
        _parallel = abs(bus.heading_angle) <= np.radians(BUS_ALIGN_HEADING_DEG)
        if bus.state == BusState.DECELERATING and dist_to_stop <= 0.5 and _stopped:
            if self.scenario == "A":
                bus.velocity = 0.0
                bus.dwell_timer = bus.stop_duration
                bus.state = BusState.STOPPED_IN_LANE
                bus._stop_served = True
                bus.lateral_offset = 0.0
                bus.heading_angle = 0.0
                bus.steer_angle = 0.0
                bus.wait_time = 0.0
            elif _parallel:
                bus.velocity = 0.0
                bus.dwell_timer = bus.stop_duration
                bus.state = BusState.STOPPED_IN_LANE if self.scenario == "A" else BusState.IN_BAY
                bus._stop_served = True
                bus.wait_time = 0.0 

        # 2. DWELL LOGIC
        if bus.state in [BusState.IN_BAY, BusState.STOPPED_IN_LANE]:
            bus.dwell_timer -= self.dt
            # Virtual blinker: cars see a faint presence throughout dwell, rising
            # in the last YIELD_BLINKER_DWELL_S seconds so they bleed off speed
            # before the bus enters WAITING_TO_MERGE (prevents velocity cliff).
            if bus.state == BusState.IN_BAY:
                from busmerge.rl.merge_constants import YIELD_IN_BAY_PRESENCE, YIELD_BLINKER_PRESENCE, YIELD_BLINKER_DWELL_S
                bus.signaling_merge = (bus.dwell_timer <= YIELD_BLINKER_DWELL_S)
                bus.blinker_presence = YIELD_BLINKER_PRESENCE if bus.signaling_merge else YIELD_IN_BAY_PRESENCE
            if bus.dwell_timer <= 0:
                if self.scenario == "A":
                    bus.state = BusState.MOVING
                    bus.lateral_offset = 0.0
                    bus.heading_angle = 0.0
                    bus.steer_angle = 0.0
                    bus.lateral_velocity = 0.0
                    bus.lat_target = 0.0
                else:
                    bus.state = BusState.WAITING_TO_MERGE
                    bus._merge_progress = 0.0
                    bus.merge_start_x = bus.position
                    from busmerge.rl.traffic_leaders import reset_bus_leader_geometry
                    reset_bus_leader_geometry(bus)
                    bus.wait_time = 0.0
                    bus.signaling_merge = False
                    bus.blinker_presence = 0.0
                    # The merge starts from the pose the bus actually stopped in (no reset).
                    bus.lat_target       = 0.0   # destination: traffic lane

        # 3. AI MERGE LOGIC — BICYCLE MODEL (The PyTorch Brain)
        if bus.state == BusState.WAITING_TO_MERGE:
            bus.wait_time += self.dt

            # ── SENSE: the same observation the training env builds ───────────────
            obs = build_observation(
                bus, self.vehicles, self._prev_bus_vel, self.dt, self.feature_dim,
                noise_sigma=self.noise_sigma, noise_state=self._perception_noise,
            )
            self._prev_bus_vel = bus.velocity
            gap, nearest_speed, nearest_car = obs.gap, obs.nearest_speed, obs.nearest_car
            merge_progress = obs.merge_progress
            bus._merge_progress = merge_progress   # keep for legacy telemetry
            state_tensor = torch.FloatTensor(obs.state).unsqueeze(0)

            if self.external_action is not None:
                raw_steer, raw_gas = (float(self.external_action[0]), float(self.external_action[1]))
            else:
                with torch.no_grad():
                    action_mean, _, _ = self.brain.policy(state_tensor)
                # 2D action: (steer_intent, gas_intent) in [-1, 1]
                # Defensive: if checkpoint loaded with action_dim=1, gas defaults to 0
                raw_steer = float(action_mean[0, 0].item())
                raw_gas   = float(action_mean[0, 1].item()) if action_mean.shape[1] > 1 else 0.0

            # Predictive governor — must match how the checkpoint was trained.
            # exp7sat v7: trained with --disable-governor; safety shield still runs.
            steer_intent    = float(np.clip(raw_steer, -1.0, 1.0))
            gas_intent      = float(np.clip(raw_gas,   -1.0, 1.0))
            from busmerge.rl.governor_logic import governor_check, apply_safety_shield
            rel_speed = bus.velocity - nearest_speed
            _gov_ok, steer_intent, gas_intent, governor_reason = governor_check(
                steer_intent, gas_intent, merge_progress, gap, rel_speed, nearest_car,
                disabled=self.governor_disabled,
            )
            _nw = nearest_car.params.width if nearest_car is not None else 1.85
            _steer_after_governor = steer_intent
            steer_intent, gas_intent, _shield_cond = apply_safety_shield(
                steer_intent, gas_intent, merge_progress, gap, rel_speed,
                nearest_speed, nearest_car, _nw, governor_reason=governor_reason, dt=self.dt,
            )
            # Telemetry: persist this frame's decision reasons on the bus so
            # _record_frame() (called later this same step()) can surface them —
            # governor_reason/_shield_cond are otherwise local and thrown away.
            bus.last_governor_reason = governor_reason
            bus.last_shield_condition = _shield_cond
            self.last_decision = {
                "governor_ok": _gov_ok, "governor_reason": governor_reason,
                "shield": _shield_cond,
                "steer_after_governor": _steer_after_governor, "steer": steer_intent, "gas": gas_intent,
                "raw_steer": raw_steer, "raw_gas": raw_gas,
            }

            # ── APPLY TARGETS — bicycle model does all movement ──
            BAY_DEPTH   = _MC_BAY_DEPTH
            BUS_MAX_SPD = _MC_BUS_MAX_SPEED   # imported from merge_constants — guaranteed to match training
            lat_target   = float(np.interp(steer_intent, [-1.0, 1.0], [BAY_DEPTH, 0.0]))
            speed_target = max(0.0, float(gas_intent)) * BUS_MAX_SPD
            bus.lat_target = lat_target
            speed_error    = speed_target - bus.velocity
            bus.acceleration = float(np.clip(2.0 * speed_error, -3.0, _MC_MERGE_ACCEL_MAX))

            # NOTE: inline lateral physics moved to after update_physics in step()
            # so the bicycle model uses the velocity from THIS frame (not stale).
            # Physics order now matches busmerge/rl/env.py exactly:
            #   lon (velocity+position) → finalize_bumper → lateral → cars

            # Merge complete: lateral_offset has reached lane centre
            if bus.lateral_offset >= -0.1:
                bus.state    = BusState.MOVING
                bus.lat_target = 0.0

        # heading_angle updated inline above during WAITING_TO_MERGE; bicycle
        # model handles DECELERATING/MOVING via update_physics.

    def _try_spawn_car(self):
        """Arrivals at the road start, placed only in a state a real car could be in.

        Arrivals are drawn as before (probability traffic_rate·dt per frame, only while the entry is
        clear: 0.5 s since the last car and the nearest car at least 15 m in), so the traffic volume is
        unchanged. A car enters at the lower of its desired speed and the safe speed behind the car ahead
        (busmerge.safe_speed.safe_speed, the same law every follower obeys). If that is below SPAWN_MIN_SPEED_MS the arrival is held and
        placed as soon as there is room: delayed, never dropped, and never in need of impossible braking.
        """
        if self.time - self.last_spawn_time < 0.5:
            return
        leader = min(self.vehicles, key=lambda v: v.position) if self.vehicles else None
        if leader is not None and leader.position < 15.0:
            return
        if self._pending_arrivals == 0:
            if self.cars_spawned_count >= self.cfg.total_cars_to_spawn:
                return
            if random.random() >= self.traffic_rate * self.dt:
                return
            self._pending_arrivals = 1

        _, sampled_params = sample_vehicle_params()
        start_speed = max(5.5, sampled_params.max_speed * random.uniform(0.68, 0.95))
        if leader is not None:
            room = float(leader.position) - float(leader.params.length) - float(sampled_params.min_gap)
            start_speed = min(start_speed, safe_speed(
                room, float(leader.velocity), float(sampled_params.comfortable_brake), self.dt))
            if start_speed < SPAWN_MIN_SPEED_MS:
                return
        self.global_id_counter += 1
        c = Vehicle(self.global_id_counter, position=0.0, velocity=start_speed, params=sampled_params)
        self.vehicles.append(c)
        self.last_spawn_time = self.time
        self.cars_spawned_count += 1
        self._pending_arrivals = 0

    def all_vehicles_finished(self) -> bool:
        if self.cars_spawned_count < self.cfg.total_cars_to_spawn: return False
        if len(self.vehicles) == 0: return True
        return False

    def _get_veh_state(self, veh):
        length_for_gap = veh.params.length
        if isinstance(veh, Bus):
            length_for_gap = veh.projected_length_along_x()

        return {
            'id': veh.id,
            'position': veh.position,
            'velocity': veh.velocity,
            'length': length_for_gap,
            'presence': getattr(veh, 'presence_factor', 1.0)
        }

    def _find_car_behind_bus(self, bus: Bus, sticky_id=None):
        """Nearest car behind the bus front; keep same car_id when still valid."""
        if bus is None:
            return None
        if sticky_id is not None:
            for veh in self.vehicles:
                if isinstance(veh, Bus) or veh.id != sticky_id:
                    continue
                if float(veh.position) < float(bus.position) - 0.5:
                    return veh
                break

        follower = None
        best_x = -1.0
        for veh in self.vehicles:
            if isinstance(veh, Bus):
                continue
            if float(veh.position) >= float(bus.position) - 1.0:
                continue
            if float(veh.position) > best_x:
                best_x = float(veh.position)
                follower = veh
        return follower

    def _should_record_follower_trace(self, bus: Bus) -> bool:
        """One row per step from IN_BAY through merge completion (progress → 1)."""
        if bus is None or self.scenario != "B":
            return False
        merge_progress = float(np.clip((bus.lateral_offset - (-3.5)) / 3.5, 0.0, 1.0))
        if bus.state in (BusState.IN_BAY, BusState.WAITING_TO_MERGE):
            self._follower_trace_active = True
            return True
        if self._follower_trace_active:
            if bus.state == BusState.MOVING and merge_progress < 0.995:
                return True
            self._follower_trace_active = False
        return False

    def _record_bus_follower_trace(self, bus: Bus) -> None:
        """One row per simulation step (dt=0.1 s) — telemetry only, no physics."""
        if bus is None:
            return
        if not self._should_record_follower_trace(bus):
            return

        from busmerge.safe_speed import bus_blocking_max_front, leader_max_follower_front
        from busmerge.rl.merge_yield import bus_gap_to_car_front
        from busmerge.rl.traffic_leaders import resolve_car_leader

        merge_progress = float(np.clip((bus.lateral_offset - (-3.5)) / 3.5, 0.0, 1.0))
        bus_x = float(bus.position)
        prev_bus_x = self._trace_prev_bus_x
        bus_dx = float("nan") if prev_bus_x is None else bus_x - float(prev_bus_x)
        self._trace_prev_bus_x = bus_x
        bus_max_front, _ = bus_blocking_max_front(bus, self.vehicles)

        row = {
            "frame": len(self.follower_trace),
            "time": round(self.time, 4),
            "dt": self.dt,
            "bus_state": bus.state.name,
            "bus_x": bus_x,
            "bus_dx": bus_dx,
            "bus_v": float(bus.velocity),
            "bus_max_front": float(bus_max_front) if bus_max_front is not None else float("nan"),
            "bus_merge_progress": merge_progress,
            "car_id": None,
            "x": float("nan"),
            "v": float("nan"),
            "accel": float("nan"),
            "front_gap": float("nan"),
            "rear_gap_to_bus": float("nan"),
            "max_front_allowed": float("nan"),
            "yield_eff": float("nan"),
            "yield_raw": float("nan"),
            "leader_id": None,
            "bus_is_leader": False,
            "leader_presence": float("nan"),
            "leader_info": "",
            "bus_visibility": "",
            "car_state": "",
            "car_dx": float("nan"),
            "car_dv": float("nan"),
            "comfort_brake": float("nan"),
            "reaction_timer": float("nan"),
            "brake_note": "",
            "follower_switched": False,
            "accel_paradox": False,
            "blinker_presence": float(getattr(bus, "blinker_presence", 0.0)),
            "signaling_merge": bool(getattr(bus, "signaling_merge", False)),
        }

        car = self._find_car_behind_bus(bus, self._follower_trace_car_id)
        if car is not None:
            switched = (
                self._trace_prev_car_id is not None
                and int(car.id) != int(self._trace_prev_car_id)
            )
            if switched:
                self._trace_prev_car_x = None
                self._trace_prev_car_v = None
            self._follower_trace_car_id = car.id
            self._trace_prev_car_id = int(car.id)
            idx = self.vehicles.index(car)
            leader, _ = resolve_car_leader(self.vehicles, idx, bus)
            y_eff = float(getattr(car, "last_applied_yield", car._merge_yield_factor(bus)))
            y_raw = float(car._merge_yield_factor(bus))
            bus_is_leader = False
            if leader is not None:
                max_front = leader_max_follower_front(leader, float(car.params.min_gap))
                bus_is_leader = (
                    leader.get("id") == bus.id
                    or float(leader.get("presence", 1.0)) < 0.99
                )
            else:
                max_front = float("nan")
            if car.is_squeezing:
                car_state = "Squeezing"
            elif car.reaction_timer > 0:
                car_state = "Reacting"
            else:
                car_state = "Cruising"
            car_x = float(car.position)
            car_v = float(car.velocity)
            car_accel = float(car.acceleration)
            prev_car_x = self._trace_prev_car_x
            prev_car_v = self._trace_prev_car_v
            car_dx = float("nan") if prev_car_x is None else car_x - float(prev_car_x)
            car_dv = float("nan") if prev_car_v is None else car_v - float(prev_car_v)
            self._trace_prev_car_x = car_x
            self._trace_prev_car_v = car_v
            comfort = float(getattr(car.params, "comfortable_brake", 2.5))
            # Classify IDM foot first (logged acceleration), then annotate bumper.
            idm_note = ""
            if car_v < 0.05:
                idm_note = "stopped"
            elif car_accel <= -5.0:
                idm_note = "emergency"
            elif car_accel <= -3.5:
                idm_note = "hard"
            elif car_accel <= -comfort:
                idm_note = "comfort"
            # Accel paradox: implied Δv/dt differs from logged accel by > 3 m/s²
            # Ignore the trivial v→0 clamp (car already stopping; Δv just hits the floor).
            accel_paradox = False
            if car_dv == car_dv:  # not NaN
                implied = car_dv / self.dt if self.dt > 0 else 0.0
                if abs(implied - car_accel) > 3.0:
                    # The frame in which a car comes to rest: speed is floored at 0, so Δv is
                    # smaller than a*dt and the logged accel has already been reset to 0. That is
                    # the speed floor, not two competing physics paths.
                    stopped_this_frame = car_v < 0.05 and car_dv < 0.0
                    if not stopped_this_frame:
                        accel_paradox = True
            brake_note = idm_note
            row.update({
                "car_id": car.id,
                "x": car_x,
                "v": car_v,
                "accel": car_accel,
                "front_gap": float(getattr(car, "_telemetry_front_gap", float("nan"))),
                "rear_gap_to_bus": float(bus_gap_to_car_front(bus, car)),
                "max_front_allowed": float(max_front),
                "yield_eff": y_eff,
                "yield_raw": y_raw,
                "leader_id": leader.get("id") if leader else None,
                "bus_is_leader": bus_is_leader,
                "leader_presence": float(leader.get("presence", 1.0)) if leader else float("nan"),
                "leader_info": str(getattr(car, "telemetry_leader", "")),
                "bus_visibility": str(getattr(car, "telemetry_bus", "")),
                "car_state": car_state,
                "car_dx": car_dx,
                "car_dv": car_dv,
                "comfort_brake": comfort,
                "reaction_timer": float(car.reaction_timer),
                "brake_note": brake_note,
                "follower_switched": switched,
                "accel_paradox": accel_paradox,
            })

        self.follower_trace.append(row)

    def _record_frame(self):
        the_bus = next((v for v in self.vehicles if isinstance(v, Bus)), None)
        by_x = sorted(self.vehicles, key=lambda v: v.position, reverse=True)
        rank_by_id = {v.id: i for i, v in enumerate(by_x)}
        from busmerge.rl.queue_analytics import parse_leader_id
        for v in self.vehicles:
            state_desc = v.state.name if isinstance(v, Bus) else "Cruising"
            if not isinstance(v, Bus):
                if v.is_squeezing: state_desc = "Squeezing!"
                elif v.reaction_timer > 0: state_desc = "Reacting..."

            final_presence = getattr(v, 'presence_factor', 1.0)
            leader_info = getattr(v, 'telemetry_leader', 'N/A')
            bus_vis_info = getattr(v, 'telemetry_bus', 'N/A')
            _leader_id = parse_leader_id(leader_info)
            _queue_rank = rank_by_id.get(v.id, -1)

            _bus_control = ""
            if isinstance(v, Bus):
                if v.state == BusState.WAITING_TO_MERGE:
                    _bus_control = "PPO+Governor"
                elif v.state == BusState.DECELERATING:
                    _bus_control = "IDM→stop"
                elif v.state == BusState.MOVING:
                    _bus_control = (
                        "IDM+queue" if _leader_id is not None else "IDM free-road"
                    )
                elif v.state in (BusState.IN_BAY, BusState.STOPPED_IN_LANE):
                    _bus_control = "frozen"

            # Heading angle:
            # Bus: use _logged_heading_deg captured in _handle_bus_logic BEFORE update_physics
            #      overwrites lateral_velocity. This gives the true geometric heading.
            # Car: use heading_angle from the bicycle model (computed in update_physics).
            if isinstance(v, Bus):
                # heading_angle is kept in sync for all states:
                # DECELERATING → bicycle model; WAITING_TO_MERGE → arctan2 from motion
                heading_deg = float(np.degrees(v.heading_angle))
            else:
                heading_deg = float(np.degrees(getattr(v, 'heading_angle', 0.0)))

            # Physical collision: only flag as real overlap when BOTH gaps are simultaneously negative
            fg = getattr(v, '_telemetry_front_gap',   float('nan'))
            lg = getattr(v, '_telemetry_lateral_gap', float('nan'))
            physical_collision = (not np.isnan(fg) and not np.isnan(lg)
                                  and fg < 0.0 and lg < 0.0)

            prev_x = self._frame_prev_x.get(v.id)
            dx = float('nan') if prev_x is None else float(v.position) - float(prev_x)
            self._frame_prev_x[v.id] = float(v.position)

            _bus_merge_prog = (
                float(np.clip((v.lateral_offset - (-3.5)) / 3.5, 0.0, 1.0))
                if isinstance(v, Bus) else float('nan')
            )
            _yield_eff = float('nan')
            if not isinstance(v, Bus) and the_bus is not None:
                if getattr(the_bus.state, "name", "") == "WAITING_TO_MERGE":
                    _yield_eff = float(v._merge_yield_factor(the_bus))
            self.frame_history.append({
                'time': self.time,
                'id': v.id,
                'type': "Bus" if isinstance(v, Bus) else "Car",
                'merge_progress': _bus_merge_prog,
                'class': "Bus" if isinstance(v, Bus) else getattr(v, 'vehicle_class', 'Mid'),
                'x': v.position,
                'dx': dx,
                'v': v.velocity,
                'length': v.params.length,
                'width': v.params.width,
                'state': state_desc,
                'presence': final_presence,
                'leader_info': leader_info,
                'leader_id': _leader_id,
                'queue_rank': _queue_rank,
                'bus_visibility': bus_vis_info,
                'lateral_offset': getattr(v, 'lateral_offset', 0.0),
                'lane_drift':     getattr(v, 'lane_drift', 0.0),
                'total_lat':      getattr(v, 'total_lateral_offset', 0.0),
                'steer_angle_deg': float(np.degrees(getattr(v, 'steer_angle', 0.0))),
                'heading_deg':    heading_deg,
                'politeness':      getattr(getattr(v, 'params', None), 'politeness_factor', float('nan')),
                'steer_rate':      getattr(getattr(v, 'params', None), 'steer_rate_deg_per_s', float('nan')),
                'front_gap':        fg,
                'lateral_gap':      lg,
                'physical_collision': physical_collision,
                'heading_anomaly':  self.heading_anomaly if isinstance(v, Bus) else False,
                'yield_eff': _yield_eff,
                'bus_control': _bus_control if isinstance(v, Bus) else "",
                'blinker_presence': float(getattr(the_bus, 'blinker_presence', 0.0)) if isinstance(v, Bus) else float('nan'),
                'governor_reason': str(getattr(v, 'last_governor_reason', "")) if (isinstance(v, Bus) and v.state == BusState.WAITING_TO_MERGE) else "",
                'shield_condition': str(getattr(v, 'last_shield_condition', "")) if (isinstance(v, Bus) and v.state == BusState.WAITING_TO_MERGE) else "",
            })

    def _remove_finished_cars(self):
        active = []
        for v in self.vehicles:
            if v.position > self.road_length:
                self.cars_finished_count += 1
            else:
                active.append(v)
        self.vehicles = active

    def get_results(self):
        return pd.DataFrame(self.frame_history)

    def get_follower_trace(self):
        return pd.DataFrame(self.follower_trace)

class AnalyticsEngine:
    def __init__(self, dataframe: pd.DataFrame, config: SimConfig):
        self.df = dataframe
        self.cfg = config

    def compute_kpis(self):
        if self.df.empty:
            return {"avg_person_speed": 0.0, "throughput_people": 0}

        vehicles = self.df.groupby('id')
        total_w_dist = 0.0
        total_w_time = 0.0
        total_people_arrived = 0

        for v_id, trip in vehicles:
            v_type = trip.iloc[0]['type']
            pax = self.cfg.pax_per_bus if v_type == 'Bus' else self.cfg.pax_per_car
            
            dist = trip['x'].max() - trip['x'].min()
            duration = trip['time'].max() - trip['time'].min()
            
            if duration < 0.1: continue

            total_w_dist += (dist * pax)
            total_w_time += (duration * pax)
            
            if trip['x'].max() > (self.cfg.road_length - 20):
                total_people_arrived += pax

        if total_w_time > 0:
            avg_person_speed = (total_w_dist / total_w_time) * 3.6
        else:
            avg_person_speed = 0.0
            
        return {
            "avg_person_speed": avg_person_speed,
            "throughput_people": int(total_people_arrived) 
        }