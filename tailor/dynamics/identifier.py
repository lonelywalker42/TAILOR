"""System identification core — ARX, OE, subspace, and frequency-domain methods.

All methods operate on uniformly-sampled input/output data and return
TransferFunctionModel objects that can be validated, compared, and stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
from scipy import signal as sp_signal
from scipy.optimize import minimize

try:
    import control
    HAS_CONTROL = True
except ImportError:
    HAS_CONTROL = False


class IdentificationMethod(Enum):
    ARX = "arx"
    OE = "oe"           # Output-Error
    SUBSPACE = "subspace"
    FREQUENCY = "frequency"  # Frequency-domain fit


@dataclass
class TransferFunctionModel:
    """Identified transfer function model."""
    num: np.ndarray           # Numerator coefficients
    den: np.ndarray           # Denominator coefficients
    dt: float                 # Sample time (s)
    method: IdentificationMethod
    input_channel: str = ""
    output_channel: str = ""
    input_label: str = ""
    output_label: str = ""
    order_num: int = 0        # Numerator order
    order_den: int = 0        # Denominator order
    delay: int = 0            # Input delay (samples)
    fit_percent: float = 0.0  # VAF %
    aic: float = 0.0          # Akaike Information Criterion
    bic: float = 0.0          # Bayesian Information Criterion
    residual_whiteness: float = 0.0  # Ljung-Box p-value
    metadata: dict = field(default_factory=dict)

    @property
    def continuous_num(self):
        """Convert to continuous-time numerator (if dt > 0)."""
        if self.dt > 0:
            sys = sp_signal.dlti(self.num, self.den, dt=self.dt)
            sys_c = sp_signal.cont2discrete(
                sp_signal.dlti(self.num, self.den, dt=self.dt).to_ss().__dict__.get('A', None),
                dt=self.dt,
            )
        return self.num

    @property
    def continuous_den(self):
        return self.den

    def to_control_tf(self):
        """Convert to python-control TransferFunction object."""
        if not HAS_CONTROL:
            raise ImportError("python-control package required")
        return control.TransferFunction(
            self.num.tolist(), self.den.tolist(), self.dt
        )

    def to_scipy_dlti(self):
        """Convert to scipy discrete-time LTI system."""
        return sp_signal.dlti(self.num, self.den, dt=self.dt)

    def simulate(self, u: np.ndarray, t: Optional[np.ndarray] = None) -> np.ndarray:
        """Simulate the model response to input u."""
        sys = self.to_scipy_dlti()
        if t is None:
            t = np.arange(len(u)) * self.dt
        result = sp_signal.dlsim(sys, u, t=t)
        # scipy >= 1.12 returns (tout, yout), older returns (tout, yout, xout)
        return result[1].flatten()

    def get_poles(self) -> np.ndarray:
        """Get system poles."""
        return np.roots(self.den)

    def get_zeros(self) -> np.ndarray:
        """Get system zeros."""
        return np.roots(self.num)

    def is_stable(self) -> bool:
        """Check if all poles are inside the unit circle."""
        poles = self.get_poles()
        return bool(np.all(np.abs(poles) < 1.0))

    def to_dict(self) -> dict:
        """Serialize to dict for database storage."""
        return {
            "num": self.num.tolist(),
            "den": self.den.tolist(),
            "dt": self.dt,
            "method": self.method.value,
            "input_channel": self.input_channel,
            "output_channel": self.output_channel,
            "input_label": self.input_label,
            "output_label": self.output_label,
            "order_num": self.order_num,
            "order_den": self.order_den,
            "delay": self.delay,
            "fit_percent": self.fit_percent,
            "aic": self.aic,
            "bic": self.bic,
            "residual_whiteness": self.residual_whiteness,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TransferFunctionModel:
        """Deserialize from dict."""
        return cls(
            num=np.array(d["num"]),
            den=np.array(d["den"]),
            dt=d["dt"],
            method=IdentificationMethod(d["method"]),
            input_channel=d.get("input_channel", ""),
            output_channel=d.get("output_channel", ""),
            input_label=d.get("input_label", ""),
            output_label=d.get("output_label", ""),
            order_num=d.get("order_num", 0),
            order_den=d.get("order_den", 0),
            delay=d.get("delay", 0),
            fit_percent=d.get("fit_percent", 0.0),
            aic=d.get("aic", 0.0),
            bic=d.get("bic", 0.0),
            residual_whiteness=d.get("residual_whiteness", 0.0),
            metadata=d.get("metadata", {}),
        )

    def __repr__(self):
        return (f"<TF {self.method.value} "
                f"na={self.order_den} nb={self.order_num} nk={self.delay} "
                f"fit={self.fit_percent:.1f}%>")


class SystemIdentifier:
    """Identify linear dynamic models from input/output data.

    Supports:
    - ARX (AutoRegressive with eXogenous input)
    - OE (Output-Error / equation error)
    - Frequency-domain transfer function fitting
    - Model order selection via AIC/BIC
    """

    def __init__(self):
        pass

    # ─── ARX Identification ───────────────────────────────────────────

    def identify_arx(
        self,
        u: np.ndarray,
        y: np.ndarray,
        na: int = 2,       # Denominator order
        nb: int = 2,       # Numerator order
        nk: int = 0,       # Input delay (samples)
        dt: float = 0.01,  # Sample time
        input_channel: str = "",
        output_channel: str = "",
    ) -> TransferFunctionModel:
        """Identify an ARX model: A(q) y(t) = B(q) u(t-nk) + e(t).

        Uses least-squares regression on the regressor matrix.
        """
        u = np.asarray(u).flatten()
        y = np.asarray(y).flatten()
        n = len(y)

        # Build regressor matrix
        # phi(t) = [-y(t-1), ..., -y(t-na), u(t-nk), ..., u(t-nk-nb+1)]
        n_rows = n - max(na, nb + nk)
        if n_rows <= 0:
            raise ValueError("Data too short for specified model orders")

        n_params = na + nb
        Phi = np.zeros((n_rows, n_params))
        Y = np.zeros(n_rows)

        for i in range(n_rows):
            t = i + max(na, nb + nk)
            Y[i] = y[t]
            # AR part
            for j in range(na):
                Phi[i, j] = -y[t - j - 1]
            # X part
            for j in range(nb):
                Phi[i, na + j] = u[t - nk - j]

        # Least squares
        theta, residuals, rank, sv = np.linalg.lstsq(Phi, Y, rcond=None)

        # Extract coefficients
        a_coeffs = np.concatenate([[1.0], theta[:na]])    # A(q) = 1 + a1*q^-1 + ...
        b_coeffs = theta[na:]                              # B(q) = b0 + b1*q^-1 + ...

        # Pad b if needed for proper transfer function
        # H(z) = B(z) / A(z)
        num = b_coeffs
        den = a_coeffs

        # Compute fit
        y_sim = self._simulate_arx(u, num, den, nk, n)
        fit = self._compute_fit(y, y_sim)

        # Compute information criteria
        residuals = y[max(na, nb + nk):] - y_sim[max(na, nb + nk):]
        aic_val = self._compute_aic(residuals, n_params)
        bic_val = self._compute_bic(residuals, n_params)
        whiteness = self._ljung_box_test(residuals, max(20, n_params))

        return TransferFunctionModel(
            num=num,
            den=den,
            dt=dt,
            method=IdentificationMethod.ARX,
            input_channel=input_channel,
            output_channel=output_channel,
            order_num=nb,
            order_den=na,
            delay=nk,
            fit_percent=fit,
            aic=aic_val,
            bic=bic_val,
            residual_whiteness=whiteness,
        )

    # ─── Output-Error (OE) Identification ─────────────────────────────

    def identify_oe(
        self,
        u: np.ndarray,
        y: np.ndarray,
        nf: int = 2,       # Denominator order (feedback)
        nb: int = 2,       # Numerator order
        nk: int = 0,       # Input delay
        dt: float = 0.01,
        input_channel: str = "",
        output_channel: str = "",
    ) -> TransferFunctionModel:
        """Identify an Output-Error model: y(t) = B(q)/F(q) u(t-nk) + e(t).

        Uses iterative prediction error minimization.
        """
        u = np.asarray(u).flatten()
        y = np.asarray(y).flatten()

        # Initial estimate via ARX
        arx_model = self.identify_arx(u, y, na=nf, nb=nb, nk=nk, dt=dt)

        # Use ARX as starting point for OE optimization
        # OE: y = B(q)/F(q) * u, minimize sum(e^2) where e = y - y_hat
        x0 = np.concatenate([arx_model.num[:nb], arx_model.den[1:nf + 1]])

        def oe_cost(params):
            b = params[:nb]
            f = np.concatenate([[1.0], params[nb:]])
            try:
                y_hat = self._simulate_oe(u, b, f, nk, len(y))
                e = y - y_hat
                return np.mean(e ** 2)
            except Exception:
                return 1e12

        result = minimize(oe_cost, x0, method='Nelder-Mead',
                          options={'maxiter': 2000, 'xatol': 1e-8, 'fatol': 1e-10})

        b_opt = result.x[:nb]
        f_opt = np.concatenate([[1.0], result.x[nb:]])

        y_sim = self._simulate_oe(u, b_opt, f_opt, nk, len(y))
        fit = self._compute_fit(y, y_sim)

        residuals = y - y_sim
        aic_val = self._compute_aic(residuals, len(x0))
        bic_val = self._compute_bic(residuals, len(x0))
        whiteness = self._ljung_box_test(residuals, max(20, len(x0)))

        return TransferFunctionModel(
            num=b_opt,
            den=f_opt,
            dt=dt,
            method=IdentificationMethod.OE,
            input_channel=input_channel,
            output_channel=output_channel,
            order_num=nb,
            order_den=nf,
            delay=nk,
            fit_percent=fit,
            aic=aic_val,
            bic=bic_val,
            residual_whiteness=whiteness,
        )

    # ─── Frequency-Domain Identification ──────────────────────────────

    def identify_frequency(
        self,
        u: np.ndarray,
        y: np.ndarray,
        order: int = 4,
        dt: float = 0.01,
        nperseg: int = 256,
        input_channel: str = "",
        output_channel: str = "",
    ) -> TransferFunctionModel:
        """Identify transfer function from frequency response data.

        Computes empirical transfer function estimate (ETFE) and fits
        a rational transfer function using least-squares in frequency domain.
        """
        u = np.asarray(u).flatten()
        y = np.asarray(y).flatten()
        fs = 1.0 / dt

        # Compute cross-spectral densities
        nperseg = min(nperseg, len(u) // 4, 256)
        if nperseg < 8:
            nperseg = min(len(u) // 2, 8)

        f, Pxy = sp_signal.csd(u, y, fs=fs, nperseg=nperseg)
        _, Pxx = sp_signal.welch(u, fs=fs, nperseg=nperseg)

        # ETFE = Pxy / Pxx
        valid = Pxx > 1e-10 * np.max(Pxx)
        H_est = np.zeros_like(Pxy, dtype=complex)
        H_est[valid] = Pxy[valid] / Pxx[valid]

        f_valid = f[valid]
        H_valid = H_est[valid]

        if len(f_valid) < order * 2:
            raise ValueError("Not enough frequency data for specified order")

        # Fit rational transfer function H(z) = B(z) / A(z)
        # Use the Sanathanan-Koerner iterative reweighting
        num, den = self._fit_rational_tf(f_valid, H_valid, order, fs)

        # Simulate to compute fit using dlsim for consistency
        try:
            sys = sp_signal.dlti(num, den, dt=dt)
            result = sp_signal.dlsim(sys, u)
            y_sim = result[1].flatten()
        except Exception:
            y_sim = sp_signal.lfilter(num, den, u)
        fit = self._compute_fit(y, y_sim)

        residuals = y - y_sim
        aic_val = self._compute_aic(residuals, len(num) + len(den) - 1)
        bic_val = self._compute_bic(residuals, len(num) + len(den) - 1)
        whiteness = self._ljung_box_test(residuals, max(20, order))

        return TransferFunctionModel(
            num=num,
            den=den,
            dt=dt,
            method=IdentificationMethod.FREQUENCY,
            input_channel=input_channel,
            output_channel=output_channel,
            order_num=len(num) - 1,
            order_den=len(den) - 1,
            delay=0,
            fit_percent=fit,
            aic=aic_val,
            bic=bic_val,
            residual_whiteness=whiteness,
            metadata={"nperseg": nperseg},
        )

    # ─── Model Order Selection ────────────────────────────────────────

    def auto_select_order(
        self,
        u: np.ndarray,
        y: np.ndarray,
        max_order: int = 10,
        dt: float = 0.01,
        method: IdentificationMethod = IdentificationMethod.ARX,
    ) -> tuple[int, TransferFunctionModel]:
        """Automatically select model order using BIC criterion.

        Returns:
            (best_order, best_model)
        """
        best_bic = np.inf
        best_model = None
        best_order = 1

        for order in range(1, max_order + 1):
            try:
                if method == IdentificationMethod.ARX:
                    model = self.identify_arx(u, y, na=order, nb=order, dt=dt)
                elif method == IdentificationMethod.OE:
                    model = self.identify_oe(u, y, nf=order, nb=order, dt=dt)
                else:
                    model = self.identify_frequency(u, y, order=order, dt=dt)

                if model.bic < best_bic:
                    best_bic = model.bic
                    best_model = model
                    best_order = order
            except Exception:
                continue

        if best_model is None:
            raise ValueError("Could not identify any model")

        return best_order, best_model

    # ─── Helper Methods ───────────────────────────────────────────────

    def _simulate_arx(self, u, num, den, nk, n):
        """Simulate ARX model: y(t) = -sum(a_i*y(t-i)) + sum(b_i*u(t-nk-i))."""
        na = len(den) - 1
        nb = len(num)
        y = np.zeros(n)

        for t in range(max(na, nb + nk), n):
            for i in range(na):
                y[t] -= den[i + 1] * y[t - i - 1]
            for i in range(nb):
                idx = t - nk - i
                if idx >= 0:
                    y[t] += num[i] * u[idx]

        return y

    def _simulate_oe(self, u, b, f, nk, n):
        """Simulate OE model: y(t) = B(q)/F(q) * u(t-nk)."""
        nb = len(b)
        nf = len(f) - 1
        x = np.zeros(n)  # Internal state
        y = np.zeros(n)

        for t in range(max(nf, nb + nk), n):
            # B part
            for i in range(nb):
                idx = t - nk - i
                if idx >= 0:
                    x[t] += b[i] * u[idx]
            # F part (feedback)
            for i in range(nf):
                x[t] -= f[i + 1] * x[t - i - 1]
            y[t] = x[t]

        return y

    def _fit_rational_tf(self, f, H, order, fs):
        """Fit rational TF H(z) = B(z)/A(z) to frequency response data."""
        omega = 2 * np.pi * f
        z = np.exp(1j * omega / fs)

        # Sanathanan-Koerner iteration
        num_order = order
        den_order = order

        # Initial: just fit numerator
        # Build Vandermonde-like matrix for z^-k
        n_freq = len(f)

        # Iterative reweighted least squares
        weights = np.ones(n_freq, dtype=complex)

        for iteration in range(5):
            # Build system: H * A - B = 0
            # H(z) * (1 + a1*z^-1 + ...) - (b0 + b1*z^-1 + ...) = 0
            n_params = num_order + den_order
            A_mat = np.zeros((n_freq, n_params), dtype=complex)
            b_vec = H.copy()

            for i in range(den_order):
                A_mat[:, i] = -H * z ** (-(i + 1))
            for i in range(num_order):
                A_mat[:, den_order + i] = z ** (-i)

            # Weighted least squares
            W = np.diag(weights)
            Aw = W @ A_mat
            bw = W @ b_vec

            # Solve real-valued system (split real/imag)
            A_full = np.vstack([Aw.real, Aw.imag])
            b_full = np.concatenate([bw.real, bw.imag])

            theta, _, _, _ = np.linalg.lstsq(A_full, b_full, rcond=None)

            den_coeffs = np.concatenate([[1.0], theta[:den_order]])
            num_coeffs = theta[den_order:]

            # Update weights (inverse of model magnitude)
            H_fit = np.polyval(num_coeffs[::-1], z) / np.polyval(den_coeffs[::-1], z)
            weights = 1.0 / (np.abs(H_fit) + 1e-6)

        return num_coeffs, den_coeffs

    def _compute_fit(self, y_true: np.ndarray, y_sim: np.ndarray) -> float:
        """Compute Variance Accounted For (VAF) as percentage."""
        # Align lengths
        n = min(len(y_true), len(y_sim))
        y_t = y_true[:n]
        y_s = y_sim[:n]

        ss_res = np.sum((y_t - y_s) ** 2)
        ss_tot = np.sum((y_t - np.mean(y_t)) ** 2)

        if ss_tot < 1e-15:
            return 0.0

        vaf = 100.0 * (1.0 - ss_res / ss_tot)
        return float(np.clip(vaf, 0, 100))

    def _compute_aic(self, residuals: np.ndarray, n_params: int) -> float:
        """Compute Akaike Information Criterion."""
        n = len(residuals)
        if n == 0:
            return np.inf
        ss = np.sum(residuals ** 2) / n
        if ss < 1e-30:
            return -np.inf
        return n * np.log(ss) + 2 * n_params

    def _compute_bic(self, residuals: np.ndarray, n_params: int) -> float:
        """Compute Bayesian Information Criterion."""
        n = len(residuals)
        if n == 0:
            return np.inf
        ss = np.sum(residuals ** 2) / n
        if ss < 1e-30:
            return -np.inf
        return n * np.log(ss) + n_params * np.log(n)

    def _ljung_box_test(self, residuals: np.ndarray, max_lag: int = 20) -> float:
        """Ljung-Box test for residual whiteness. Returns p-value.

        p > 0.05 suggests residuals are white (good model fit).
        """
        n = len(residuals)
        if n < max_lag + 1:
            return 0.0

        r = np.correlate(residuals, residuals, mode="full")
        r = r[n - 1:]  # Autocorrelation (unnormalized)
        r = r / r[0]   # Normalize

        # Ljung-Box statistic
        Q = 0
        for k in range(1, max_lag + 1):
            if k < len(r):
                Q += r[k] ** 2 / (n - k)

        Q *= n * (n + 2)

        # Approximate p-value using chi-squared distribution
        from scipy.stats import chi2
        p_value = 1 - chi2.cdf(Q, max_lag)

        return float(p_value)
