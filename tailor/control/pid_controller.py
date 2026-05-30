"""PID controller modeling for PX4 flight controllers.

Supports PX4 standard control structures:
- Rate loop (inner): PI with feedforward
- Attitude loop (outer): P with feedforward
- Custom user-defined structures
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
from scipy import signal as sp_signal

try:
    import control
    HAS_CONTROL = True
except ImportError:
    HAS_CONTROL = False


class ControlAxis(Enum):
    ROLL = "roll"
    PITCH = "pitch"
    YAW = "yaw"
    THROTTLE = "throttle"


class PIDStructure(Enum):
    """PX4 controller structures."""
    PI_FF = "pi_ff"           # Rate loop: Kp + Ki/s + Kff
    PID_FF = "pid_ff"         # Rate loop: Kp + Ki/s + Kd*s/(Tf*s+1) + Kff
    P = "p"                   # Attitude loop: Kp
    P_FF = "p_ff"             # Attitude loop: Kp + Kff
    CUSTOM = "custom"


@dataclass
class PIDGains:
    """PID gain parameters for a single axis."""
    kp: float = 0.0
    ki: float = 0.0
    kd: float = 0.0
    kff: float = 0.0       # Feedforward gain
    tf: float = 0.01        # Derivative filter time constant (s)
    ilimit: float = 0.0     # Integrator anti-windup limit (0 = no limit)

    def to_dict(self) -> dict:
        return {"kp": self.kp, "ki": self.ki, "kd": self.kd,
                "kff": self.kff, "tf": self.tf, "ilimit": self.ilimit}

    @classmethod
    def from_dict(cls, d: dict) -> PIDGains:
        return cls(**{k: d.get(k, 0) for k in cls.__dataclass_fields__})

    def __repr__(self):
        return (f"PIDGains(kp={self.kp:.4f}, ki={self.ki:.4f}, "
                f"kd={self.kd:.4f}, kff={self.kff:.4f})")


@dataclass
class AxisConfig:
    """Configuration for a single control axis."""
    axis: ControlAxis
    structure: PIDStructure
    gains: PIDGains
    label: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = f"{self.axis.value}_{self.structure.value}"


@dataclass
class ControllerParams:
    """Complete PID parameter set for all axes."""
    axes: dict[str, AxisConfig] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    @property
    def roll(self) -> Optional[AxisConfig]:
        return self.axes.get(ControlAxis.ROLL.value)

    @property
    def pitch(self) -> Optional[AxisConfig]:
        return self.axes.get(ControlAxis.PITCH.value)

    @property
    def yaw(self) -> Optional[AxisConfig]:
        return self.axes.get(ControlAxis.YAW.value)

    def to_dict(self) -> dict:
        return {
            "axes": {k: {"axis": v.axis.value, "structure": v.structure.value,
                         "gains": v.gains.to_dict(), "label": v.label}
                     for k, v in self.axes.items()},
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ControllerParams:
        axes = {}
        for k, v in d.get("axes", {}).items():
            axes[k] = AxisConfig(
                axis=ControlAxis(v["axis"]),
                structure=PIDStructure(v["structure"]),
                gains=PIDGains.from_dict(v["gains"]),
                label=v.get("label", ""),
            )
        return cls(axes=axes, metadata=d.get("metadata", {}))

    def to_px4_params(self) -> dict[str, float]:
        """Export as PX4 parameter names and values."""
        params = {}
        axis_map = {
            ControlAxis.ROLL: "MC_ROLL",
            ControlAxis.PITCH: "MC_PITCH",
            ControlAxis.YAW: "MC_YAW",
        }
        for axis_name, cfg in self.axes.items():
            prefix = axis_map.get(cfg.axis, f"MC_{axis_name.upper()}")
            if cfg.structure in (PIDStructure.PI_FF, PIDStructure.PID_FF):
                params[f"{prefix}_P"] = cfg.gains.kp
                params[f"{prefix}_I"] = cfg.gains.ki
                params[f"{prefix}_D"] = cfg.gains.kd
                params[f"{prefix}_FF"] = cfg.gains.kff
            elif cfg.structure in (PIDStructure.P, PIDStructure.P_FF):
                params[f"{prefix}_P"] = cfg.gains.kp
                params[f"{prefix}_FF"] = cfg.gains.kff
        return params


class PIDController:
    """PID controller model with PX4-compatible structure.

    Supports continuous-time and discrete-time transfer function computation,
    closed-loop simulation, and performance evaluation.
    """

    def __init__(self, structure: PIDStructure = PIDStructure.PI_FF):
        self.structure = structure

    def get_open_loop_tf(
        self,
        gains: PIDGains,
        plant_tf: Optional[tuple[np.ndarray, np.ndarray]] = None,
        dt: float = 0.0,
    ):
        """Compute the open-loop transfer function C(s)*G(s).

        Args:
            gains: PID gains.
            plant_tf: (num, den) of the plant. If None, returns controller TF only.
            dt: Sample time. 0 = continuous.

        Returns:
            (num, den) of the open-loop TF, or control.TransferFunction if available.
        """
        # Build controller TF
        ctrl_num, ctrl_den = self._controller_tf(gains)

        if plant_tf is not None:
            p_num, p_den = plant_tf
            # Multiply: C(s) * G(s)
            ol_num = np.convolve(ctrl_num, p_num)
            ol_den = np.convolve(ctrl_den, p_den)
        else:
            ol_num = ctrl_num
            ol_den = ctrl_den

        if HAS_CONTROL and dt > 0:
            sys_c = control.TransferFunction(ol_num, ol_den)
            sys_d = control.sample_system(sys_c, dt, method='zoh')
            return sys_d
        elif HAS_CONTROL:
            return control.TransferFunction(ol_num, ol_den)
        else:
            return ol_num, ol_den

    def get_closed_loop_tf(
        self,
        gains: PIDGains,
        plant_tf: tuple[np.ndarray, np.ndarray],
        dt: float = 0.0,
    ):
        """Compute the closed-loop transfer function T = CG / (1 + CG).

        Args:
            gains: PID gains.
            plant_tf: (num, den) of the plant.
            dt: Sample time.

        Returns:
            Closed-loop TF.
        """
        ctrl_num, ctrl_den = self._controller_tf(gains)
        p_num, p_den = plant_tf

        # CG
        cg_num = np.convolve(ctrl_num, p_num)
        cg_den = np.convolve(ctrl_den, p_den)

        # 1 + CG
        # Pad cg_den to match length of cg_num + cg_den
        cl_den = np.polyadd(cg_den, cg_num)
        cl_num = cg_num

        if HAS_CONTROL:
            return control.TransferFunction(cl_num, cl_den)
        return cl_num, cl_den

    def simulate_closed_loop(
        self,
        gains: PIDGains,
        plant_tf: tuple[np.ndarray, np.ndarray],
        reference: np.ndarray,
        dt: float = 0.01,
        t: Optional[np.ndarray] = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Simulate closed-loop step response.

        Returns:
            (t, y, u) — time, output, control effort.
        """
        ctrl_num, ctrl_den = self._controller_tf(gains)
        p_num, p_den = plant_tf

        n = len(reference)
        if t is None:
            t = np.arange(n) * dt

        # Open-loop TF
        ol_num = np.convolve(ctrl_num, p_num)
        ol_den = np.convolve(ctrl_den, p_den)

        # Closed-loop: T = CG / (1 + CG)
        cl_den = np.polyadd(ol_den, ol_num)
        cl_num = ol_num

        # Simulate
        sys = sp_signal.dlti(cl_num, cl_den, dt=dt)
        result = sp_signal.dlsim(sys, reference, t=t)
        y = result[1].flatten()

        # Control effort: u = C * (r - y)
        error = reference - y
        ctrl_sys = sp_signal.dlti(ctrl_num, ctrl_den, dt=dt)
        result_ctrl = sp_signal.dlsim(ctrl_sys, error, t=t)
        u = result_ctrl[1].flatten()

        return t, y, u

    def evaluate_performance(
        self,
        gains: PIDGains,
        plant_tf: tuple[np.ndarray, np.ndarray],
        dt: float = 0.01,
    ) -> dict:
        """Evaluate controller performance metrics.

        Returns:
            Dict with step response and frequency domain metrics.
        """
        from tailor.dynamics.validation import ModelValidator

        # Get closed-loop TF
        ctrl_num, ctrl_den = self._controller_tf(gains)
        p_num, p_den = plant_tf

        ol_num = np.convolve(ctrl_num, p_num)
        ol_den = np.convolve(ctrl_den, p_den)
        cl_den = np.polyadd(ol_den, ol_num)
        cl_num = ol_num

        # Create model for validation
        from tailor.dynamics.identifier import TransferFunctionModel, IdentificationMethod
        model = TransferFunctionModel(
            num=cl_num, den=cl_den, dt=dt,
            method=IdentificationMethod.ARX,
        )

        sm = ModelValidator.step_response_metrics(model)
        fm = ModelValidator.frequency_metrics(model)

        return {
            "rise_time_s": sm.rise_time_s,
            "overshoot_pct": sm.overshoot_pct,
            "settling_time_s": sm.settling_time_s,
            "steady_state_error": sm.steady_state_error,
            "bandwidth_hz": fm.bandwidth_hz,
            "phase_margin_deg": fm.phase_margin_deg,
            "gain_margin_db": fm.gain_margin_db,
            "peak_gain_db": fm.peak_gain_db,
            "dc_gain": sm.dc_gain,
            "is_stable": model.is_stable(),
        }

    def _controller_tf(self, gains: PIDGains) -> tuple[np.ndarray, np.ndarray]:
        """Compute controller transfer function (num, den) in s-domain.

        PI+FF: C(s) = Kp + Ki/s + Kff = (Kp*s + Ki + Kff*s^2) / s
        PID+FF: C(s) = Kp + Ki/s + Kd*s/(Tf*s+1) + Kff
        P: C(s) = Kp
        P+FF: C(s) = Kp + Kff*s
        """
        if self.structure == PIDStructure.PI_FF:
            # C(s) = (Kff*s^2 + Kp*s + Ki) / s
            num = np.array([gains.kff, gains.kp, gains.ki])
            den = np.array([1.0, 0.0])

        elif self.structure == PIDStructure.PID_FF:
            # C(s) = Kp + Ki/s + Kd*s/(Tf*s+1) + Kff
            # = [Kp*s*(Tf*s+1) + Ki*(Tf*s+1) + Kd*s^2 + Kff*s*(Tf*s+1)] / [s*(Tf*s+1)]
            tf = max(gains.tf, 1e-6)
            num = np.array([
                gains.kff * tf + gains.kp * tf + gains.kd,
                gains.kff + gains.kp + gains.ki * tf,
                gains.ki,
            ])
            den = np.array([tf, 1.0, 0.0])

        elif self.structure == PIDStructure.P:
            num = np.array([gains.kp])
            den = np.array([1.0])

        elif self.structure == PIDStructure.P_FF:
            # C(s) = Kp + Kff*s
            num = np.array([gains.kff, gains.kp])
            den = np.array([1.0])

        else:
            num = np.array([gains.kp, gains.ki])
            den = np.array([1.0, 0.0])

        return num, den


