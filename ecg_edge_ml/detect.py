"""detect.py - R-peak detection on an already band-passed ECG (simplified Pan-Tompkins), NumPy/SciPy only.

Pan-Tompkins in four steps (the ECG-Edge firmware has an integer C version of the same idea):
  1. derivative         d[n] = y[n+1]-y[n-1]   -> emphasises the steep QRS slopes, kills slow P/T waves
  2. squaring           d^2                    -> all positive, big slopes dominate
  3. moving-window integration (150 ms ~ one QRS width) -> one smooth hump per beat
  4. adaptive threshold: 25 % of the local maximum (8 s window) + a minimum spacing of 250 ms (refractory period)
Each hump is then refined to the largest |y| within +/-100 ms, which is the R-peak position in the signal.
Detection runs on the FILTERED signal, so positions are in filtered (delayed) time.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import maximum_filter1d
from scipy.signal import find_peaks

from .dsp import FS_HZ


def detect_r_peaks(y: np.ndarray, fs: int = FS_HZ) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    if len(y) < 4 * fs:
        return np.zeros(0, dtype=np.int64)
    d = np.zeros_like(y)
    d[1:-1] = y[2:] - y[:-2]
    sq = d ** 2
    w = max(int(round(0.15 * fs)), 1)
    integ = np.convolve(sq, np.ones(w) / w, mode="same")
    local_max = maximum_filter1d(integ, size=int(8 * fs), mode="nearest")
    floor = 0.05 * np.percentile(integ, 99)                      # ignore noise-only stretches
    thr = np.maximum(0.25 * local_max, floor)
    cand, _ = find_peaks(integ, height=thr, distance=int(0.25 * fs))
    half = int(0.10 * fs)
    peaks = []
    for c in cand:
        lo, hi = max(c - half, 0), min(c + half + 1, len(y))
        peaks.append(lo + int(np.argmax(np.abs(y[lo:hi]))))
    return np.unique(np.asarray(peaks, dtype=np.int64))


def match_peaks(det, truth, tol: int):
    """Greedy one-to-one matching within +/-tol samples. Returns (tp, fp, fn)."""
    det, truth = np.sort(np.asarray(det)), np.sort(np.asarray(truth))
    used = np.zeros(len(det), dtype=bool)
    tp = 0
    for t in truth:
        i = int(np.searchsorted(det, t))
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(det) and not used[j] and abs(int(det[j]) - int(t)) <= tol:
                if best is None or abs(int(det[j]) - int(t)) < abs(int(det[best]) - int(t)):
                    best = j
        if best is not None:
            used[best] = True
            tp += 1
    return tp, len(det) - tp, len(truth) - tp
