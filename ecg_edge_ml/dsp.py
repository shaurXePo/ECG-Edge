"""dsp.py - the ECG-Edge filter chain, in Python, in every arithmetic we care about.

Ported from the ECG-Edge repo (scripts/common.py and scripts/diagnose_q15_iir.py) so that this
project is self-contained.  The filter SPEC is identical: 0.5-40 Hz band-pass + 60 Hz notch,
fs = 360 Hz, int16 samples = Q15 with +/-5 mV full scale.

Why a bit-exact fixed-point *model* here?  The classifier experiment asks "what happens to
classification if the filter runs in Q15 instead of float?".  A Python model of the CMSIS
arithmetic answers that on a laptop, for all 44 records, without hardware.  (The ECG-Edge
README says this model was verified against the C kernel; we have not re-verified it here.)

Every filter is exposed as an `ECGFilter`:
    apply(x_int)  -> float64 array in int16-LSB units   (causal, zero initial state)
    delay         -> integer group delay in samples (used to re-align beats with annotations)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy import signal

# ---------------------------------------------------------------- specification (one place)
FS_HZ = 360                      # MIT-BIH sampling rate [Hz]
FULLSCALE_MV = 5.0               # int16 full scale = +/-5 mV  (1 LSB = 0.1526 uV)
LSB_MV = FULLSCALE_MV / 32768.0  # mV per int16 LSB
BP_LO_HZ, BP_HI_HZ = 0.5, 40.0   # diagnostic-ECG band
NOTCH_HZ, NOTCH_Q = 60.0, 30.0   # US mains (MIT-BIH); use 50 for Indian recordings. Q=30 -> ~2 Hz wide
DELAY_PROBE_HZ = 10.0            # IIR group delay is measured at 10 Hz, where QRS energy lives
Q15_MIN, Q15_MAX = -32768, 32767
# hp1: two cascaded 1st-order high-passes; cutoff lowered so the CASCADE is -3 dB at 0.5 Hz
HP1_FC_HZ = BP_LO_HZ * math.sqrt(math.sqrt(2.0) - 1.0)


# ---------------------------------------------------------------- float64 "golden" designs
def design_fir(ntaps: int) -> np.ndarray:
    """Hamming windowed-sinc band-pass; ntaps odd -> type-I linear phase, delay (ntaps-1)/2."""
    if ntaps % 2 == 0:
        raise ValueError("ntaps must be odd")
    return signal.firwin(ntaps, [BP_LO_HZ, BP_HI_HZ], pass_zero=False, window="hamming", fs=FS_HZ)


def design_iir_sos(order: int) -> np.ndarray:
    """Butterworth band-pass (order -> `order` biquads) followed by a notch biquad."""
    sos = signal.butter(order, [BP_LO_HZ, BP_HI_HZ], btype="bandpass", fs=FS_HZ, output="sos")
    b, a = signal.iirnotch(NOTCH_HZ, NOTCH_Q, fs=FS_HZ)
    return np.vstack([sos, signal.tf2sos(b, a)])


def design_iirh_sos(lp_order: int = 2) -> np.ndarray:
    """[1st-order HP, 1st-order HP, Butterworth LP 40 Hz, 60 Hz notch] - the Q15-friendly structure.
    First-order sections are stored as biquads with b2 = a2 = 0."""
    hp = signal.butter(1, HP1_FC_HZ, btype="highpass", fs=FS_HZ, output="sos")
    lp = signal.butter(lp_order, BP_HI_HZ, btype="lowpass", fs=FS_HZ, output="sos")
    b, a = signal.iirnotch(NOTCH_HZ, NOTCH_Q, fs=FS_HZ)
    return np.vstack([hp, hp, lp, signal.tf2sos(b, a)])


def quantize_input(x_mv: np.ndarray) -> np.ndarray:
    """mV -> int16 range (kept as int64 for safe arithmetic). Round to nearest, clip at the rails."""
    q = np.round(np.asarray(x_mv, dtype=float) / FULLSCALE_MV * 32768.0)
    return np.clip(q, Q15_MIN, Q15_MAX).astype(np.int64)


# ---------------------------------------------------------------- coefficient helpers (CMSIS)
def sos_peak_gains(sos: np.ndarray, n: int = 8192) -> np.ndarray:
    w = np.linspace(0, np.pi, n)
    return np.array([np.max(np.abs(signal.sosfreqz(s[None, :], worN=w)[1])) for s in sos])


def scale_sos_linf(sos: np.ndarray) -> np.ndarray:
    """L-infinity section scaling: divide each section's numerator by its peak gain and put the
    product back into the LAST section.  The cascade's transfer function is unchanged, but no
    inner node can exceed the input level (no clipping inside the cascade)."""
    g = sos_peak_gains(sos)
    out = sos.copy()
    out[:, :3] = out[:, :3] / g[:, None]
    out[-1, :3] *= float(np.prod(g))
    return out


def sos_to_cmsis(sos: np.ndarray) -> np.ndarray:
    """scipy row [b0 b1 b2 1 a1 a2] -> CMSIS row [b0 b1 b2 -a1 -a2] (feedback sign flipped)."""
    return np.column_stack([sos[:, 0], sos[:, 1], sos[:, 2], -sos[:, 4], -sos[:, 5]])


def choose_post_shift(coefs: np.ndarray) -> int:
    """Smallest postShift p with every |coef| < 2**p.  Stored int q = round(c * 2**(15-p))."""
    m = float(np.max(np.abs(coefs)))
    p = 0
    while m >= 2.0 ** p * (1.0 - 2.0 ** -15):
        p += 1
    return p


def quant(values: np.ndarray, total_bits: int, post_shift: int = 0) -> np.ndarray:
    """Round to nearest, saturate.  Stored int = round(v * 2**(total_bits-1-post_shift))."""
    scale = 2.0 ** (total_bits - 1 - post_shift)
    lo, hi = -(2 ** (total_bits - 1)), 2 ** (total_bits - 1) - 1
    return np.clip(np.round(np.asarray(values) * scale), lo, hi).astype(np.int64)


# ---------------------------------------------------------------- bit-exact fixed-point models
def fir_q15(x: np.ndarray, h: np.ndarray, rounding: bool = False) -> np.ndarray:
    """Model of arm_fir_q15: Q15 taps, 64-bit accumulate, then >>15 and saturate.
    CMSIS TRUNCATES (floor); `rounding=True` adds half an LSB first (our hand-written FIR)."""
    q = quant(h, 16)                                                # taps all |h|<1 -> plain Q15
    acc = np.convolve(np.asarray(x, dtype=np.int64), q)[: len(x)]   # exact in int64
    if rounding:
        acc = acc + (1 << 14)
    return np.clip(acc >> 15, Q15_MIN, Q15_MAX)


def biquad_df1_q15(x, cmsis_coefs: np.ndarray, post_shift: int, rounding: bool = False) -> np.ndarray:
    """Model of arm_biquad_cascade_df1_q15:
        acc = b0*x + b1*x1 + b2*x2 + a1*y1 + a2*y2   (64-bit)
        y   = saturate16( (acc [+ half]) >> (15 - post_shift) )
    A plain Python loop (a few us per sample per section): fine for offline experiments."""
    q = quant(cmsis_coefs, 16, post_shift)
    sh = 15 - post_shift
    half = (1 << (sh - 1)) if rounding else 0
    y = [int(v) for v in x]
    for b0, b1, b2, a1, a2 in q.tolist():
        out = [0] * len(y)
        x1 = x2 = y1 = y2 = 0
        for n, xn in enumerate(y):
            yn = (b0 * xn + b1 * x1 + b2 * x2 + a1 * y1 + a2 * y2 + half) >> sh
            if yn > Q15_MAX:
                yn = Q15_MAX
            elif yn < Q15_MIN:
                yn = Q15_MIN
            x2, x1, y2, y1 = x1, xn, y1, yn
            out[n] = yn
        y = out
    return np.asarray(y, dtype=np.int64)


# ---------------------------------------------------------------- filter registry
@dataclass(frozen=True)
class ECGFilter:
    name: str
    apply: Callable[[np.ndarray], np.ndarray]   # int samples -> float64 in int16-LSB units
    delay: int                                  # group delay in samples
    description: str


def _iir_delay(sos: np.ndarray) -> int:
    w = 2 * np.pi * DELAY_PROBE_HZ / FS_HZ
    tot = 0.0
    for s in sos:
        _, gd = signal.group_delay((s[:3], s[3:]), w=[w])
        tot += float(gd[0])
    return int(round(tot))


def _sos_filter(sos: np.ndarray, fixed: bool, rounding: bool):
    """Return (apply, delay) for an SOS design in float64 or Q15 (linf-scaled, like the firmware)."""
    delay = _iir_delay(sos)
    if not fixed:
        return (lambda x: signal.sosfilt(sos, np.asarray(x, dtype=float))), delay
    cm = sos_to_cmsis(scale_sos_linf(sos))
    ps = choose_post_shift(cm)
    return (lambda x: biquad_df1_q15(x, cm, ps, rounding).astype(float)), delay


def make_filter(name: str) -> ECGFilter:
    """Names:
         raw                      no filtering (baseline)
         fir{N}_f64               float64 FIR, N odd taps             e.g. fir127_f64
         fir{N}_q15 / _q15r       CMSIS-style Q15 FIR, truncate / round
         iir{K}_f64               float64 Butterworth(K)+notch
         iir{K}_q15               Q15 CMSIS-style, truncate, linf scaling   (the one that FAILS)
         iirh_f64 / _q15 / _q15r  hp1 structure: float64 / Q15 truncate / Q15 round
    """
    if name == "raw":
        return ECGFilter(name, lambda x: np.asarray(x, dtype=float), 0, "unfiltered")

    m = re.fullmatch(r"fir(\d+)_(f64|q15|q15r)", name)
    if m:
        n, kind = int(m.group(1)), m.group(2)
        h = design_fir(n)
        if kind == "f64":
            fn = lambda x: np.convolve(np.asarray(x, dtype=float), h)[: len(x)]
        else:
            fn = lambda x: fir_q15(x, h, rounding=(kind == "q15r")).astype(float)
        return ECGFilter(name, fn, (n - 1) // 2, f"{n}-tap Hamming FIR, {kind}")

    m = re.fullmatch(r"iir(\d+)_(f64|q15)", name)
    if m:
        order, kind = int(m.group(1)), m.group(2)
        fn, delay = _sos_filter(design_iir_sos(order), kind == "q15", rounding=False)
        return ECGFilter(name, fn, delay, f"Butterworth({order})+notch, {kind}")

    m = re.fullmatch(r"iirh_(f64|q15|q15r)", name)
    if m:
        kind = m.group(1)
        fn, delay = _sos_filter(design_iirh_sos(2), kind != "f64", rounding=(kind == "q15r"))
        return ECGFilter(name, fn, delay, f"hp1 structure, {kind}")

    raise ValueError(f"unknown filter name {name!r}")


def filter_mv(flt: ECGFilter, x_mv: np.ndarray) -> np.ndarray:
    """mV -> int16 -> filter -> output in mV (the unit the classifier sees)."""
    return flt.apply(quantize_input(x_mv)) * LSB_MV


# Each fixed-point filter's float64 "twin": the same design in float, so error = arithmetic only.
FLOAT_TWIN = {"fir127_q15": "fir127_f64", "fir127_q15r": "fir127_f64", "iir2_q15": "iir2_f64",
              "iirh_q15": "iirh_f64", "iirh_q15r": "iirh_f64"}


# ---------------------------------------------------------------- coefficient view (for frequency-response plots)
def coeffs_for(name: str):
    """(kind, float_coeffs, quantised_coeffs_as_floats) for a filter name; quantised is None for float/raw filters.
    kind 'fir': coefficient arrays are tap vectors.  kind 'sos': arrays are scipy SOS matrices.
    The quantised SOS is the CMSIS Q15 coefficient set (linf-scaled, post-shifted, rounded to 16 bit) turned
    back into floats: it shows what COEFFICIENT rounding alone does, ignoring the per-sample truncation noise."""
    if name == "raw":
        return "fir", np.array([1.0]), None
    m = re.fullmatch(r"fir(\d+)_(f64|q15|q15r)", name)
    if m:
        h = design_fir(int(m.group(1)))
        return "fir", h, (None if m.group(2) == "f64" else quant(h, 16) / 32768.0)
    m = re.fullmatch(r"iir(\d+)_(f64|q15)", name)
    if m:
        sos, fixed = design_iir_sos(int(m.group(1))), m.group(2) == "q15"
    else:
        m = re.fullmatch(r"iirh_(f64|q15|q15r)", name)
        if not m:
            raise ValueError(f"unknown filter name {name!r}")
        sos, fixed = design_iirh_sos(2), m.group(1) != "f64"
    if not fixed:
        return "sos", sos, None
    cm = sos_to_cmsis(scale_sos_linf(sos))
    ps = choose_post_shift(cm)
    q = quant(cm, 16, ps) / 2.0 ** (15 - ps)                      # back to float: [b0 b1 b2 a1' a2'] (a' = -a)
    sos_q = np.column_stack([q[:, 0], q[:, 1], q[:, 2], np.ones(len(q)), -q[:, 3], -q[:, 4]])
    return "sos", sos, sos_q


def magnitude_db(kind: str, coeffs: np.ndarray, n: int = 4096):
    """(freq_hz, |H| in dB) on n points from 0 to fs/2."""
    if kind == "fir":
        w, h = signal.freqz(coeffs, worN=n)
    else:
        w, h = signal.sosfreqz(coeffs, worN=n)
    return w * FS_HZ / (2 * np.pi), 20 * np.log10(np.maximum(np.abs(h), 1e-12))
