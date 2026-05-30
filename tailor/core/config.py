"""Application configuration and constants."""

from __future__ import annotations

import os
from pathlib import Path


# Paths
APP_NAME = "TAILOR"
APP_AUTHOR = "TAILOR"

# User data directory (cross-platform)
if os.name == "nt":
    _DATA_ROOT = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
else:
    _DATA_ROOT = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

APP_DATA_DIR = _DATA_ROOT / APP_AUTHOR / APP_NAME
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = APP_DATA_DIR / "tailor.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Supported file extensions
ULG_EXTENSIONS = {".ulg"}

# Default coordinate frames
class CoordFrame:
    """Coordinate frame identifiers."""
    FRD = "frd"           # Front-Right-Down (PX4 body frame)
    NED = "ned"           # North-East-Down (world)
    ENU = "enu"           # East-North-Up (world)
    WIND = "wind"         # Wind axis (stability / wind)
    THRUST_VERT = "thrust_vertical"  # Tail-sitter hover: thrust vertical


# PX4 uORB messages we parse
CORE_UORB_MESSAGES = [
    "sensor_accel",
    "sensor_gyro",
    "sensor_mag",
    "vehicle_attitude",
    "vehicle_attitude_setpoint",
    "vehicle_rates_setpoint",
    "vehicle_local_position",
    "vehicle_local_position_setpoint",
    "vehicle_global_position",
    "actuator_outputs",
    "actuator_controls",
    "actuator_motors",
    "actuator_servos",
    "vehicle_status",
    "vehicle_command",
    "manual_control_setpoint",
    "airspeed",
    "battery_status",
    "input_rc",
    "esc_status",
    "rpm",
    "tecs_status",
    "vehicle_constraints",
    "landing_gear",
]

# PX4 nav_state values for flight mode detection
class NavState:
    """PX4 navigation state codes."""
    MANUAL = 0
    ALTCTL = 1
    POSCTL = 2
    AUTO_MISSION = 3
    AUTO_LOITER = 4
    AUTO_RTL = 5
    AUTO_LANDENGFAIL = 8
    AUTO_LANDGPSFAIL = 9
    ACRO = 10
    OFFBOARD = 14
    STAB = 15
    AUTO_TAKEOFF = 17
    AUTO_LAND = 18
    AUTO_FOLLOW_TARGET = 20
    AUTO_PRECLAND = 21
    ORBIT = 22
    AUTO_VTOL_TAKEOFF = 24

    # Tail-sitter / VTOL mode helpers
    MULTIROTOR_STATES = {MANUAL, ALTCTL, POSCTL, AUTO_LOITER, AUTO_LAND, AUTO_TAKEOFF}
    FIXEDWING_STATES = {AUTO_MISSION, AUTO_RTL, AUTO_LANDENGFAIL, AUTO_LANDGPSFAIL}
    VTOL_STATES = {AUTO_VTOL_TAKEOFF}

    @classmethod
    def classify(cls, nav_state: int) -> str:
        """Return 'multirotor', 'fixedwing', or 'transition'."""
        if nav_state in cls.MULTIROTOR_STATES:
            return "multirotor"
        if nav_state in cls.FIXEDWING_STATES:
            return "fixedwing"
        if nav_state in cls.VTOL_STATES:
            return "transition"
        return "unknown"


# Default vehicle template fields
DEFAULT_VEHICLE_PARAMS = {
    "mass": 0.0,                   # kg
    "inertia_ixx": 0.0,           # kg*m^2
    "inertia_iyy": 0.0,
    "inertia_izz": 0.0,
    "inertia_ixz": 0.0,
    "cg_x": 0.0,                  # m, from reference point
    "cg_y": 0.0,
    "cg_z": 0.0,
    "motor_thrust_coeff": 0.0,    # N per unit command
    "motor_torque_coeff": 0.0,    # Nm per unit command
    "servo_efficiency": 1.0,      # fraction
    "wingspan": 0.0,              # m
    "wing_area": 0.0,             # m^2
    "num_motors": 4,
    "num_servos": 0,
    "frame_type": "",             # e.g. "quad_x", "tiltrotor"
    "firmware_version": "",
    "notes": "",
}
