#!/usr/bin/env python3
"""plot_responses.py - what does coefficient quantisation do to the FREQUENCY RESPONSE?

Plots |H(f)| of the float64 design against the response of the quantised coefficients (Q15 /
Q31, de-quantised with the postShift rule).  This isolates coefficient error from arithmetic
(rounding / saturation) error, which validate.py measures in the time domain.

    python scripts/plot_responses.py            # -> results/freq_responses.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def sos_from_cmsis(q, bits, ps):
    """quantised CMSIS rows (b0 b1 b2 a1' a2') -> scipy sos rows [b0 b1 b2 1 a1 a2]."""
    c = C.dequant(q, bits, ps)
    return np.column_stack([c[:, 0], c[:, 1], c[:, 2], np.ones(len(c)), -c[:, 3], -c[:, 4]])


def main():
    f = np.logspace(-1.3, np.log10(C.FS_HZ / 2 - 0.5), 4000)
    w = 2 * np.pi * f / C.FS_HZ
    fig, ax = plt.subplots(2, 2, figsize=(13, 8))

    # ---- FIR ----
    a = ax[0][0]
    for n, col in zip(C.DEFAULT_FIR_TAPS, ("tab:red", "tab:green", "tab:blue")):
        h = C.design_fir(n)
        hq = C.dequant(C.quant(h, 16), 16)
        a.semilogx(f, 20 * np.log10(np.abs(signal.freqz(h, worN=w)[1]) + 1e-12), color=col, label=f"{n} taps, float64")
        a.semilogx(f, 20 * np.log10(np.abs(signal.freqz(hq, worN=w)[1]) + 1e-12), color=col, ls=":", label=f"{n} taps, Q15 coeffs")
    a.set_title("FIR band-pass: float64 vs Q15 coefficients"); a.set_ylim(-120, 5)

    # ---- Butterworth IIR ----
    a = ax[0][1]
    k = 2
    for scale, ls in (("linf", "-"), ("none", "--")):
        sos0 = C.design_iir_sos(k)
        sos = C.scale_sos_linf(sos0) if scale == "linf" else sos0
        cm = C.sos_to_cmsis(sos); ps = C.choose_post_shift(cm)
        if scale == "linf":
            a.semilogx(f, 20 * np.log10(np.abs(signal.sosfreqz(sos0, worN=w)[1]) + 1e-12), "k", lw=2, label="float64 design")
        hq = np.abs(signal.sosfreqz(sos_from_cmsis(C.quant(cm, 16, ps), 16, ps), worN=w)[1])
        a.semilogx(f, 20 * np.log10(hq + 1e-12), ls=ls, label=f"Q15 coeffs (postShift {ps}, scaling={scale})")
    a.set_title("Butterworth order 2 + notch: coefficient quantisation moves the 0.5 Hz corner"); a.set_ylim(-80, 5)

    # ---- hp1 ----
    a = ax[1][0]
    sos0 = C.design_iirh_sos(2)
    cm = C.sos_to_cmsis(sos0); ps = C.choose_post_shift(cm)
    a.semilogx(f, 20 * np.log10(np.abs(signal.sosfreqz(sos0, worN=w)[1]) + 1e-12), "k", lw=2, label="float64 design")
    a.semilogx(f, 20 * np.log10(np.abs(signal.sosfreqz(sos_from_cmsis(C.quant(cm, 16, ps), 16, ps), worN=w)[1]) + 1e-12),
               ":", label=f"Q15 coeffs (postShift {ps})")
    a.set_title("hp1 structure (2x 1st-order HP + LP + notch)"); a.set_ylim(-80, 5)

    # ---- low-frequency zoom ----
    a = ax[1][1]
    fz = np.linspace(0.05, 3.0, 600); wz = 2 * np.pi * fz / C.FS_HZ
    for label, sos0 in (("Butterworth order 2", C.design_iir_sos(2)), ("hp1", C.design_iirh_sos(2))):
        cm = C.sos_to_cmsis(sos0); ps = C.choose_post_shift(cm)
        a.plot(fz, 20 * np.log10(np.abs(signal.sosfreqz(sos0, worN=wz)[1]) + 1e-12), label=f"{label} float64")
        a.plot(fz, 20 * np.log10(np.abs(signal.sosfreqz(sos_from_cmsis(C.quant(cm, 16, ps), 16, ps), worN=wz)[1]) + 1e-12),
               ":", label=f"{label} Q15 coeffs")
    a.axvline(0.5, color="gray", lw=.8); a.set_title("Zoom 0.05-3 Hz (the 0.5 Hz corner)"); a.set_ylim(-60, 3)

    for a in ax.flat:
        a.grid(alpha=.3, which="both"); a.set_xlabel("frequency [Hz]"); a.set_ylabel("|H| [dB]"); a.legend(fontsize=7)
    fig.tight_layout(); out = C.RESULTS / "freq_responses.png"; fig.savefig(out, dpi=110)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
