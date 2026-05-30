"""Coordinate system management for tail-sitter / VTOL analysis.

Handles transformations between body (FRD), world (NED/ENU), wind, and
mode-specific reference frames used in tail-sitter flight analysis.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

import numpy as np
from scipy.spatial.transform import Rotation


class CoordFrame(Enum):
    """Supported coordinate frames."""
    FRD = "frd"                       # Front-Right-Down (PX4 body)
    FLU = "flu"                       # Front-Left-Up
    NED = "ned"                       # North-East-Down (world)
    ENU = "enu"                       # East-North-Up (world)
    WIND = "wind"                     # Wind axis (stability)
    THRUST_VERT = "thrust_vertical"   # Tail-sitter hover mode


def quat_to_rotation(q: np.ndarray) -> Rotation:
    """Convert PX4 quaternion [qw, qx, qy, qz] to scipy Rotation.

    PX4 stores quaternions as [w, x, y, z] but scipy expects [x, y, z, w].
    """
    q = np.asarray(q)
    if q.ndim == 1:
        q_wxyz = q
    else:
        q_wxyz = q
    # Reorder to scipy convention [x, y, z, w]
    return Rotation.from_quat([q_wxyz[1], q_wxyz[2], q_wxyz[3], q_wxyz[0]])


def euler_to_rotation(roll: float, pitch: float, yaw: float) -> Rotation:
    """Convert Euler angles (rad) to Rotation. ZYX intrinsic order (aerospace)."""
    return Rotation.from_euler('ZYX', [yaw, pitch, roll])


class CoordinateTransformer:
    """Transform vectors between coordinate frames."""

    @staticmethod
    def frd_to_ned(vec_frd: np.ndarray, quat_frd_to_ned: np.ndarray) -> np.ndarray:
        """Transform a vector from FRD body frame to NED world frame.

        Args:
            vec_frd: Vector in FRD frame, shape (3,) or (N, 3).
            quat_frd_to_ned: Quaternion [qw, qx, qy, qz] representing body-to-world.

        Returns:
            Vector in NED frame.
        """
        R = quat_to_rotation(quat_frd_to_ned)
        return R.apply(vec_frd)

    @staticmethod
    def ned_to_frd(vec_ned: np.ndarray, quat_frd_to_ned: np.ndarray) -> np.ndarray:
        """Transform a vector from NED world frame to FRD body frame."""
        R = quat_to_rotation(quat_frd_to_ned)
        return R.inv().apply(vec_ned)

    @staticmethod
    def ned_to_enu(vec_ned: np.ndarray) -> np.ndarray:
        """Transform from NED to ENU (swap axes: N->E, E->N, D->U)."""
        vec_ned = np.asarray(vec_ned)
        if vec_ned.ndim == 1:
            return np.array([vec_ned[1], vec_ned[0], -vec_ned[2]])
        return np.column_stack([vec_ned[:, 1], vec_ned[:, 0], -vec_ned[:, 2]])

    @staticmethod
    def enu_to_ned(vec_enu: np.ndarray) -> np.ndarray:
        """Transform from ENU to NED."""
        vec_enu = np.asarray(vec_enu)
        if vec_enu.ndim == 1:
            return np.array([vec_enu[1], vec_enu[0], -vec_enu[2]])
        return np.column_stack([vec_enu[:, 1], vec_enu[:, 0], -vec_enu[:, 2]])

    @staticmethod
    def quat_to_euler_deg(quat: np.ndarray) -> np.ndarray:
        """Convert quaternion to Euler angles in degrees [roll, pitch, yaw]."""
        R = quat_to_rotation(quat)
        # ZYX intrinsic: yaw, pitch, roll
        euler = R.as_euler('ZYX', degrees=True)
        if euler.ndim == 1:
            return np.array([euler[2], euler[1], euler[0]])  # roll, pitch, yaw
        return np.column_stack([euler[:, 2], euler[:, 1], euler[:, 0]])

    @staticmethod
    def quat_to_euler_rad(quat: np.ndarray) -> np.ndarray:
        """Convert quaternion to Euler angles in radians [roll, pitch, yaw]."""
        R = quat_to_rotation(quat)
        euler = R.as_euler('ZYX', degrees=False)
        if euler.ndim == 1:
            return np.array([euler[2], euler[1], euler[0]])
        return np.column_stack([euler[:, 2], euler[:, 1], euler[:, 0]])

    @staticmethod
    def compute_aoa_sideslip(
        velocity_frd: np.ndarray,
        airspeed: float | None = None,
    ) -> tuple[float, float]:
        """Compute angle of attack (alpha) and sideslip (beta) from FRD velocity.

        alpha = atan2(-vz, vx)  (FRD: x forward, z down)
        beta  = atan2(vy, sqrt(vx^2 + vz^2))
        """
        v = np.asarray(velocity_frd)
        vx, vy, vz = v[0], v[1], v[2]
        alpha = np.arctan2(-vz, vx)
        beta = np.arctan2(vy, np.sqrt(vx**2 + vz**2))
        return float(alpha), float(beta)


class TailSitterCoordinateManager:
    """Mode-aware coordinate system manager for tail-sitter vehicles.

    In multirotor hover mode, remaps body axes so thrust direction is "up"
    in the analysis view. In fixed-wing mode, uses standard FRD.
    During transition, provides interpolated or dual-view data.
    """

    def __init__(self):
        self.transformer = CoordinateTransformer()

    def transform_for_mode(
        self,
        vec_frd: np.ndarray,
        quat_frd_to_ned: np.ndarray,
        flight_mode: str,
        alpha_blend: float = 0.0,
        target_frame: CoordFrame = CoordFrame.THRUST_VERT,
    ) -> np.ndarray:
        """Transform a body-frame vector based on flight mode.

        Args:
            vec_frd: Vector in FRD body frame, shape (3,) or (N, 3).
            quat_frd_to_ned: Quaternion(s) for body-to-world rotation.
            flight_mode: 'multirotor', 'fixedwing', or 'transition'.
            alpha_blend: Blend factor for transition (0=multirotor, 1=fixedwing).
            target_frame: Desired output frame.

        Returns:
            Transformed vector.
        """
        if target_frame == CoordFrame.FRD:
            return vec_frd

        if target_frame == CoordFrame.NED:
            return self.transformer.frd_to_ned(vec_frd, quat_frd_to_ned)

        if target_frame == CoordFrame.ENU:
            ned = self.transformer.frd_to_ned(vec_frd, quat_frd_to_ned)
            return self.transformer.ned_to_enu(ned)

        if target_frame == CoordFrame.THRUST_VERT:
            if flight_mode == "multirotor":
                return self._thrust_vertical_view(vec_frd, quat_frd_to_ned)
            elif flight_mode == "fixedwing":
                return vec_frd  # Standard FRD
            else:  # transition
                vec_tv = self._thrust_vertical_view(vec_frd, quat_frd_to_ned)
                return (1 - alpha_blend) * vec_tv + alpha_blend * vec_frd

        return vec_frd

    def _thrust_vertical_view(
        self,
        vec_frd: np.ndarray,
        quat_frd_to_ned: np.ndarray,
    ) -> np.ndarray:
        """Remap FRD so that the thrust direction is vertical (NED z-axis).

        For tail-sitter hover: the body z-axis (down) becomes the thrust direction.
        We rotate the body frame so that body-z aligns with world-down (NED),
        keeping the nose direction.
        """
        vec_frd = np.asarray(vec_frd)
        R = quat_to_rotation(quat_frd_to_ned)

        # Transform to NED
        vec_ned = R.apply(vec_frd)

        # In hover, we want to display with "up" being thrust direction.
        # Standard NED has z-down, so negate z for intuitive display.
        # This gives: x=north (forward), y=east (right), z=up (thrust)
        if vec_ned.ndim == 1:
            return np.array([vec_ned[0], vec_ned[1], -vec_ned[2]])
        return np.column_stack([vec_ned[:, 0], vec_ned[:, 1], -vec_ned[:, 2]])

    def get_mode_blend_factor(
        self,
        airspeed: float,
        transition_airspeed_start: float = 5.0,
        transition_airspeed_end: float = 15.0,
    ) -> float:
        """Compute blend factor based on airspeed for transition mode.

        Returns 0.0 at low airspeed (multirotor view), 1.0 at high airspeed (fixedwing view).
        """
        if airspeed <= transition_airspeed_start:
            return 0.0
        if airspeed >= transition_airspeed_end:
            return 1.0
        return (airspeed - transition_airspeed_start) / (transition_airspeed_end - transition_airspeed_start)
