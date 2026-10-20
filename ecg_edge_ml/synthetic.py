"""synthetic.py - a made-up ECG with normal (N), ventricular (V) and supraventricular (A) beats.

ONLY for unit tests and for smoke-testing the pipeline when PhysioNet is unreachable.  It is a
sum of Gaussians, not a physiological model: never report numbers measured on it as results.
Its one job is to have KNOWN R-peak positions and KNOWN labels, so tests can prove that beat
extraction and filter-delay compensation are correct.
"""
from __future__ import annotations

import numpy as np

from .dsp import FS_HZ

# (centre [s] relative to R, amplitude [mV], width [s])
_N_WAVES = [(-0.20, 0.12, 0.025), (-0.035, -0.12, 0.010), (0.0, 1.10, 0.012), (0.035, -0.25, 0.012), (0.27, 0.30, 0.050)]
_V_WAVES = [(0.0, 1.60, 0.035), (0.22, -0.60, 0.070)]                  # wide, tall QRS, inverted T, no P
_A_WAVES = [(-0.035, -0.10, 0.010), (0.0, 1.00, 0.012), (0.035, -0.20, 0.012), (0.25, 0.25, 0.045)]  # no P wave


def synthetic_record(seconds: float = 120.0, seed: int = 0, p_v: float = 0.15, p_s: float = 0.08,
                     fs: int = FS_HZ) -> dict:
    """Return dict(x_mv, ann_samples, ann_symbols) with 'N', 'V', 'A' beats."""
    rng = np.random.default_rng(seed)
    n = int(round(seconds * fs))
    t = np.arange(n) / fs
    x = np.zeros(n)
    samples, symbols = [], []
    tr = 6.0                                    # first beat after the IIR start-up transient
    while tr < seconds - 1.0:
        u = rng.random()
        if u < p_v:
            sym, waves, rr_next = "V", _V_WAVES, 0.95        # compensatory pause after a PVC
        elif u < p_v + p_s:
            sym, waves, rr_next = "A", _A_WAVES, 0.80
        else:
            sym, waves, rr_next = "N", _N_WAVES, 0.85 * (1.0 + 0.05 * rng.standard_normal())
        for c, a, w in waves:
            x += a * np.exp(-0.5 * ((t - tr - c) / w) ** 2)
        samples.append(int(round(tr * fs)))
        symbols.append(sym)
        tr += rr_next
    x += 0.30 * np.sin(2 * np.pi * 0.30 * t) + 0.15 * np.sin(2 * np.pi * 0.10 * t + 1.0)   # baseline wander
    x += 0.05 * np.sin(2 * np.pi * 60.0 * t)                                               # mains
    x += 0.02 * rng.standard_normal(n)                                                     # EMG-like noise
    return dict(x_mv=x, ann_samples=np.array(samples), ann_symbols=np.array(symbols))
