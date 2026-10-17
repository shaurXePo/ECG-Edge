#!/usr/bin/env python3
"""diagnose_q15_iir.py - WHY does a Q15 Butterworth biquad at 0.5 Hz / fs=360 Hz fail?

Runs a bit-exact Python model of CMSIS arm_biquad_cascade_df1_q15 (verified equal to the C
kernel, see README) and prints the three numbers that explain the failure:

  1. DC gain of each section's feedback path  1/A(1) = 1/(1 + a1 + a2)
        -> a constant error injected at the section output (the -0.5 LSB of truncation) is
           multiplied by this number.
  2. Coefficient-quantisation sensitivity: A(1) compared with one Q-format LSB of a1/a2.
        -> if A(1) is not >> one LSB, the DC pole position is essentially random.
  3. SNR for: truncating vs rounding, scaling none/linf, Butterworth vs hp1 structure.

    python scripts/diagnose_q15_iir.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402


def df1_q15(x, cm, ps, rounding=False):
    """Bit-exact model: acc = b0x + b1x1 + b2x2 + a1y1 + a2y2 ; y = sat16((acc [+ half]) >> (15 - ps))."""
    q = C.quant(cm, 16, ps).astype(np.int64)
    sh = 15 - ps
    y = np.asarray(x, dtype=np.int64)
    for b0, b1, b2, a1, a2 in q:
        out = np.empty_like(y); x1 = x2 = y1 = y2 = 0
        for n, xn in enumerate(y):
            acc = b0 * int(xn) + b1 * x1 + b2 * x2 + a1 * y1 + a2 * y2
            if rounding:
                acc += 1 << (sh - 1)
            yn = max(-32768, min(32767, acc >> sh))
            x2, x1, y2, y1 = x1, int(xn), y1, yn
            out[n] = yn
        y = out
    return y


def snr(y, r):
    return 10 * np.log10(np.sum(r ** 2) / np.sum((y - r) ** 2))


def main():
    x = np.load(C.RESULTS / "reference.npz")["x"].astype(np.int64)
    sos0 = C.design_iir_sos(2)
    cm = C.sos_to_cmsis(sos0); ps = C.choose_post_shift(cm)
    lsb = 2.0 ** (ps - 15)
    print(f"Butterworth order 2 + notch, postShift = {ps}  ->  one coefficient LSB = {lsb:.3e}\n")
    print(f"{'section':>7} {'A(1)=1+a1+a2':>14} {'DC gain 1/A(1)':>15} {'A(1)/LSB':>10}   comment")
    for i, s in enumerate(sos0):
        a1_, a2_ = s[4], s[5]
        A1 = 1 + a1_ + a2_
        print(f"{i:7d} {A1:14.3e} {1 / A1:15.1f} {A1 / lsb:10.1f}   "
              f"{'<-- poles ~ 0.5 Hz: A(1) is only a few LSBs: unrepresentable' if A1 / lsb < 10 else ''}")
    print("\nSNR vs float64 (bit-exact Q15 model):")
    print(f"{'structure':24s} {'scaling':>7s} {'arithmetic':>11s} {'SNR dB':>8s} {'bias LSB':>9s}")
    for label, design in (("Butterworth+notch", C.design_iir_sos(2)), ("hp1 (1st-order HPs)", C.design_iirh_sos(2))):
        r = C.ref_iir(x, design)
        for scale in ("none", "linf"):
            s = C.scale_sos_linf(design) if scale == "linf" else design
            c = C.sos_to_cmsis(s); p = C.choose_post_shift(c)
            for rnd in (False, True):
                y = df1_q15(x, c, p, rnd)
                print(f"{label:24s} {scale:>7s} {'round' if rnd else 'truncate':>11s} {snr(y, r):8.2f} {np.mean(y - r):9.1f}")


if __name__ == "__main__":
    main()
