"""data.py - MIT-BIH -> filtered beats -> (X, y) arrays, with an inter-patient split.

Design decisions (each one is an interview question):

1. LABELS: the 5 AAMI EC57 classes, with Q dropped.
       N = normal / bundle-branch / escape    (N L R e j)
       S = supraventricular ectopic           (A a J S)
       V = ventricular ectopic                (V E)
       F = fusion                             (F)
   Paced beats and unclassifiable beats ('/', 'f', 'Q') are skipped, and so are the four records
   that are mostly paced (102, 104, 107, 217), as is standard.

2. INTER-PATIENT SPLIT (de Chazal et al. 2004): DS1 = train, DS2 = test, 22 records each, no
   patient in both.  Splitting beats at random would put the same patient's beats in train and
   test and inflate accuracy.  A few DS1 records are held out as validation (also by record).

3. FILTER THEN CUT: the whole record goes through the (causal) ECG-Edge filter first, then beats
   are cut out - exactly what the firmware would see.  A causal filter delays the signal, so the
   window for an annotation at sample r is centred on r + delay (the filter's group delay).

4. LONGER WINDOW + RANDOM CROP: windows are cut MARGIN samples longer on each side; training
   takes a random crop (a +/-MARGIN-sample shift, simulating R-peak detection jitter from a
   real detector); evaluation takes the centre crop.

5. PER-BEAT MEAN REMOVAL, NO PER-BEAT AMPLITUDE NORMALISATION: removing the mean kills slow
   baseline offsets (and the FIR's soft 0.5 Hz edge); keeping amplitude in mV preserves
   information (PVCs are tall).  This is also trivial on a microcontroller.

6. CHANNEL: MLII chosen by NAME (record 114 stores it as the second signal).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .dsp import FS_HZ, LSB_MV, ECGFilter, quantize_input

# ---------------------------------------------------------------- classes and splits
CLASSES = ["N", "S", "V", "F"]
AAMI_MAP = {
    "N": 0, "L": 0, "R": 0, "e": 0, "j": 0,
    "A": 1, "a": 1, "J": 1, "S": 1,
    "V": 2, "E": 2,
    "F": 3,
}
EXCLUDED_RECORDS = ("102", "104", "107", "217")        # paced
DS1 = ("101", "106", "108", "109", "112", "114", "115", "116", "118", "119", "122",
       "124", "201", "203", "205", "207", "208", "209", "215", "220", "223", "230")
DS2 = ("100", "103", "105", "111", "113", "117", "121", "123", "200", "202", "210",
       "212", "213", "214", "219", "221", "222", "228", "231", "232", "233", "234")
VAL_RECORDS = ("106", "209", "215", "230")             # held out of DS1 for early stopping
TRAIN_RECORDS = tuple(r for r in DS1 if r not in VAL_RECORDS)
TEST_RECORDS = DS2

# ---------------------------------------------------------------- window geometry
PRE = 96                      # samples before the R peak  (0.267 s)
POST = 160                    # samples after the R peak   (0.444 s)
WIN = PRE + POST              # 256 samples -> three stride-2 convs give 32 positions
MARGIN = 16                   # extra samples each side for shift augmentation (+/-44 ms)
SETTLE_S = 5.0                # skip beats in the first 5 s: IIR start-up transient (0.5 Hz HP)

# ---------------------------------------------------------------- RR-interval features
BEAT_SYMBOLS = frozenset("NLRBAaJSVrFejnE/fQ?")   # every WFDB beat annotation (used to get true RR intervals)
N_RR = 4                      # [pre_rr_s, post_rr_s, pre_rr/avg, post_rr/avg]
DEFAULT_RR_S = 0.8            # used only if a record has a single beat
RR_HIST = 8                   # "avg" = mean of up to 8 RR intervals BEFORE the pre-RR interval (causal)


def split_of(record: str) -> str:
    """Which part of the inter-patient split a record belongs to (for honest labelling in the app)."""
    if record in TRAIN_RECORDS:
        return "TRAIN (DS1): the model has seen this patient"
    if record in VAL_RECORDS:
        return "VALIDATION (DS1): used to pick the best epoch"
    if record in TEST_RECORDS:
        return "TEST (DS2): unseen patient"
    return "not part of the DS1/DS2 split"


# ---------------------------------------------------------------- record loading
def load_record(record: str, data_dir: str | Path) -> dict:
    """Read one MIT-BIH record from `data_dir` (needs .dat .hea .atr). Returns x_mv (MLII) + annotations."""
    import wfdb  # lazy: tests and synthetic mode work without it

    base = str(Path(data_dir) / record)
    rec = wfdb.rdrecord(base)
    if int(rec.fs) != FS_HZ:
        raise RuntimeError(f"record {record}: fs={rec.fs}, expected {FS_HZ}")
    names = list(rec.sig_name)
    ch = names.index("MLII") if "MLII" in names else 0
    ann = wfdb.rdann(base, "atr")
    return dict(x_mv=np.nan_to_num(rec.p_signal[:, ch].astype(float)),
                ann_samples=np.asarray(ann.sample), ann_symbols=np.asarray(ann.symbol))


# ---------------------------------------------------------------- beat extraction
def extract_beats(y_mv: np.ndarray, ann_samples, ann_symbols, delay: int,
                  pre: int = PRE, post: int = POST, margin: int = MARGIN,
                  settle_s: float = SETTLE_S):
    """Cut labelled windows out of a FILTERED signal.

    Returns (X [n, pre+post+2*margin] float32 in mV, y [n] int64 class index, r [n] annotation sample).
    The window is centred on ann_sample + delay; beats whose window leaves the record, whose
    symbol is not one of N/S/V/F, or that fall inside the settling period are skipped.
    """
    length = pre + post + 2 * margin
    n = len(y_mv)
    X, lab, rr = [], [], []
    for s, sym in zip(ann_samples, ann_symbols):
        if sym not in AAMI_MAP or s < settle_s * FS_HZ:
            continue
        c = int(s) + delay
        lo = c - (pre + margin)
        hi = lo + length
        if lo < 0 or hi > n:
            continue
        X.append(y_mv[lo:hi])
        lab.append(AAMI_MAP[sym])
        rr.append(int(s))
    if not X:
        return np.zeros((0, length), np.float32), np.zeros(0, np.int64), np.zeros(0, np.int64)
    return np.asarray(X, dtype=np.float32), np.asarray(lab, dtype=np.int64), np.asarray(rr, dtype=np.int64)


def filter_and_extract(rec: dict, flt: ECGFilter, **kw):
    """mV -> int16 -> filter -> mV -> beat windows.  `rec` has x_mv, ann_samples, ann_symbols."""
    y_mv = flt.apply(quantize_input(rec["x_mv"])) * LSB_MV
    return extract_beats(y_mv, rec["ann_samples"], rec["ann_symbols"], flt.delay, **kw)


def beat_times(ann_samples, ann_symbols) -> np.ndarray:
    """Sorted sample indices of ALL beat annotations (any beat type, incl. paced/unclassifiable).
    RR intervals must use every beat: skipping a 'Q' beat would make the next RR look twice as long."""
    keep = [int(s) for s, c in zip(ann_samples, ann_symbols) if c in BEAT_SYMBOLS]
    return np.unique(np.asarray(keep, dtype=np.int64))


def rr_features(beat_samples, r_samples, fs: int = FS_HZ, hist: int = RR_HIST) -> np.ndarray:
    """4 timing features per beat, shape (n, N_RR) float32:
         pre_rr   seconds since the previous beat           (S/PVC beats come EARLY)
         post_rr  seconds until the next beat               (a compensatory pause follows a PVC)
         pre/avg  pre_rr  / mean of the `hist` RR intervals before it   (<1 = premature)
         post/avg post_rr / same mean                                    (>1 = pause)
    Edge cases: a missing neighbour copies the other one; no history -> avg = pre_rr.
    Values are clipped (RR to 0.2-3 s, ratios to 0-3) so pauses/artefacts cannot blow up the network.
    On the MCU this needs the NEXT R peak, so the decision for a beat lags by one RR (~0.8 s)."""
    b = np.sort(np.asarray(beat_samples, dtype=np.int64))
    r = np.asarray(r_samples, dtype=np.int64)
    out = np.zeros((len(r), N_RR), dtype=np.float32)
    if len(b) < 2:
        out[:] = [DEFAULT_RR_S, DEFAULT_RR_S, 1.0, 1.0]
        return out
    rr = np.diff(b) / fs                                   # rr[i] = interval between beat i and beat i+1
    idx = np.minimum(np.searchsorted(b, r), len(b) - 1)    # position of each beat in b
    for k, i in enumerate(idx):
        pre = rr[i - 1] if i >= 1 else np.nan
        post = rr[i] if i < len(rr) else np.nan
        if np.isnan(pre):
            pre = post
        if np.isnan(post):
            post = pre
        h = rr[max(0, i - 1 - hist): i - 1] if i >= 2 else rr[:0]   # intervals BEFORE the pre interval
        avg = float(h.mean()) if len(h) else pre
        out[k] = [pre, post, pre / avg, post / avg]
    out[:, :2] = np.clip(out[:, :2], 0.2, 3.0)
    out[:, 2:] = np.clip(out[:, 2:], 0.0, 3.0)
    return out


def beats_and_rr(rec: dict, flt: ECGFilter, **kw):
    """Windows + labels + RR features for one record. Returns X, y, F, r. **kw goes to extract_beats."""
    X, y, r = filter_and_extract(rec, flt, **kw)
    F = rr_features(beat_times(rec["ann_samples"], rec["ann_symbols"]), r)
    return X, y, F, r


def build_beats(records, flt: ECGFilter, data_dir: str | Path, cache_dir: str | Path | None = None,
                verbose: bool = True):
    """Beats for several records through one filter. Returns X, y, F (RR features), rec_id (array of str).

    Cached per (filter, record) because the Q15 IIR models are slow-ish Python loops.
    Old cache files without RR features are recomputed automatically.
    """
    Xs, ys, Fs, ids = [], [], [], []
    cache = Path(cache_dir) if cache_dir else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    for rec_id in records:
        f = cache / f"{flt.name}_{rec_id}.npz" if cache else None
        X = None
        if f is not None and f.exists():
            d = np.load(f)
            if "F" in d.files:
                X, y, Fr = d["X"], d["y"], d["F"]
        if X is None:
            X, y, Fr, _ = beats_and_rr(load_record(rec_id, data_dir), flt)
            if f is not None:
                np.savez_compressed(f, X=X, y=y, F=Fr)
        if verbose:
            counts = np.bincount(y, minlength=len(CLASSES)) if len(y) else np.zeros(len(CLASSES), int)
            print(f"  [{flt.name}] {rec_id}: {len(y):5d} beats  " +
                  " ".join(f"{c}={k}" for c, k in zip(CLASSES, counts)))
        Xs.append(X); ys.append(y); Fs.append(Fr); ids += [rec_id] * len(y)
    if not Xs:
        raise ValueError("no records given")
    return np.concatenate(Xs), np.concatenate(ys), np.concatenate(Fs), np.asarray(ids)


def beat_keys(rec_id: str, r) -> np.ndarray:
    """Unique id per annotated beat: record number * 10^7 + annotation sample."""
    return int(rec_id) * 10_000_000 + np.asarray(r, dtype=np.int64)


def common_masks(keys_list):
    """Different filters have different delays, so each may drop a different edge beat.
    Return one boolean mask per filter that keeps only beats present for ALL filters
    (keys must be sorted, which they are: records and samples ascend)."""
    common = keys_list[0]
    for k in keys_list[1:]:
        common = np.intersect1d(common, k)
    return [np.isin(k, common) for k in keys_list]


# ---------------------------------------------------------------- model-input preparation
def center_crop(X: np.ndarray, margin: int = MARGIN) -> np.ndarray:
    return X[:, margin: X.shape[1] - margin]


def random_crop(X: np.ndarray, rng: np.random.Generator, margin: int = MARGIN) -> np.ndarray:
    """Per-row random crop of WIN samples: a random shift in [-margin, +margin]."""
    n, length = X.shape
    win = length - 2 * margin
    off = rng.integers(0, 2 * margin + 1, size=n)
    idx = off[:, None] + np.arange(win)[None, :]
    return X[np.arange(n)[:, None], idx]


def prep(X_crop: np.ndarray) -> np.ndarray:
    """Per-beat mean removal. Amplitude stays in mV (see module docstring, point 5)."""
    X = np.asarray(X_crop, dtype=np.float32)
    return X - X.mean(axis=1, keepdims=True)