# ─── PX4 Parameter Extraction ──────────────────────────────────────────

PX4_RATE_PARAM_MAP = {
    "MC_ROLLRATE_P": ("roll", "kp"),
    "MC_ROLLRATE_I": ("roll", "ki"),
    "MC_ROLLRATE_D": ("roll", "kd"),
    "MC_ROLLRATE_FF": ("roll", "kff"),
    "MC_PITCHRATE_P": ("pitch", "kp"),
    "MC_PITCHRATE_I": ("pitch", "ki"),
    "MC_PITCHRATE_D": ("pitch", "kd"),
    "MC_PITCHRATE_FF": ("pitch", "kff"),
    "MC_YAWRATE_P": ("yaw", "kp"),
    "MC_YAWRATE_I": ("yaw", "ki"),
    "MC_YAWRATE_D": ("yaw", "kd"),
    "MC_YAWRATE_FF": ("yaw", "kff"),
}

PX4_ATTITUDE_PARAM_MAP = {
    "MC_ROLL_P": ("roll", "kp"),
    "MC_ROLL_FF": ("roll", "kff"),
    "MC_PITCH_P": ("pitch", "kp"),
    "MC_PITCH_FF": ("pitch", "kff"),
    "MC_YAW_P": ("yaw", "kp"),
    "MC_YAW_FF": ("yaw", "kff"),
}


