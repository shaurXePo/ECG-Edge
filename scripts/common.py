"""common.py - shared helpers for the ECG-Edge Python scripts.

Everything that must agree between the Python reference and the C firmware lives here:
  * the sampling rate, full-scale convention and filter specification,
  * the quantisation rules (float -> Q15 / Q31, CMSIS coefficient layout, postShift),
  * the parser for the CSV log produced by the firmware.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
from scipy import signal

# --------------------------------------------------------------------------------------
# Specification (the ONE place these numbers are defined; export_headers.py copies them
# into C headers so firmware and reference can never silently disagree).
# --------------------------------------------------------------------------------------
FS_HZ = 360                    # MIT-BIH sampling rate [Hz]
FULLSCALE_MV = 5.0             # Q15 full scale = +/-5 mV  (1 LSB = 5000 uV / 32768 = 0.1526 uV)
LSB_UV = FULLSCALE_MV * 1000.0 / 32768.0
BP_LO_HZ, BP_HI_HZ = 0.5, 40.0 # monitoring-style ECG band (narrower than diagnostic bandwidths)
NOTCH_HZ, NOTCH_Q = 60.0, 30.0 # US mains used when MIT-BIH was recorded; Q=30 -> ~2 Hz wide
PT_LO_HZ, PT_HI_HZ = 5.0, 15.0 # Pan-Tompkins QRS-energy band
PT_ORDER = 2                   # Butterworth order of the PT band-pass -> 2 biquad sections
DEFAULT_FIR_TAPS = (63, 127, 255)
DEFAULT_IIR_ORDERS = (2, 4)
Q15_MIN, Q15_MAX = -32768, 32767
Q31_MIN, Q31_MAX = -(2 ** 31), 2 ** 31 - 1

# MIT-BIH annotation symbols that denote an actual heartbeat (everything else is a
# rhythm change / noise marker and must NOT count as a beat when scoring R-peak detection).
BEAT_SYMBOLS = set("NLRBAaJSVrFejnE/fQ?")

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "results"
DATA_DIR = REPO / "data"


# --------------------------------------------------------------------------------------
# ECG source
# --------------------------------------------------------------------------------------
def synth_ecg(seconds: float, fs: int = FS_HZ, hr_bpm: float = 72.0, seed: int = 1):
    """Synthetic ECG (sum of Gaussians per beat + wander + mains + EMG noise).

    ONLY for smoke-testing the toolchain when PhysioNet is unreachable.  Never report
    results obtained on this signal as 'MIT-BIH results'.
    """
    rng = np.random.default_rng(seed)
    n = int(round(seconds * fs))
    t = np.arange(n) / fs
    x = np.zeros(n)
    # (centre [s], amplitude [mV], width [s]) of P, Q, R, S, T waves relative to the R peak
    waves = [(-0.20, 0.12, 0.025), (-0.035, -0.12, 0.010), (0.0, 1.10, 0.012),
             (0.035, -0.25, 0.012), (0.27, 0.30, 0.050)]
    r_times, tb = [], 0.35
    while tb < seconds - 0.4:
        r_times.append(tb)
        tb += (60.0 / hr_bpm) * (1.0 + 0.05 * rng.standard_normal())
    for tr in r_times:
        for c, a, w in waves:
            x += a * np.exp(-0.5 * ((t - tr - c) / w) ** 2)
    x += 0.30 * np.sin(2 * np.pi * 0.30 * t) + 0.15 * np.sin(2 * np.pi * 0.10 * t + 1.0)  # baseline wander
    x += 0.10 * np.sin(2 * np.pi * 60.0 * t)                                              # mains
    x += 0.02 * rng.standard_normal(n)                                                    # EMG-like noise
    ann = np.round(np.array(r_times) * fs).astype(int)
    return x, ann, np.array(["N"] * len(ann))


def load_ecg(source: str, record: str = "100", seconds: float = 10.0, start_s: float = 0.0,
             data_dir: Path = DATA_DIR):
    """Return dict(x_mv, ann_samples, ann_symbols, name) for the requested segment.

    source = 'wfdb'      : MIT-BIH via the wfdb package (downloads into data/ on first use)
             'synthetic' : built-in generator (smoke tests only)
    """
    if source == "synthetic":
        x, a, s = synth_ecg(seconds)
        return dict(x_mv=x, ann_samples=a, ann_symbols=s, name=f"SYNTHETIC {seconds:g}s")
    if source != "wfdb":
        raise ValueError(f"unknown source {source!r}")
    import wfdb  # imported lazily so synthetic mode works without it

    data_dir = Path(data_dir) / "mitdb"
    data_dir.mkdir(parents=True, exist_ok=True)
    need = [f"{record}.dat", f"{record}.hea", f"{record}.atr"]
    if not all((data_dir / f).exists() for f in need):
        print(f"[load_ecg] downloading {need} from PhysioNet mitdb -> {data_dir}")
        wfdb.dl_files("mitdb", str(data_dir), need)
    s0 = int(round(start_s * FS_HZ))
    s1 = s0 + int(round(seconds * FS_HZ))
    rec = wfdb.rdrecord(str(data_dir / record), sampfrom=s0, sampto=s1, channels=[0])
    if int(rec.fs) != FS_HZ:
        raise RuntimeError(f"record fs={rec.fs}, expected {FS_HZ}")
    # Read ALL annotations, then slice ourselves (avoids version-dependent offset semantics).
    ann = wfdb.rdann(str(data_dir / record), "atr")
    m = (ann.sample >= s0) & (ann.sample < s1)
    return dict(x_mv=rec.p_signal[:, 0].astype(float), ann_samples=ann.sample[m] - s0,
                ann_symbols=np.array(ann.symbol)[m],
                name=f"mitdb/{record} {rec.sig_name[0]} start={start_s:g}s len={seconds:g}s")


def quantize_input(x_mv: np.ndarray) -> np.ndarray:
    """mV -> int16 (Q15 with +/-FULLSCALE_MV full scale). Rounds to nearest, clips at the rails."""
    q = np.round(np.asarray(x_mv) / FULLSCALE_MV * 32768.0)
    return np.clip(q, Q15_MIN, Q15_MAX).astype(np.int16)


# --------------------------------------------------------------------------------------
# Filter design (double precision "golden" designs)
# --------------------------------------------------------------------------------------
def design_fir(ntaps: int) -> np.ndarray:
    """Hamming windowed-sinc band-pass, ntaps must be odd (type-I linear phase)."""
    if ntaps % 2 == 0:
        raise ValueError("ntaps must be odd")
    return signal.firwin(ntaps, [BP_LO_HZ, BP_HI_HZ], pass_zero=False, window="hamming", fs=FS_HZ)


def design_iir_sos(order: int, with_notch: bool = True) -> np.ndarray:
    """Butterworth band-pass (order -> `order` biquads) followed by an optional 60 Hz notch biquad."""
    sos = signal.butter(order, [BP_LO_HZ, BP_HI_HZ], btype="bandpass", fs=FS_HZ, output="sos")
    if with_notch:
        b, a = signal.iirnotch(NOTCH_HZ, NOTCH_Q, fs=FS_HZ)
        sos = np.vstack([sos, signal.tf2sos(b, a)])
    return sos


# Q15-friendly alternative ("hp1" structure).  A 2nd-order Butterworth high-pass at 0.5 Hz / 360 Hz
# has poles at radius 0.991: 1+a1+a2 = 7.7e-5 is SMALLER than the Q14 coefficient step (6.1e-5),
# so a 16-bit direct-form section cannot represent it (see README / scripts/diagnose_q15_iir.py).
# Two cascaded FIRST-order high-passes have real poles at R=0.994 whose Q15 error is only ~0.3 %.
# fc is lowered so the *cascade* is still -3 dB at 0.5 Hz:  fc = 0.5 * sqrt(sqrt(2) - 1).
HP1_FC_HZ = BP_LO_HZ * math.sqrt(math.sqrt(2.0) - 1.0)


def design_iirh_sos(lp_order: int = 2) -> np.ndarray:
    """[1st-order HP, 1st-order HP, Butterworth LP 40 Hz (lp_order), 60 Hz notch] as SOS rows.
    First-order sections are stored as biquads with b2 = a2 = 0."""
    hp = signal.butter(1, HP1_FC_HZ, btype="highpass", fs=FS_HZ, output="sos")
    lp = signal.butter(lp_order, BP_HI_HZ, btype="lowpass", fs=FS_HZ, output="sos")
    b, a = signal.iirnotch(NOTCH_HZ, NOTCH_Q, fs=FS_HZ)
    return np.vstack([hp, hp, lp, signal.tf2sos(b, a)])


def design_pt_sos() -> np.ndarray:
    return signal.butter(PT_ORDER, [PT_LO_HZ, PT_HI_HZ], btype="bandpass", fs=FS_HZ, output="sos")


def sos_peak_gains(sos: np.ndarray, n: int = 8192) -> np.ndarray:
    w = np.linspace(0, np.pi, n)
    return np.array([np.max(np.abs(signal.sosfreqz(s[None, :], worN=w)[1])) for s in sos])


def scale_sos_linf(sos: np.ndarray) -> np.ndarray:
    """L-infinity section scaling (keeps the cascade transfer function IDENTICAL).

    Each section's numerator is divided by that section's peak gain, so no internal node can
    exceed the input amplitude for a narrow-band signal; the product of the removed gains is
    put back in the LAST section's numerator.  Rationale: Q15 has no headroom, so we keep every
    intermediate signal as large as safely possible (more bits used -> less relative
    quantisation noise) and also never let an inner node clip.
    """
    g = sos_peak_gains(sos)
    out = sos.copy()
    out[:, :3] = out[:, :3] / g[:, None]
    out[-1, :3] *= float(np.prod(g))
    return out


def sos_to_cmsis(sos: np.ndarray) -> np.ndarray:
    """scipy row [b0 b1 b2 1 a1 a2]  ->  CMSIS row [b0 b1 b2 -a1 -a2].

    CMSIS evaluates  y[n] = b0 x[n] + b1 x[n-1] + b2 x[n-2] + a1' y[n-1] + a2' y[n-2]
    i.e. the feedback coefficients are stored with their sign flipped w.r.t. the textbook /
    scipy convention  y[n] = ... - a1 y[n-1] - a2 y[n-2].
    """
    return np.column_stack([sos[:, 0], sos[:, 1], sos[:, 2], -sos[:, 4], -sos[:, 5]])


def choose_post_shift(coefs: np.ndarray) -> int:
    """Smallest postShift p >= 0 such that every coefficient fits in the format
    Q(1+p).(15-p)  i.e. |c| < 2**p.   Real value of a stored integer q is  q * 2**p / 2**15."""
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


def dequant(q: np.ndarray, total_bits: int, post_shift: int = 0) -> np.ndarray:
    return np.asarray(q, dtype=float) / 2.0 ** (total_bits - 1 - post_shift)


def q15_biquad_layout(cm: np.ndarray, post_shift: int) -> np.ndarray:
    """CMSIS arm_biquad_cascade_df1_q15 wants SIX values per stage: {b0, 0, b1, b2, a1, a2}.
    (The padding zero lets the Cortex-M4 SIMD code load b0 and 0 as one 32-bit word.)"""
    q = quant(cm, 16, post_shift)
    return np.column_stack([q[:, 0], np.zeros(len(q), dtype=np.int64), q[:, 1], q[:, 2], q[:, 3], q[:, 4]])


def fir_to_cmsis_q15(h: np.ndarray):
    """Pad to even length (arm_fir_q15 on Cortex-M4 requires an even numTaps), reverse (CMSIS
    stores b[N-1] ... b[0]) and quantise to Q15.  Returns (q15 array, padded_len)."""
    hp = np.append(h, 0.0) if len(h) % 2 else h.copy()
    return quant(hp[::-1], 16), len(hp)


def fir_to_cmsis_f32(h: np.ndarray):
    hp = np.append(h, 0.0) if len(h) % 2 else h.copy()
    return hp[::-1].astype(np.float32), len(hp)


# --------------------------------------------------------------------------------------
# Golden (float64) reference filters on the *quantised* int16 input
# --------------------------------------------------------------------------------------
def ref_fir(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    return np.convolve(x.astype(float), h)[: len(x)]          # zero initial state, causal


def ref_iir(x: np.ndarray, sos: np.ndarray) -> np.ndarray:
    return signal.sosfilt(sos, x.astype(float))               # zero initial state, causal


def group_delay_samples(sos: np.ndarray, f_hz: float) -> float:
    """Group delay of an SOS cascade at f_hz, in samples (sum over sections)."""
    w = 2 * np.pi * f_hz / FS_HZ
    tot = 0.0
    for s in sos:
        _, gd = signal.group_delay((s[:3], s[3:]), w=[w])
        tot += float(gd[0])
    return tot


# --------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------
def error_metrics(y: np.ndarray, ref: np.ndarray, skip: int = 0) -> dict:
    """SNR of an implementation vs the float64 reference, all in int16-LSB units.

    SNR_dB    = 10*log10( sum(ref^2) / sum((y-ref)^2) )              total error (includes DC bias)
    SNR_ac_dB = same with the MEAN of the error removed: a constant offset is harmless for an
                AC-coupled ECG, so this is the more clinically relevant number when bias dominates.
    """
    y = np.asarray(y, dtype=float)[skip:]
    r = np.asarray(ref, dtype=float)[skip:]
    e = y - r
    num, den = float(np.sum(r * r)), float(np.sum(e * e))
    snr = 10 * math.log10(num / den) if den > 0 else float("inf")
    e_ac = e - np.mean(e)                       # error with its DC component removed
    den_ac = float(np.sum(e_ac * e_ac))
    snr_ac = 10 * math.log10(num / den_ac) if den_ac > 0 else float("inf")
    return dict(snr_db=snr, snr_ac_db=snr_ac, max_abs_err=float(np.max(np.abs(e))),
                rms_err=float(np.sqrt(np.mean(e * e))), mean_err=float(np.mean(e)))


def ideal_q15_snr(ref: np.ndarray, skip: int = 0) -> float:
    """Best SNR any int16-output implementation could reach: round the exact result to integers."""
    return error_metrics(np.round(ref), ref, skip)["snr_db"]


def sha1_int16(x: np.ndarray) -> str:
    return hashlib.sha1(np.asarray(x, dtype="<i2").tobytes()).hexdigest()


# --------------------------------------------------------------------------------------
# MCU / host log parser
# --------------------------------------------------------------------------------------
def parse_log(path: str | Path) -> dict:
    """Parse the CSV log emitted by the firmware (UART capture, semihosting or host stdout).

    Line grammar (see firmware/src/ecg_app.c):
      #META,key,value
      #BEGIN,name,fmt,count  ... idx,value ... #END,name
      #STAT,name,samples,blocks,block,total_cycles,max_block_cycles,min_block_cycles,rail_hits
      #SWEEP,<same fields as #STAT>
      #PEAK,idx          #STACK,used,total
    Any other line (boot garbage, partial lines) is ignored.
    """
    out = dict(meta={}, stats={}, sweep=[], series={}, peaks=[], stack=None, done=False)
    cur, buf = None, None
    stat_keys = ["samples", "blocks", "block", "total_cycles", "max_block_cycles", "min_block_cycles", "rail_hits"]
    for raw in Path(path).read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            f = line[1:].split(",")
            tag = f[0]
            try:
                if tag == "META":
                    out["meta"][f[1]] = ",".join(f[2:])
                elif tag == "BEGIN":
                    # samples are stored BY INDEX: a byte lost on the UART leaves a NaN hole
                    # (detected by validate.py) instead of silently shifting the whole series.
                    cur, buf = f[1], np.full(int(f[3]), np.nan)
                elif tag == "END":
                    if cur == f[1]:
                        out["series"][cur] = buf
                    cur = None
                elif tag in ("STAT", "SWEEP"):
                    d = dict(name=f[1], **{k: int(v) for k, v in zip(stat_keys, f[2:])})
                    if tag == "STAT":
                        out["stats"][f[1]] = d
                    else:
                        out["sweep"].append(d)
                elif tag == "PEAK":
                    out["peaks"].append(int(f[1]))
                elif tag == "STACK":
                    out["stack"] = (int(f[1]), int(f[2]))
                elif tag == "DONE":
                    out["done"] = True
            except (ValueError, IndexError):
                continue                                   # corrupted line (UART glitch) -> skip
        elif cur is not None and re.fullmatch(r"\d+,-?\d+(\.\d+)?", line):
            i, v = line.split(",")
            if int(i) < len(buf):
                buf[int(i)] = float(v)
    return out


def save_json(path: Path, obj) -> None:
    Path(path).write_text(json.dumps(obj, indent=2, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
