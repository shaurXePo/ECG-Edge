"""appcore.py - everything the Streamlit app computes, kept NumPy-only and testable without a browser.

The app file (app/streamlit_app.py) only draws; the logic lives here.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import data as D
from .dsp import FLOAT_TWIN, FS_HZ, LSB_MV, filter_mv, make_filter
from .metrics import softmax
from .numpy_infer import NumpyNet
from .synthetic import synthetic_record

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PATH = ROOT / "app" / "sample_ecg.npz"
MODEL_PATH = ROOT / "models" / "rr_v3.npz"
EXPERIMENT_CSV = ROOT / "results" / "filter_experiment" / "results.csv"
LEAD_S = 10.0                      # seconds of lead-in stored before each demo window (IIR warm-up; not classified)
FILTER_CHOICES = ["fir127_f64", "fir127_q15", "fir127_q15r", "fir63_f64", "iir2_f64", "iir2_q15",
                  "iirh_f64", "iirh_q15", "iirh_q15r", "raw"]


# ---------------------------------------------------------------- demo data
def save_samples(path, recs: dict) -> None:
    """recs: {name: dict(x_mv, ann_samples, ann_symbols)}  ->  one small .npz file."""
    arrays = {"records": np.array(list(recs), dtype="U16")}
    for n, r in recs.items():
        arrays[f"{n}_x"] = np.asarray(r["x_mv"], dtype=np.float32)
        arrays[f"{n}_s"] = np.asarray(r["ann_samples"], dtype=np.int32)
        arrays[f"{n}_c"] = np.asarray(r["ann_symbols"], dtype="U1")
    np.savez_compressed(path, **arrays)


def load_samples(path=SAMPLE_PATH):
    """Returns ({name: rec}, is_real). Falls back to clearly-labelled synthetic ECG if the file is absent."""
    path = Path(path)
    if path.exists():
        with np.load(path, allow_pickle=False) as d:
            recs = {str(n): dict(x_mv=d[f"{n}_x"].astype(float), ann_samples=d[f"{n}_s"].astype(np.int64),
                                 ann_symbols=d[f"{n}_c"]) for n in d["records"]}
        return recs, True
    return {f"synthetic-{i}": synthetic_record(80.0, seed=i) for i in (1, 2, 3)}, False


def load_net(path=MODEL_PATH):
    return NumpyNet.load(path) if Path(path).exists() else None


# ---------------------------------------------------------------- filtering
def filtered_mv(rec: dict, filt_name: str) -> np.ndarray:
    """Whole demo segment through one filter, output in mV (still delayed by the filter's group delay)."""
    return filter_mv(make_filter(filt_name), rec["x_mv"])


def aligned(y: np.ndarray, delay: int) -> np.ndarray:
    """Shift left by the group delay so the output lines up with the input for plotting."""
    return np.concatenate([y[delay:], np.zeros(delay)]) if delay else y


def twin_stats(y: np.ndarray, y_ref: np.ndarray, skip_s: float = LEAD_S) -> dict:
    """Error of a fixed-point output against its float twin, ignoring the warm-up. SNR is inf if identical."""
    a, b = np.asarray(y)[int(skip_s * FS_HZ):], np.asarray(y_ref)[int(skip_s * FS_HZ):]
    err = a - b
    p_err, p_ref = float(np.sum(err ** 2)), float(np.sum(b ** 2))
    snr = float("inf") if p_err == 0 else (float("-inf") if p_ref == 0 else 10 * np.log10(p_ref / p_err))
    return dict(snr_db=snr, max_abs_err_lsb=float(np.max(np.abs(err)) / LSB_MV),
                mean_err_lsb=float(np.mean(err) / LSB_MV))


# ---------------------------------------------------------------- classification
def classify_rec(rec: dict, filt_name: str, net: NumpyNet) -> dict:
    """Filter -> cut beats (after the lead-in) -> RR features -> NumPy network."""
    flt = make_filter(filt_name)
    X, y, F, r = D.beats_and_rr(rec, flt, settle_s=LEAD_S)
    Xc = D.center_crop(X)
    prob = softmax(net.predict(Xc, F if net.n_rr else None)) if len(X) else np.zeros((0, len(D.CLASSES)))
    return dict(r=r, y_true=y, pred=prob.argmax(axis=1) if len(X) else np.zeros(0, int),
                prob=prob, windows=D.prep(Xc) if len(X) else Xc, rr=F)


# ================================================================ end-to-end pipeline (no annotations needed)
from fractions import Fraction  # noqa: E402

from scipy.signal import resample_poly  # noqa: E402

from .detect import detect_r_peaks, match_peaks  # noqa: E402

UNIT_TO_MV = {"mV": 1.0, "µV": 1e-3, "V": 1e3}


def prepare_signal(values, fs: float, unit: str = "mV", max_minutes: float = 10.0) -> np.ndarray:
    """User samples -> mV at 360 Hz (resampled if needed), capped in length. Raises ValueError on junk."""
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)] * UNIT_TO_MV[unit]
    if len(x) < 10 * fs:
        raise ValueError("need at least 10 seconds of signal")
    if abs(fs - FS_HZ) > 1e-9:
        f = Fraction(FS_HZ / fs).limit_denominator(1000)
        x = resample_poly(x, f.numerator, f.denominator)
    return x[: int(max_minutes * 60 * FS_HZ)]


