"""Excitation detector — find rich dynamic segments in flight data.

Detects step inputs, doublets, frequency sweeps, and general high-excitation
segments suitable for system identification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
from scipy import signal as sp_signal


class ExcitationType(Enum):
    STEP = "step"
    DOUBLET = "doublet"
    SWEEP = "sweep"
    GENERAL = "general"       # High-variance / rich content
    PULSE = "pulse"


@dataclass
class ExcitationSegment:
    """A detected excitation segment."""
    t_start: float
    t_end: float
    duration: float
    excitation_type: ExcitationType
    channel: str              # Source channel name
    quality_score: float      # 0-1, how rich the excitation is
    amplitude: float          # Peak-to-peak or step magnitude
    notes: str = ""

    def __repr__(self):
        return (f"<Segment {self.excitation_type.value} "
                f"[{self.t_start:.2f}-{self.t_end:.2f}s] "
                f"ch={self.channel} q={self.quality_score:.2f}>")


class ExcitationDetector:
    """Automatically detect excitation segments in time-series data.

    Uses sliding-window variance analysis, step detection, and spectral
    richness metrics to find segments suitable for system identification.
    """

    def __init__(
        self,
        min_duration: float = 0.5,       # Minimum segment duration (s)
        max_duration: float = 60.0,      # Maximum segment duration (s)
        variance_threshold: float = 0.3, # Relative threshold for variance change
        step_threshold: float = 0.5,     # Step detection threshold (fraction of std)
    ):
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.variance_threshold = variance_threshold
        self.step_threshold = step_threshold

    def detect(
        self,
        time: np.ndarray,
        data: np.ndarray,
        channel_name: str = "",
        window_size: float = 1.0,   # Sliding window size in seconds
    ) -> list[ExcitationSegment]:
        """Detect excitation segments in a signal.

        Args:
            time: Timestamp array (seconds).
            data: Signal values.
            channel_name: Name of the channel.
            window_size: Sliding window duration in seconds.

        Returns:
            List of detected segments, sorted by time.
        """
        if len(time) < 10 or len(data) < 10:
            return []

        dt = np.median(np.diff(time))
        if dt <= 0:
            return []

        win_samples = max(int(window_size / dt), 5)

        segments = []

        # 1. Detect steps
        step_segs = self._detect_steps(time, data, channel_name)
        segments.extend(step_segs)

        # 2. Detect doublets
        doublet_segs = self._detect_doublets(time, data, channel_name)
        segments.extend(doublet_segs)

        # 3. Detect high-variance (rich excitation) segments
        var_segs = self._detect_high_variance(time, data, channel_name, win_samples)
        segments.extend(var_segs)

        # 4. Detect frequency sweeps (chirp)
        sweep_segs = self._detect_sweeps(time, data, channel_name)
        segments.extend(sweep_segs)

        # Merge overlapping segments
        segments = self._merge_overlapping(segments)

        # Score and sort
        for seg in segments:
            seg.quality_score = self._score_segment(time, data, seg)
        segments.sort(key=lambda s: s.t_start)

        return segments

    def detect_steps(
        self,
        time: np.ndarray,
        data: np.ndarray,
        channel_name: str = "",
    ) -> list[ExcitationSegment]:
        """Public interface for step-only detection."""
        return self._detect_steps(time, data, channel_name)

    def _detect_steps(
        self,
        time: np.ndarray,
        data: np.ndarray,
        channel_name: str,
    ) -> list[ExcitationSegment]:
        """Detect step-like changes in the signal."""
        segments = []
        std = np.std(data)
        if std < 1e-10:
            return segments

        # Compute first difference
        diff = np.diff(data)
        abs_diff = np.abs(diff)
        threshold = self.step_threshold * std

        # Find large jumps
        jump_idx = np.where(abs_diff > threshold)[0]
        if len(jump_idx) == 0:
            return segments

        # Group consecutive jumps
        groups = self._group_consecutive(jump_idx)

        for group in groups:
            i_start = group[0]
            i_end = group[-1] + 1

            # Extend to capture the settling period
            settling_samples = int(0.5 / np.median(np.diff(time)))  # 0.5s settling
            i_settle = min(i_end + settling_samples, len(time) - 1)

            # Check if step is significant enough
            pre_val = np.mean(data[max(0, i_start - 5):i_start]) if i_start > 5 else data[0]
            post_val = np.mean(data[i_end:min(i_settle, len(data))])
            step_mag = abs(post_val - pre_val)

            if step_mag > 2 * std:
                segments.append(ExcitationSegment(
                    t_start=float(time[max(0, i_start - 2)]),
                    t_end=float(time[i_settle]),
                    duration=float(time[i_settle] - time[max(0, i_start - 2)]),
                    excitation_type=ExcitationType.STEP,
                    channel=channel_name,
                    quality_score=0.0,  # Will be scored later
                    amplitude=step_mag,
                ))

        return segments

    def _detect_doublets(
        self,
        time: np.ndarray,
        data: np.ndarray,
        channel_name: str,
    ) -> list[ExcitationSegment]:
        """Detect doublet inputs (positive then negative step, or vice versa)."""
        segments = []
        std = np.std(data)
        if std < 1e-10:
            return segments

        diff = np.diff(data)
        threshold = self.step_threshold * std * 0.5

        # Find sign changes after significant moves
        sign_changes = np.where(np.diff(np.sign(diff)))[0]

        i = 0
        while i < len(sign_changes) - 1:
            idx1 = sign_changes[i]
            idx2 = sign_changes[i + 1]

            # Check both moves are significant
            move1 = abs(diff[idx1]) if idx1 < len(diff) else 0
            move2 = abs(diff[idx2]) if idx2 < len(diff) else 0

            if move1 > threshold and move2 > threshold:
                # Check moves are in opposite directions
                if np.sign(diff[idx1]) != np.sign(diff[idx2]):
                    seg_duration = time[idx2 + 1] - time[idx1]
                    if self.min_duration <= seg_duration <= self.max_duration:
                        segments.append(ExcitationSegment(
                            t_start=float(time[idx1]),
                            t_end=float(time[min(idx2 + 2, len(time) - 1)]),
                            duration=seg_duration,
                            excitation_type=ExcitationType.DOUBLET,
                            channel=channel_name,
                            quality_score=0.0,
                            amplitude=max(move1, move2),
                        ))
                    i += 2
                    continue
            i += 1

        return segments

    def _detect_high_variance(
        self,
        time: np.ndarray,
        data: np.ndarray,
        channel_name: str,
        win_samples: int,
    ) -> list[ExcitationSegment]:
        """Detect segments with high variance (rich dynamic content)."""
        segments = []
        n = len(data)
        if n < win_samples * 2:
            return segments

        # Compute sliding window variance
        kernel = np.ones(win_samples) / win_samples
        mean_sq = np.convolve(data ** 2, kernel, mode="valid")
        mean_val = np.convolve(data, kernel, mode="valid")
        variance = mean_sq - mean_val ** 2

        # Global statistics
        global_var = np.var(data)
        if global_var < 1e-15:
            return segments

        # Normalize variance
        norm_var = variance / global_var

        # Find contiguous high-variance regions
        high_var = norm_var > self.variance_threshold

        # Find boundaries
        transitions = np.diff(high_var.astype(int))
        starts = np.where(transitions == 1)[0] + 1
        ends = np.where(transitions == -1)[0] + 1

        # Handle edge cases
        if high_var[0]:
            starts = np.concatenate([[0], starts])
        if high_var[-1]:
            ends = np.concatenate([ends, [len(high_var)]])

        # Offset for valid convolution output
        offset = win_samples // 2

        for s, e in zip(starts, ends):
            t_s = float(time[s + offset])
            t_e = float(time[min(e + offset, n - 1)])
            duration = t_e - t_s

            if duration < self.min_duration or duration > self.max_duration:
                continue

            # Check spectral richness
            seg_data = data[s + offset:e + offset]
            if len(seg_data) < 10:
                continue

            spectral_score = self._spectral_richness(seg_data)
            if spectral_score < 0.1:
                continue

            segments.append(ExcitationSegment(
                t_start=t_s,
                t_end=t_e,
                duration=duration,
                excitation_type=ExcitationType.GENERAL,
                channel=channel_name,
                quality_score=0.0,
                amplitude=float(np.std(seg_data)),
            ))

        return segments

    def _detect_sweeps(
        self,
        time: np.ndarray,
        data: np.ndarray,
        channel_name: str,
    ) -> list[ExcitationSegment]:
        """Detect frequency sweeps (chirp signals)."""
        segments = []

        # Use spectrogram to detect increasing frequency content
        dt = np.median(np.diff(time))
        if dt <= 0 or len(data) < 50:
            return segments

        fs = 1.0 / dt
        nperseg = min(len(data) // 4, 256)
        if nperseg < 16:
            return segments

        try:
            f, t_spec, Sxx = sp_signal.spectrogram(data, fs=fs, nperseg=nperseg)
        except Exception:
            return segments

        # Look for time-varying peak frequency
        peak_freqs = f[np.argmax(Sxx, axis=0)]

        # Check if peak frequency is monotonically increasing or decreasing
        freq_diff = np.diff(peak_freqs)
        if len(freq_diff) < 5:
            return segments

        # Check for monotonic trend in peak frequency
        n_up = np.sum(freq_diff > 0)
        n_down = np.sum(freq_diff < 0)
        total = len(freq_diff)

        if max(n_up, n_down) / total > 0.7:  # 70% monotonic
            # This looks like a sweep
            t_start = float(t_spec[0] + time[0])
            t_end = float(t_spec[-1] + time[0])
            duration = t_end - t_start

            if self.min_duration <= duration <= self.max_duration:
                segments.append(ExcitationSegment(
                    t_start=t_start,
                    t_end=t_end,
                    duration=duration,
                    excitation_type=ExcitationType.SWEEP,
                    channel=channel_name,
                    quality_score=0.0,
                    amplitude=float(np.std(data)),
                    notes=f"Freq range: {peak_freqs[0]:.1f} - {peak_freqs[-1]:.1f} Hz",
                ))

        return segments

    def _spectral_richness(self, data: np.ndarray) -> float:
        """Compute a 0-1 score for spectral richness of a signal segment.

        Higher score means more frequency content (good for identification).
        """
        if len(data) < 10:
            return 0.0

        # Compute power spectrum
        fft = np.fft.rfft(data - np.mean(data))
        power = np.abs(fft) ** 2

        if np.sum(power) < 1e-15:
            return 0.0

        # Normalize
        power_norm = power / np.sum(power)

        # Entropy of power distribution (higher = richer)
        # Avoid log(0)
        p = power_norm[power_norm > 0]
        entropy = -np.sum(p * np.log2(p))
        max_entropy = np.log2(len(p)) if len(p) > 0 else 1.0

        richness = entropy / max_entropy if max_entropy > 0 else 0.0

        # Also check number of significant frequency components
        n_significant = np.sum(power_norm > 0.05)
        freq_diversity = min(n_significant / 5.0, 1.0)

        return 0.5 * richness + 0.5 * freq_diversity

    def _score_segment(
        self,
        time: np.ndarray,
        data: np.ndarray,
        seg: ExcitationSegment,
    ) -> float:
        """Compute quality score (0-1) for a segment."""
        mask = (time >= seg.t_start) & (time <= seg.t_end)
        seg_data = data[mask]

        if len(seg_data) < 5:
            return 0.0

        # Factor 1: Duration suitability (prefer 1-10s)
        dur_score = 1.0
        if seg.duration < 1.0:
            dur_score = seg.duration / 1.0
        elif seg.duration > 10.0:
            dur_score = max(0.5, 10.0 / seg.duration)

        # Factor 2: Spectral richness
        spectral = self._spectral_richness(seg_data)

        # Factor 3: Signal-to-noise ratio estimate
        # Use variance ratio of first vs second half as a crude SNR proxy
        half = len(seg_data) // 2
        if half > 2:
            var1 = np.var(seg_data[:half])
            var2 = np.var(seg_data[half:])
            snr = min(var1, var2) / max(var1, var2) if max(var1, var2) > 0 else 0
        else:
            snr = 0.5

        # Factor 4: Type bonus
        type_bonus = {
            ExcitationType.STEP: 0.9,
            ExcitationType.DOUBLET: 0.85,
            ExcitationType.SWEEP: 0.95,
            ExcitationType.GENERAL: 0.6,
            ExcitationType.PULSE: 0.7,
        }.get(seg.excitation_type, 0.5)

        score = 0.2 * dur_score + 0.3 * spectral + 0.2 * (1 - snr) + 0.3 * type_bonus
        return float(np.clip(score, 0, 1))

    def _merge_overlapping(
        self, segments: list[ExcitationSegment]
    ) -> list[ExcitationSegment]:
        """Merge segments that overlap in time."""
        if len(segments) <= 1:
            return segments

        # Sort by start time
        segments.sort(key=lambda s: s.t_start)
        merged = [segments[0]]

        for seg in segments[1:]:
            prev = merged[-1]
            if seg.t_start <= prev.t_end:
                # Overlapping — merge
                prev.t_end = max(prev.t_end, seg.t_end)
                prev.duration = prev.t_end - prev.t_start
                prev.amplitude = max(prev.amplitude, seg.amplitude)
                if seg.quality_score > prev.quality_score:
                    prev.quality_score = seg.quality_score
            else:
                merged.append(seg)

        return merged

    def _group_consecutive(self, indices: np.ndarray, max_gap: int = 3) -> list[list[int]]:
        """Group consecutive indices (with small gaps tolerated)."""
        if len(indices) == 0:
            return []

        groups = [[indices[0]]]
        for idx in indices[1:]:
            if idx - groups[-1][-1] <= max_gap:
                groups[-1].append(idx)
            else:
                groups.append([idx])

        return groups


def find_identification_segments(
    time: np.ndarray,
    signals: dict[str, np.ndarray],
    min_duration: float = 0.5,
) -> list[ExcitationSegment]:
    """Convenience function: find segments across multiple channels.

    Args:
        time: Time array.
        signals: Dict of channel_name -> signal array.
        min_duration: Minimum segment duration.

    Returns:
        Merged list of segments from all channels.
    """
    detector = ExcitationDetector(min_duration=min_duration)
    all_segments = []

    for name, data in signals.items():
        if len(data) == len(time):
            segs = detector.detect(time, data, channel_name=name)
            all_segments.extend(segs)

    # Merge across channels
    all_segments = detector._merge_overlapping(all_segments)
    all_segments.sort(key=lambda s: s.t_start)

    return all_segments
