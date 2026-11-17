from dataclasses import dataclass
from typing import Optional


@dataclass
class SimConfig:
    # --- Traffic Generation ---
    road_length: float = 1000.0   # meters
    traffic_rate: float = 0.3     # cars/second
    total_cars_to_spawn: int = 50 # <--- NEW: Fixed Batch Size
    
    # --- Passenger loads (only the app's person-weighted KPIs use them; the stop-design experiment applies
    # occupancy at analysis time). The explorer's Israeli starting values: 1.35 per car, 20 per bus. ---
    pax_per_car: float = 1.35
    pax_per_bus: float = 20.0
    
    # --- Scenario Logic ---
    bus_stop_position: float = 300.0
    bus_dwell_time: float = 15.0  # seconds
    
    # --- Experiment arrivals (busmerge/experiments) ---
    # When set, car arrivals come from a schedule drawn from their own random generator: Poisson arrivals at
    # traffic_rate during the first arrival_window_s seconds, each car's class and size drawn with them. Two
    # scenarios with the same arrival_seed get the same cars, and a car that finds the entry blocked waits
    # instead of being lost (BUGS O20). None keeps the app's arrivals unchanged.
    arrival_seed: Optional[int] = None
    arrival_window_s: float = 150.0

    # --- Physics Limits ---
    speed_limit_car: float = 50.0 / 3.6 # m/s
    speed_limit_bus: float = 40.0 / 3.6 # m/s