def amplitude_warning(x_mv: np.ndarray):
    peak = float(np.max(np.abs(x_mv)))
    if peak > 5.0:
        return f"peak {peak:.1f} mV exceeds the +/-5 mV int16 full scale and will clip: check the unit setting"
    if peak < 0.1:
        return f"peak only {peak * 1000:.0f} uV: very small for an ECG, check the unit setting"
    return None


def true_labels(r, ann_samples, ann_symbols, delay: int, tol_s: float = 0.075) -> np.ndarray:
    """Label of the annotated beat nearest to each detected peak (annotation time + filter delay), else -1.
    -1 also covers beat types outside N/S/V/F (paced, unclassifiable)."""
    keep = np.array([c in D.BEAT_SYMBOLS for c in ann_symbols], dtype=bool)
    a = np.asarray(ann_samples)[keep] + delay
    sym = np.asarray(ann_symbols)[keep]
    out = np.full(len(r), -1, dtype=np.int64)
    if len(a) == 0:
        return out
    order = np.argsort(a); a, sym = a[order], sym[order]
    for k, c in enumerate(r):
        i = int(np.searchsorted(a, c))
        cands = [j for j in (i - 1, i) if 0 <= j < len(a)]
        j = min(cands, key=lambda j: abs(int(a[j]) - int(c)))
        if abs(int(a[j]) - int(c)) <= tol_s * FS_HZ:
            out[k] = D.AAMI_MAP.get(str(sym[j]), -1)
    return out


def run_pipeline(x_mv: np.ndarray, filt_name: str, net: NumpyNet, ann=None, settle_s: float = D.SETTLE_S) -> dict:
    """raw mV @360 Hz -> int16 -> filter -> R-peak detection -> beat windows + RR features -> network.
    `ann` = dict(ann_samples, ann_symbols) is OPTIONAL and used only to score detection and label beats."""
    flt = make_filter(filt_name)
    y = filter_mv(flt, x_mv)
    r_all = detect_r_peaks(y)
    r_all = r_all[r_all >= settle_s * FS_HZ]
    length, lo_off = D.WIN + 2 * D.MARGIN, D.PRE + D.MARGIN
    ok = np.array([(c - lo_off >= 0) and (c - lo_off + length <= len(y)) for c in r_all], dtype=bool)
    r = r_all[ok]
    out = dict(y=y, delay=flt.delay, r_all=r_all, r=r, labels=None, det=None)
    if len(r) == 0:
        return {**out, "windows": np.zeros((0, D.WIN)), "prob": np.zeros((0, 4)), "pred": np.zeros(0, int),
                "rr": np.zeros((0, D.N_RR), np.float32)}
    X = np.stack([y[c - lo_off: c - lo_off + length] for c in r]).astype(np.float32)
    F = D.rr_features(r_all, r)                      # timing from ALL detected peaks, like the firmware would
    Xc = D.center_crop(X)
    prob = softmax(net.predict(Xc, F if net.n_rr else None))
    out.update(windows=D.prep(Xc), prob=prob, pred=prob.argmax(axis=1), rr=F)
    if ann is not None:
        out["labels"] = true_labels(r, ann["ann_samples"], ann["ann_symbols"], flt.delay)
        keep = np.array([c in D.BEAT_SYMBOLS for c in ann["ann_symbols"]], dtype=bool)
        truth = np.asarray(ann["ann_samples"])[keep] + flt.delay
        truth = truth[truth >= settle_s * FS_HZ]
        tp, fp, fn = match_peaks(r_all, truth, int(0.075 * FS_HZ))
        out["det"] = dict(tp=tp, fp=fp, fn=fn, sensitivity=tp / max(tp + fn, 1), ppv=tp / max(tp + fp, 1))
    return out


def occlusion_map(net: NumpyNet, window: np.ndarray, rr, cls: int, width: int = 24, stride: int = 8) -> np.ndarray:
    """Which samples does the prediction for class `cls` depend on?  Zero out `width` samples at a time
    (the window is mean-removed, so zero = baseline) and record how much P(cls) drops; per-sample value =
    mean drop over the occluding windows covering it. Positive = removing this part hurts the prediction."""
    w = np.asarray(window, dtype=np.float32)
    rr = None if not net.n_rr else np.asarray(rr, dtype=np.float32)[None, :]
    base = softmax(net.forward(w[None, :], rr))[0, cls]
    heat, cnt = np.zeros(len(w)), np.zeros(len(w))
    for s in range(0, len(w) - width + 1, stride):
        w2 = w.copy(); w2[s:s + width] = 0.0
        drop = base - softmax(net.forward(w2[None, :], rr))[0, cls]
        heat[s:s + width] += drop; cnt[s:s + width] += 1
    return heat / np.maximum(cnt, 1)


def response_pair(filt_name: str, n: int = 4096):
    """Magnitude responses (dB) of the float design and of its Q15-quantised coefficients.
    Returns (f_hz, db_float, db_fixed_or_None)."""
    from .dsp import coeffs_for, magnitude_db
    kind, cf, cq = coeffs_for(filt_name)
    f, d0 = magnitude_db(kind, cf, n)
    return f, d0, (None if cq is None else magnitude_db(kind, cq, n)[1])
