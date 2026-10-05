"""EXPERIMENTAL: training environment whose physics is the production SimulationEngine.

``BusMergeEnv`` re-implements the world (bus, cars, controller, bumper rules) for training.
``EngineEnv`` keeps its scenario generator, observation encoder and reward, but advances the
world with ``SimulationEngine.step`` so training and the app share one physics implementation.
"""
from __future__ import annotations

import numpy as np

from busmerge.config import PhysicsMode, SimConfig
from busmerge.rl.env import BusMergeEnv
from busmerge.simulation import SimulationEngine
from busmerge.vehicle import BusState


class EngineEnv(BusMergeEnv):
    def __init__(self, *args, physics_mode: PhysicsMode = PhysicsMode.PRODUCTION, **kwargs):
        super().__init__(*args, **kwargs)
        self._engine_physics_mode = physics_mode
        self.engine: SimulationEngine | None = None

    # -- world setup ---------------------------------------------------------------
    def reset(self):
        state = super().reset()  # scenario generator: builds self.bus and self.vehicles (cars)
        cfg = SimConfig(total_cars_to_spawn=0, physics_mode=self._engine_physics_mode)
        engine = SimulationEngine(scenario="B", config=cfg, governor_disabled=self.governor_disabled,
                                  load_brain=False)
        assert abs(engine.dt - self.dt) < 1e-9, "engine and env time steps differ"
        engine.record_frames = False
        engine.cars_spawned_count = cfg.total_cars_to_spawn  # training scenarios have no new arrivals
        engine.vehicles = [self.bus] + list(self.vehicles)
        engine.noise_sigma = 0.0  # the agent's observation noise is applied by the env encoder
        self.engine = engine
        return state

    # -- one step: engine does governor, shield, controller and physics ---------------
    def _control_and_tick(self, steer_intent, gas_intent):
        eng = self.engine
        eng.external_action = (steer_intent, gas_intent)
        self._prev_bus_vel = self.bus.velocity
        eng.last_decision = None
        eng.step()
        # The engine drops cars that left the road; keep the env's view in sync.
        self.vehicles = [v for v in eng.vehicles if v is not self.bus]

        d = eng.last_decision
        if d is None:  # bus already left WAITING_TO_MERGE in this step
            return {"raw_steer_agent": steer_intent, "raw_gas_agent": gas_intent,
                    "raw_steer": steer_intent, "intervened": False, "intervention_strength": 0.0,
                    "steer_intent": steer_intent, "gas_intent": gas_intent}
        self._governor_raw_steer = steer_intent
        if not d["governor_ok"]:
            self.last_governor_veto = True
            self.last_governor_reason = d["governor_reason"]
            self.episode_governor_vetos += 1
        else:
            self.last_governor_reason = d["governor_reason"]
        self.last_shield_condition = d["shield"]
        raw_steer = d["steer_after_governor"]
        intervened = (d["shield"] != "" or abs(raw_steer - d["steer"]) > 1e-6
                      or abs(d["gas"] - d["raw_gas"]) > 1e-6)
        self.last_intervened = intervened
        if intervened:
            self.episode_shields += 1
        strength = float(np.clip(abs(raw_steer - d["steer"]) / max(abs(raw_steer), 1e-8), 0.0, 1.0))
        return {"raw_steer_agent": steer_intent, "raw_gas_agent": gas_intent, "raw_steer": raw_steer,
                "intervened": intervened, "intervention_strength": strength,
                "steer_intent": d["steer"], "gas_intent": d["gas"]}

    def _merge_complete(self) -> bool:
        return self.bus.state == BusState.MOVING or super()._merge_complete()