def extract_px4_params(param_dict: dict[str, float]) -> ControllerParams:
    """Extract PID parameters from PX4 parameter dictionary.

    Args:
        param_dict: Dict of PX4 parameter name -> value.

    Returns:
        ControllerParams with rate loop configuration.
    """
    axes = {}

    for px4_name, (axis, gain_key) in PX4_RATE_PARAM_MAP.items():
        if px4_name in param_dict:
            if axis not in axes:
                axes[axis] = AxisConfig(
                    axis=ControlAxis(axis.upper()),
                    structure=PIDStructure.PI_FF,
                    gains=PIDGains(),
                )
            setattr(axes[axis].gains, gain_key, param_dict[px4_name])

    return ControllerParams(axes=axes)


def default_rate_gains(axis: ControlAxis = ControlAxis.ROLL) -> AxisConfig:
    """Create default rate loop gains (typical PX4 values)."""
    defaults = {
        ControlAxis.ROLL: PIDGains(kp=0.15, ki=0.2, kd=0.003, kff=0.0),
        ControlAxis.PITCH: PIDGains(kp=0.15, ki=0.2, kd=0.003, kff=0.0),
        ControlAxis.YAW: PIDGains(kp=0.2, ki=0.1, kd=0.0, kff=0.0),
    }
    return AxisConfig(
        axis=axis,
        structure=PIDStructure.PID_FF,
        gains=defaults.get(axis, PIDGains()),
    )
