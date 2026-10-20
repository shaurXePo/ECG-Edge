"""experiment.py - does the ECG filter implementation change what a FIXED classifier predicts?

    python -m ecg_edge_ml.experiment --model runs/rr_v3/model.pt

ONE trained model (trained on float64 127-tap FIR beats) is scored on DS2 beats produced by many
filters.  Nothing is retrained, so any difference between rows comes from the filter alone, not
from a different training run or epoch.

Fair comparisons: a fixed-point filter should be judged against its OWN float twin
(fir127_q15 vs fir127_f64, iir2_q15 vs iir2_f64, ...).  Comparing an IIR with the FIR-trained
model also changes the filter's shape (a different frequency/phase response), which is not a
fixed-point effect.  So we report both: "agree_ref" (vs the FIR reference the model knows) and
"agree_twin" (vs the float version of the same design).

Metrics: accuracy; V and S sensitivity/precision at the model's own threshold; one-vs-rest
ROC-AUC for V and S (threshold-free); and agreement = fraction of beats whose predicted class
is unchanged.  F is omitted: ~400 beats from two patients cannot support a comparison.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import torch

from . import data as D
from .dsp import FLOAT_TWIN, make_filter
from .metrics import confusion, per_class, roc_auc, softmax
from .model import TinyECGNet
from .train import predict_logits

DEFAULT_FILTERS = ["fir127_f64", "fir127_q15", "fir127_q15r", "fir63_f64",
                   "iir2_f64", "iir2_q15", "iirh_f64", "iirh_q15", "iirh_q15r", "raw"]
TWINS = FLOAT_TWIN


def load_model(path: str) -> TinyECGNet:
    ck = torch.load(path, map_location="cpu", weights_only=True)      # our own file: plain tensors + ints
    model = TinyECGNet(width=ck["width"], n_rr=ck["n_rr"])
    model.load_state_dict(ck["state_dict"])
    return model.eval()


def beats_for_filter(flt, records, data_dir, cache_dir):
    """X, y, F, keys for several records (cached per filter and record)."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    Xs, ys, Fs, ks = [], [], [], []
    for rec_id in records:
        f = cache / f"exp_{flt.name}_{rec_id}.npz"
        if f.exists():
            d = np.load(f)
            X, y, Fr, r = d["X"], d["y"], d["F"], d["r"]
        else:
            X, y, Fr, r = D.beats_and_rr(D.load_record(rec_id, data_dir), flt)
            np.savez_compressed(f, X=X, y=y, F=Fr, r=r)
        Xs.append(X); ys.append(y); Fs.append(Fr); ks.append(D.beat_keys(rec_id, r))
    return np.concatenate(Xs), np.concatenate(ys), np.concatenate(Fs), np.concatenate(ks)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="runs/rr_v3/model.pt")
    ap.add_argument("--filters", nargs="+", default=DEFAULT_FILTERS, help="first one is the reference")
    ap.add_argument("--data-dir", default="data/mitdb")
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--out", default="results/filter_experiment")
    args = ap.parse_args()

    model = load_model(args.model)
    data = {}
    for name in args.filters:
        print(f"building DS2 beats: {name}", flush=True)
        data[name] = beats_for_filter(make_filter(name), D.TEST_RECORDS, args.data_dir, args.cache_dir)

    masks = D.common_masks([data[n][3] for n in args.filters])
    ref_y = data[args.filters[0]][1][masks[0]]
    preds, probs, ys = {}, {}, {}
    for name, m in zip(args.filters, masks):
        X, y, Fr, _ = data[name]
        X, y, Fr = X[m], y[m], Fr[m]
        assert np.array_equal(y, ref_y), "labels differ between filters: beat alignment bug"
        logits = predict_logits(model, D.center_crop(X), Fr)
        preds[name], probs[name], ys[name] = logits.argmax(axis=1), softmax(logits), y
    n = len(ref_y)
    print(f"\n{n} beats common to all {len(args.filters)} filters; "
          f"V = {int((ref_y == 2).sum())}, S = {int((ref_y == 1).sum())}\n")

    rows = []
    for name in args.filters:
        pm = per_class(confusion(ys[name], preds[name]))
        rows.append(dict(
            filter=name, acc=pm["accuracy"], V_se=pm["se"][2], V_ppv=pm["ppv"][2],
            V_auc=roc_auc(ys[name] == 2, probs[name][:, 2]),
            S_se=pm["se"][1], S_auc=roc_auc(ys[name] == 1, probs[name][:, 1]),
            agree_ref=float(np.mean(preds[name] == preds[args.filters[0]])),
            agree_twin=float(np.mean(preds[name] == preds[TWINS[name]])) if TWINS.get(name) in preds else float("nan")))

    cols = ["filter", "acc", "V_se", "V_ppv", "V_auc", "S_se", "S_auc", "agree_ref", "agree_twin"]
    print(f"{cols[0]:13s}" + "".join(f"{c:>11s}" for c in cols[1:]))
    for r in rows:
        print(f"{r['filter']:13s}" + "".join(f"{r[c]:11.3f}" for c in cols[1:]))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "results.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader(); w.writerows(rows)
    print(f"\nsaved {out / 'results.csv'}   (model: {args.model}, n = {n} beats)")


if __name__ == "__main__":
    main()
