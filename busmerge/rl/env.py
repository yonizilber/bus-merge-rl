from typing import Optional

import numpy as np
import random
from collections import deque


from busmerge.geometry import compute_sat_overlap_area, vehicle_corners
from busmerge.vehicle import Vehicle, Bus, BusState, CAR_PARAMS, sample_vehicle_params
from busmerge.rl.observation import build_observation
from busmerge.rl.merge_success import is_production_merge_complete
from busmerge.config import PhysicsMode, SimConfig
from busmerge.simulation import SimulationEngine
from busmerge.rl.merge_constants import (
    BUS_WIDTH, BUS_LENGTH, BAY_DEPTH,
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

    State vector  : 11 features (see busmerge.rl.feature_encoding.encode_features)

    Physics       : None of its own. Every step is executed by SimulationEngine.step()
                    (the same code the Streamlit app runs); this class only generates the
                    training scenarios, encodes observations and computes the reward.

    Merge progress: Derived from actual lateral_offset, not a stored scalar.
                    merge_progress = clip((offset - BAY_DEPTH) / (-BAY_DEPTH), 0, 1)
                    0 = bus fully in bay, 1 = bus fully back in traffic lane.
    """

    def __init__(self, eval_mode=False, governor_disabled=False,
                 physics_mode: PhysicsMode = PhysicsMode.PRODUCTION):
        self.dt        = 0.1
        self.physics_mode = physics_mode
        self.engine: Optional[SimulationEngine] = None
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

        self._attach_engine()
        return self._get_state()

    def _attach_engine(self):
        """Put the scenario the generator just built into a SimulationEngine, which then runs it."""
        cfg = SimConfig(total_cars_to_spawn=0, physics_mode=self.physics_mode)  # no new arrivals
        engine = SimulationEngine(scenario="B", config=cfg, governor_disabled=self.governor_disabled,
                                  load_brain=False)
        assert abs(engine.dt - self.dt) < 1e-9, "engine and env time steps differ"
        engine.record_frames = False
        engine.cars_spawned_count = cfg.total_cars_to_spawn
        engine.vehicles = [self.bus] + list(self.vehicles)
        engine.noise_sigma = 0.0  # observation noise is applied by this env's encoder
        self.engine = engine

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
                veh._physics_mode = self.physics_mode.value
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
        steer, gas = self._parse_action(action_value)
        cmd = self._control_and_tick(steer, gas)
        return self._reward_and_terminal(cmd)

    def _parse_action(self, action_value):
        """Flatten and clip the raw action; update the action-quality telemetry."""
        self.current_step += 1
        self.last_intervened = False
        self.last_shield_condition = ""
        self.last_success = False
        self.last_crash   = False
        self.last_timeout = False
        self.last_governor_veto   = False
        self.last_governor_reason = ""

        action_arr = np.asarray(action_value, dtype=np.float32).flatten()
        _vol = float(np.sum(np.abs(action_arr - self._prev_action)))
        _steer_jerk = float(abs(action_arr[0] - self._prev_action[0]))
        self._peak_steer_jerk = max(self._peak_steer_jerk, _steer_jerk)
        self._action_volatility_sum   += _vol
        self._action_volatility_count += 1
        self._prev_action = action_arr.copy()
        steer_intent = float(np.clip(action_arr[0], -1.0, 1.0))  # +1 = steer into lane
        gas_intent   = float(np.clip(action_arr[1], -1.0, 1.0))  # +1 = accelerate
        return steer_intent, gas_intent

    def _control_and_tick(self, steer_intent, gas_intent):
        """Hand the agent's action to the engine for one step; report what the controller did.

        The engine runs governor, shield, autopilot, bumper rules, the bicycle model and all cars.
        """
        eng = self.engine
        eng.vehicles = [self.bus] + list(self.vehicles)  # env.vehicles is the source of truth between steps
        eng.external_action = (steer_intent, gas_intent)
        eng.last_decision = None
        self._prev_bus_vel = self.bus.velocity
        self._governor_raw_steer = steer_intent
        eng.step()
        self.vehicles = [v for v in eng.vehicles if v is not self.bus]  # cars that left the road are gone

        d = eng.last_decision
        if d is None:  # the bus left WAITING_TO_MERGE during this step
            return {"raw_steer_agent": steer_intent, "raw_gas_agent": gas_intent,
                    "raw_steer": steer_intent, "intervened": False, "intervention_strength": 0.0,
                    "steer_intent": steer_intent, "gas_intent": gas_intent}

        self.last_governor_reason = d["governor_reason"]
        if not d["governor_ok"]:
            self.last_governor_veto = True
            self.episode_governor_vetos += 1
        self.last_shield_condition = d["shield"]
        steer_after_governor = d["steer_after_governor"]
        intervened = (d["shield"] != "" or abs(steer_after_governor - d["steer"]) > 1e-6
                      or abs(d["gas"] - d["raw_gas"]) > 1e-6)
        self.last_intervened = intervened
        if intervened:
            self.episode_shields += 1
        strength = float(np.clip(
            abs(steer_after_governor - d["steer"]) / max(abs(steer_after_governor), 1e-8), 0.0, 1.0))
        return {"raw_steer_agent": steer_intent, "raw_gas_agent": gas_intent,
                "raw_steer": steer_after_governor, "intervened": intervened,
                "intervention_strength": strength, "steer_intent": d["steer"], "gas_intent": d["gas"]}

    def _reward_and_terminal(self, cmd):
        """Reward, termination and diagnostics after the physics tick."""
        _raw_steer_agent = cmd["raw_steer_agent"]
        _raw_gas_agent = cmd["raw_gas_agent"]
        raw_steer = cmd["raw_steer"]
        intervened = cmd["intervened"]
        intervention_strength = cmd["intervention_strength"]
        steer_intent = cmd["steer_intent"]
        gas_intent = cmd["gas_intent"]

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
            _bus_corners = vehicle_corners(
                float(self.bus.position), float(self.bus.lateral_offset),
                float(BUS_LENGTH), float(BUS_WIDTH), float(self.bus.heading_angle),
            )
            _car_corners = vehicle_corners(
                float(_nearest_for_sat.position),
                float(getattr(_nearest_for_sat, "total_lateral_offset", 0.0)),
                float(_nearest_for_sat.params.length), float(_nearest_for_sat.params.width),
                float(getattr(_nearest_for_sat, "heading_angle", 0.0)),
            )
            _sat_area = compute_sat_overlap_area(_bus_corners, _car_corners)

        # lon_dist for reward + features = bus_rear − car_front (same as `gap` above)
        _lon_dist = float(gap)

        # Term 4: terminal success (+5000)
        if self._merge_complete():
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

    def _merge_complete(self) -> bool:
        """Terminal success: the same rule the engine and the app use to call the merge done."""
        return is_production_merge_complete(
            float(self.bus.lateral_offset), self.bus.state, saw_waiting_to_merge=True)

    def _get_state(self):
        """The agent's observation, built by the same function the production engine uses."""
        return build_observation(
            self.bus, self.vehicles, self._prev_bus_vel, self.dt, getattr(self, "feature_dim", 11),
            noise_sigma=0.0 if self.eval_mode else self.noise_sigma,
            noise_state=self._perception_noise,
        ).state

    def _maybe_distract(self, params):
        """15% chance a spawned car is 'distracted' — slower reaction time."""
        if not self.eval_mode and random.random() < 0.15:
            factor = random.uniform(1.5, 3.0)
            params.base_reaction_time   *= factor
            params.shock_reaction_time   = max(params.shock_reaction_time,
                                               params.base_reaction_time + 0.5)
