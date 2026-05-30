"""Model validation and dynamic performance metrics.

Provides tools for validating identified models against measured data,
computing time-domain and frequency-domain performance indicators,
and comparing multiple models.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import signal as sp_signal

try:
    import control
    HAS_CONTROL = True
except ImportError:
    HAS_CONTROL = False

from tailor.dynamics.identifier import TransferFunctionModel


@dataclass
class StepResponseMetrics:
    """Time-domain step response performance metrics."""
    rise_time_s: float = 0.0          # 10%-90% rise time
    peak_time_s: float = 0.0          # Time to first peak
    overshoot_pct: float = 0.0        # Peak overshoot %
    settling_time_s: float = 0.0      # 2% settling time
    steady_state_value: float = 0.0   # Final value
    steady_state_error: float = 0.0   # |1 - steady_state| for unit step
    peak_value: float = 0.0           # Maximum value
    dc_gain: float = 0.0              # DC gain of the system

    def __repr__(self):
        return (f"<StepMetrics tr={self.rise_time_s:.3f}s "
                f"OS={self.overshoot_pct:.1f}% "
                f"ts={self.settling_time_s:.3f}s>")


@dataclass
class FrequencyMetrics:
    """Frequency-domain performance metrics."""
    bandwidth_hz: float = 0.0         # -3dB bandwidth
    gain_margin_db: float = 0.0       # Gain margin
    gain_margin_freq_hz: float = 0.0  # Frequency at gain margin
    phase_margin_deg: float = 0.0     # Phase margin
    phase_margin_freq_hz: float = 0.0 # Frequency at phase margin (crossover)
    dc_gain_db: float = 0.0           # DC gain in dB
    peak_gain_db: float = 0.0         # Resonance peak gain
    peak_freq_hz: float = 0.0         # Resonance frequency

    def __repr__(self):
        return (f"<FreqMetrics bw={self.bandwidth_hz:.2f}Hz "
                f"PM={self.phase_margin_deg:.1f}deg "
                f"GM={self.gain_margin_db:.1f}dB>")


@dataclass
class ModelComparison:
    """Comparison of multiple models."""
    models: list[TransferFunctionModel]
    step_metrics: list[StepResponseMetrics]
    freq_metrics: list[FrequencyMetrics]
    fit_percents: list[float]
    best_index: int = -1              # Index of best overall model
    ranking_criteria: str = "bic"     # How models were ranked


class ModelValidator:
    """Validate identified models and compute performance metrics."""

    # ─── Step Response Analysis ───────────────────────────────────────

    @staticmethod
    def step_response_metrics(
        model: TransferFunctionModel,
        t_duration: float = 5.0,
        threshold_settling: float = 0.02,
    ) -> StepResponseMetrics:
        """Compute step response metrics for a discrete-time model.

        Args:
            model: Identified transfer function model.
            t_duration: Simulation duration in seconds.
            threshold_settling: Settling threshold (fraction, default 2%).

        Returns:
            StepResponseMetrics with all time-domain indicators.
        """
        dt = model.dt
        if dt <= 0:
            dt = 0.01
        n_steps = int(t_duration / dt)
        u = np.ones(n_steps)  # Unit step

        t = np.arange(n_steps) * dt
        y = model.simulate(u, t)

        metrics = StepResponseMetrics()

        # DC gain
        metrics.dc_gain = float(y[-1]) if len(y) > 0 else 0.0
        metrics.steady_state_value = metrics.dc_gain
        metrics.steady_state_error = abs(1.0 - metrics.dc_gain) if metrics.dc_gain != 0 else 0.0

        # Peak value and time
        if len(y) > 0:
            peak_idx = np.argmax(np.abs(y))
            metrics.peak_value = float(y[peak_idx])
            metrics.peak_time_s = float(t[peak_idx])

            # Overshoot (only if system overshoots)
            if metrics.dc_gain > 0:
                overshoot = (metrics.peak_value - metrics.dc_gain) / metrics.dc_gain
                metrics.overshoot_pct = float(max(0, overshoot) * 100)
            elif metrics.dc_gain < 0:
                overshoot = (metrics.peak_value - metrics.dc_gain) / abs(metrics.dc_gain)
                metrics.overshoot_pct = float(max(0, overshoot) * 100)

        # Rise time (10% to 90% of final value)
        if metrics.dc_gain != 0:
            target_10 = 0.1 * metrics.dc_gain
            target_90 = 0.9 * metrics.dc_gain
        else:
            target_10 = 0.1
            target_90 = 0.9

        idx_10 = np.where(y >= target_10)[0]
        idx_90 = np.where(y >= target_90)[0]

        if len(idx_10) > 0 and len(idx_90) > 0:
            metrics.rise_time_s = float(t[idx_90[0]] - t[idx_10[0]])

        # Settling time (2% band)
        if metrics.dc_gain != 0:
            band = threshold_settling * abs(metrics.dc_gain)
        else:
            band = threshold_settling

        # Find last time outside the band
        outside_band = np.abs(y - metrics.dc_gain) > band
        if np.any(outside_band):
            last_outside = np.where(outside_band)[0][-1]
            metrics.settling_time_s = float(t[min(last_outside + 1, len(t) - 1)])
        else:
            metrics.settling_time_s = 0.0

        return metrics

    # ─── Frequency Response Analysis ──────────────────────────────────

    @staticmethod
    def frequency_metrics(model: TransferFunctionModel) -> FrequencyMetrics:
        """Compute frequency-domain metrics for a discrete-time model.

        Args:
            model: Identified transfer function model.

        Returns:
            FrequencyMetrics with bandwidth, margins, etc.
        """
        metrics = FrequencyMetrics()

        dt = model.dt
        if dt <= 0:
            dt = 0.01
        fs = 1.0 / dt

        # Compute frequency response
        n_points = 2048
        w = np.logspace(-2, np.log10(fs / 2 * 2 * np.pi), n_points)

        try:
            w_resp, h = sp_signal.dfreqresp(
                (model.num, model.den, dt), w=w
            )
        except Exception:
            # Fallback: use bode
            try:
                sys = sp_signal.dlti(model.num, model.den, dt=dt)
                w_resp, h = sp_signal.dfreqresp(sys, w=w)
            except Exception:
                return metrics

        freq_hz = w_resp / (2 * np.pi)
        mag_db = 20 * np.log10(np.abs(h) + 1e-20)
        phase_deg = np.degrees(np.angle(h))

        # DC gain
        metrics.dc_gain_db = float(mag_db[0])

        # Peak gain (resonance)
        peak_idx = np.argmax(mag_db)
        metrics.peak_gain_db = float(mag_db[peak_idx])
        metrics.peak_freq_hz = float(freq_hz[peak_idx])

        # Bandwidth (-3dB from DC)
        dc_level = mag_db[0]
        bw_threshold = dc_level - 3.0
        below_bw = mag_db < bw_threshold
        if np.any(below_bw):
            bw_idx = np.where(below_bw)[0][0]
            metrics.bandwidth_hz = float(freq_hz[bw_idx])
        else:
            metrics.bandwidth_hz = float(freq_hz[-1])

        # Gain margin: gain at phase crossover (phase = -180°)
        phase_crossover = np.where(phase_deg <= -180)[0]
        if len(phase_crossover) > 0:
            gm_idx = phase_crossover[0]
            metrics.gain_margin_db = float(-mag_db[gm_idx])
            metrics.gain_margin_freq_hz = float(freq_hz[gm_idx])
        else:
            metrics.gain_margin_db = 60.0  # Effectively infinite

        # Phase margin: phase at gain crossover (gain = 0 dB)
        gain_crossover = np.where(mag_db <= 0)[0]
        if len(gain_crossover) > 0:
            pm_idx = gain_crossover[0]
            metrics.phase_margin_deg = float(180 + phase_deg[pm_idx])
            metrics.phase_margin_freq_hz = float(freq_hz[pm_idx])
        else:
            metrics.phase_margin_deg = 90.0  # Very stable

        return metrics

    # ─── Residual Analysis ────────────────────────────────────────────

    @staticmethod
    def residual_analysis(
        model: TransferFunctionModel,
        u: np.ndarray,
        y: np.ndarray,
    ) -> dict:
        """Perform residual analysis on a model.

        Returns:
            Dict with residual statistics and whiteness test results.
        """
        y_sim = model.simulate(u)
        n = min(len(y), len(y_sim))
        residuals = y[:n] - y_sim[:n]

        # Basic statistics
        result = {
            "mean": float(np.mean(residuals)),
            "std": float(np.std(residuals)),
            "rms": float(np.sqrt(np.mean(residuals ** 2))),
            "max_abs": float(np.max(np.abs(residuals))),
        }

        # Autocorrelation of residuals
        if len(residuals) > 20:
            acf = np.correlate(residuals, residuals, mode="full")
            acf = acf[len(residuals) - 1:]
            acf = acf / acf[0]
            # 95% confidence band
            conf_band = 1.96 / np.sqrt(len(residuals))
            result["acf"] = acf[:50].tolist()
            result["confidence_band"] = float(conf_band)
            result["is_white"] = bool(np.all(np.abs(acf[1:20]) < conf_band * 2))

        # Cross-correlation between input and residuals
        if len(u) >= n:
            xcorr = np.correlate(u[:n], residuals, mode="full")
            xcorr = xcorr / (np.std(u[:n]) * np.std(residuals) * n)
            result["cross_corr_peak"] = float(np.max(np.abs(xcorr)))
            result["input_uncorrelated"] = result["cross_corr_peak"] < 0.2

        return result

    # ─── Model Comparison ─────────────────────────────────────────────

    @staticmethod
    def compare_models(
        models: list[TransferFunctionModel],
        ranking: str = "bic",
    ) -> ModelComparison:
        """Compare multiple identified models.

        Args:
            models: List of identified models.
            ranking: Ranking criterion ("bic", "fit", "bandwidth").

        Returns:
            ModelComparison with metrics for each model.
        """
        step_metrics = []
        freq_metrics = []
        fit_percents = []

        for model in models:
            sm = ModelValidator.step_response_metrics(model)
            fm = ModelValidator.frequency_metrics(model)
            step_metrics.append(sm)
            freq_metrics.append(fm)
            fit_percents.append(model.fit_percent)

        # Rank models
        if ranking == "bic":
            scores = [m.bic for m in models]
            best_idx = int(np.argmin(scores))
        elif ranking == "fit":
            best_idx = int(np.argmax(fit_percents))
        elif ranking == "bandwidth":
            bw = [fm.bandwidth_hz for fm in freq_metrics]
            best_idx = int(np.argmax(bw))
        else:
            best_idx = 0

        return ModelComparison(
            models=models,
            step_metrics=step_metrics,
            freq_metrics=freq_metrics,
            fit_percents=fit_percents,
            best_index=best_idx,
            ranking_criteria=ranking,
        )


def compute_step_response_data(
    model: TransferFunctionModel,
    t_duration: float = 5.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute step response as (time, output) arrays for plotting.

    Returns:
        (t, y) arrays.
    """
    dt = model.dt if model.dt > 0 else 0.01
    n = int(t_duration / dt)
    t = np.arange(n) * dt
    u = np.ones(n)
    y = model.simulate(u, t)
    return t, y


