"""Tests for uLog parser and coordinate transforms."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from tailor.parser.coordinate import (
    CoordinateTransformer,
    TailSitterCoordinateManager,
    CoordFrame,
    quat_to_rotation,
    euler_to_rotation,
)


class TestQuaternionConversions:
    def test_identity_quaternion(self):
        """Identity quaternion [1,0,0,0] should produce no rotation."""
        R = quat_to_rotation(np.array([1.0, 0.0, 0.0, 0.0]))
        vec = R.apply([1.0, 0.0, 0.0])
        np.testing.assert_allclose(vec, [1.0, 0.0, 0.0], atol=1e-10)

    def test_90deg_yaw(self):
        """90-degree yaw rotation: x -> y, y -> -x."""
        q = np.array([np.cos(np.pi / 4), 0, 0, np.sin(np.pi / 4)])
        R = quat_to_rotation(q)
        vec = R.apply([1.0, 0.0, 0.0])
        np.testing.assert_allclose(vec, [0.0, 1.0, 0.0], atol=1e-10)

    def test_euler_roundtrip(self):
        """Euler -> quat -> euler should roundtrip."""
        roll, pitch, yaw = 0.3, 0.2, 1.5
        R = euler_to_rotation(roll, pitch, yaw)
        q = R.as_quat()  # [x, y, z, w]
        q_pxyz = np.array([q[3], q[0], q[1], q[2]])  # [w, x, y, z]
        R2 = quat_to_rotation(q_pxyz)
        euler_back = R2.as_euler('ZYX')
        np.testing.assert_allclose(
            [euler_back[2], euler_back[1], euler_back[0]],
            [roll, pitch, yaw],
            atol=1e-10,
        )


class TestCoordinateTransformer:
    def test_frd_to_ned_identity(self):
        """Identity rotation: FRD = NED."""
        q_identity = np.array([1.0, 0.0, 0.0, 0.0])
        vec_frd = np.array([1.0, 2.0, 3.0])
        vec_ned = CoordinateTransformer.frd_to_ned(vec_frd, q_identity)
        np.testing.assert_allclose(vec_ned, vec_frd, atol=1e-10)

    def test_frd_to_ned_90deg_pitch(self):
        """90-deg pitch up: FRD x (forward) -> NED z (down)."""
        # 90 deg pitch: nose points up
        q = np.array([np.cos(np.pi / 4), 0, np.sin(np.pi / 4), 0])
        vec_frd = np.array([1.0, 0.0, 0.0])
        vec_ned = CoordinateTransformer.frd_to_ned(vec_frd, q)
        # After 90-deg pitch, forward becomes down in NED
        np.testing.assert_allclose(vec_ned[2], 1.0, atol=1e-10)

    def test_ned_to_enu(self):
        """NED [1,0,0] -> ENU [0,1,0]. N->E, E->N, D->-U."""
        vec_ned = np.array([1.0, 0.0, 0.0])
        vec_enu = CoordinateTransformer.ned_to_enu(vec_ned)
        np.testing.assert_allclose(vec_enu, [0.0, 1.0, 0.0], atol=1e-10)

    def test_ned_enu_roundtrip(self):
        """NED -> ENU -> NED should roundtrip."""
        vec = np.array([3.0, -2.0, 5.0])
        vec_enu = CoordinateTransformer.ned_to_enu(vec)
        vec_back = CoordinateTransformer.enu_to_ned(vec_enu)
        np.testing.assert_allclose(vec_back, vec, atol=1e-10)

    def test_batch_transform(self):
        """Transform a batch of vectors."""
        q_identity = np.array([1.0, 0.0, 0.0, 0.0])
        vecs = np.random.randn(10, 3)
        result = CoordinateTransformer.frd_to_ned(vecs, q_identity)
        np.testing.assert_allclose(result, vecs, atol=1e-10)

    def test_aoa_sideslip(self):
        """AoA and sideslip for pure forward flight."""
        v_frd = np.array([10.0, 0.0, 0.0])
        alpha, beta = CoordinateTransformer.compute_aoa_sideslip(v_frd)
        np.testing.assert_allclose(alpha, 0.0, atol=1e-10)
        np.testing.assert_allclose(beta, 0.0, atol=1e-10)

    def test_aoa_positive(self):
        """AoA should be positive when nose is pitched up (negative vz in FRD)."""
        v_frd = np.array([10.0, 0.0, -5.0])
        alpha, _ = CoordinateTransformer.compute_aoa_sideslip(v_frd)
        assert alpha > 0


class TestTailSitterCoordinateManager:
    def test_hover_thrust_vertical(self):
        """In hover mode with identity attitude, thrust vertical view should negate z."""
        mgr = TailSitterCoordinateManager()
        q_identity = np.array([1.0, 0.0, 0.0, 0.0])
        vec_frd = np.array([0.0, 0.0, -10.0])  # 10 m/s^2 downward in body
        result = mgr.transform_for_mode(
            vec_frd, q_identity, "multirotor",
            target_frame=CoordFrame.THRUST_VERT,
        )
        # In thrust vertical view, down becomes up
        np.testing.assert_allclose(result, [0.0, 0.0, 10.0], atol=1e-10)

    def test_fixedwing_standard_frd(self):
        """In fixed-wing mode, thrust vertical view should return FRD as-is."""
        mgr = TailSitterCoordinateManager()
        q_identity = np.array([1.0, 0.0, 0.0, 0.0])
        vec_frd = np.array([1.0, 2.0, 3.0])
        result = mgr.transform_for_mode(
            vec_frd, q_identity, "fixedwing",
            target_frame=CoordFrame.THRUST_VERT,
        )
        np.testing.assert_allclose(result, vec_frd, atol=1e-10)

    def test_transition_blend(self):
        """Transition should blend between multirotor and fixed-wing views."""
        mgr = TailSitterCoordinateManager()
        q_identity = np.array([1.0, 0.0, 0.0, 0.0])
        vec_frd = np.array([0.0, 0.0, -10.0])

        result_0 = mgr.transform_for_mode(
            vec_frd, q_identity, "transition", alpha_blend=0.0,
            target_frame=CoordFrame.THRUST_VERT,
        )
        result_1 = mgr.transform_for_mode(
            vec_frd, q_identity, "transition", alpha_blend=1.0,
            target_frame=CoordFrame.THRUST_VERT,
        )
        result_half = mgr.transform_for_mode(
            vec_frd, q_identity, "transition", alpha_blend=0.5,
            target_frame=CoordFrame.THRUST_VERT,
        )

        # alpha=0 should match multirotor view
        np.testing.assert_allclose(result_0, [0.0, 0.0, 10.0], atol=1e-10)
        # alpha=1 should match fixed-wing view (FRD)
        np.testing.assert_allclose(result_1, vec_frd, atol=1e-10)
        # alpha=0.5 should be the midpoint
        np.testing.assert_allclose(result_half, 0.5 * (result_0 + result_1), atol=1e-10)

    def test_airspeed_blend_factor(self):
        """Blend factor should linearly interpolate with airspeed."""
        mgr = TailSitterCoordinateManager()
        assert mgr.get_mode_blend_factor(0.0) == 0.0
        assert mgr.get_mode_blend_factor(3.0) == 0.0
        assert mgr.get_mode_blend_factor(10.0) == 0.5
        assert mgr.get_mode_blend_factor(20.0) == 1.0
