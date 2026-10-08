from dataclasses import dataclass
from enum import Enum


class PhysicsMode(Enum):
    """Controls bumper-kinematics enforcement and telemetry verbosity.

    PRODUCTION  — enforce velocity caps + loud telemetry flags (default for
                  Streamlit and smoke tests; keeps smooth visuals while making
                  Hand-of-God events observable).
    DEBUG       — skip velocity overrides (same as TRAINING); overlaps are reported by
                  busmerge.invariants, nothing is raised.
    TRAINING    — skip velocity caps and position snaps; spongy SAT is the sole
                  crash judge so PPO can feel overlap pain (required for v10).
    """
    PRODUCTION = "production"
    DEBUG = "debug"
    TRAINING = "training"


@dataclass
class SimConfig:
    # --- Traffic Generation ---
    road_length: float = 1000.0   # meters
    traffic_rate: float = 0.3     # cars/second
    total_cars_to_spawn: int = 50 # <--- NEW: Fixed Batch Size
    
    # --- Passenger Loads (The Modular Variables) ---
    pax_per_car: float = 1.2
    pax_per_bus: float = 50.0
    
    # --- Scenario Logic ---
    bus_stop_position: float = 300.0
    bus_dwell_time: float = 15.0  # seconds
    
    # --- Physics Limits ---
    speed_limit_car: float = 50.0 / 3.6 # m/s
    speed_limit_bus: float = 40.0 / 3.6 # m/s

    # --- Physics enforcement ---
    physics_mode: PhysicsMode = PhysicsMode.PRODUCTION
    # EXPERIMENTAL: replace the follower speed caps, position trims and stop-holds with one
    # safe-speed limit on acceleration (busmerge/safe_speed.py). Off by default.
    strict_physics: bool = False