def compute_frequency_response_data(
    model: TransferFunctionModel,
    n_points: int = 1024,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute frequency response as (freq_hz, magnitude_db, phase_deg) for plotting.

    Returns:
        (freq_hz, mag_db, phase_deg) arrays.
    """
    dt = model.dt if model.dt > 0 else 0.01
    fs = 1.0 / dt
    w = np.logspace(-2, np.log10(fs / 2 * 2 * np.pi), n_points)

    try:
        w_resp, h = sp_signal.dfreqresp((model.num, model.den, dt), w=w)
    except Exception:
        sys = sp_signal.dlti(model.num, model.den, dt=dt)
        w_resp, h = sp_signal.dfreqresp(sys, w=w)

    freq_hz = w_resp / (2 * np.pi)
    mag_db = 20 * np.log10(np.abs(h) + 1e-20)
    phase_deg = np.degrees(np.angle(h))

    return freq_hz, mag_db, phase_deg


def compute_bode_comparison(
    models: list[TransferFunctionModel],
    labels: Optional[list[str]] = None,
    n_points: int = 1024,
) -> dict:
    """Compute Bode data for multiple models for overlay plotting.

    Returns:
        Dict with 'freq_hz', and for each model: 'mag_db_i', 'phase_deg_i', 'label_i'.
    """
    if labels is None:
        labels = [f"Model {i+1}" for i in range(len(models))]

    result = {"models": []}
    for i, (model, label) in enumerate(zip(models, labels)):
        freq_hz, mag_db, phase_deg = compute_frequency_response_data(model, n_points)
        result["models"].append({
            "label": label,
            "freq_hz": freq_hz,
            "mag_db": mag_db,
            "phase_deg": phase_deg,
        })

    return result
