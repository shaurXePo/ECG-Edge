"""train.py - train TinyECGNet on DS1 (minus validation records), test on DS2.

    python -m ecg_edge_ml.train --out runs/rr                 # with RR features (default)
    python -m ecg_edge_ml.train --no-rr --out runs/baseline   # beat shape only (the M1 baseline)
    python -m ecg_edge_ml.train --synthetic --epochs 3        # offline smoke test (numbers meaningless)
    python -m ecg_edge_ml.train --weight-power 0.3 --out runs/rr_w03

Change ONE thing per run so differences can be attributed: --no-rr vs default isolates the RR
features; --weight-power isolates the class weighting; --seed measures run-to-run noise.
The model is trained on beats from ONE filter (default: float64 127-tap FIR) and later tested on
beats from every other filter variant.  Everything is seeded; CPU only.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from . import data as D
from .dsp import make_filter
from .metrics import confusion, macro_f1, per_class, report
from .model import TinyECGNet, count_params
from .synthetic import synthetic_record


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


@torch.no_grad()
def predict_logits(model: torch.nn.Module, X_crop: np.ndarray, rr: np.ndarray | None, batch: int = 1024) -> np.ndarray:
    """X_crop: (n, WIN) mV windows (already cropped); rr: (n, N_RR) or None. Returns (n, 4) logits."""
    model.eval()
    out = []
    for i in range(0, len(X_crop), batch):
        xb = torch.from_numpy(D.prep(X_crop[i:i + batch])).unsqueeze(1)
        rb = torch.from_numpy(rr[i:i + batch]).float() if (model.n_rr and rr is not None) else None
        out.append(model(xb, rb).numpy())
    return np.concatenate(out) if out else np.zeros((0, len(D.CLASSES)), np.float32)


def evaluate(model, X_windows, y, rr) -> np.ndarray:
    """Confusion matrix on CENTRE-cropped windows (X_windows still has the margins)."""
    logits = predict_logits(model, D.center_crop(X_windows), rr)
    return confusion(y, logits.argmax(axis=1))


def synthetic_beats(seeds, flt):
    Xs, ys, Fs = [], [], []
    for s in seeds:
        X, y, Fr, _ = D.beats_and_rr(synthetic_record(seed=s), flt)
        Xs.append(X); ys.append(y); Fs.append(Fr)
    return np.concatenate(Xs), np.concatenate(ys), np.concatenate(Fs)


def load_splits(args, flt):
    """Returns (Xtr, ytr, Ftr), (Xva, yva, Fva), (Xte, yte, Fte)."""
    if args.synthetic:
        print("SYNTHETIC data (smoke test only; numbers are meaningless)")
        return synthetic_beats(range(0, 6), flt), synthetic_beats(range(6, 8), flt), synthetic_beats(range(8, 10), flt)
    kw = dict(flt=flt, data_dir=args.data_dir, cache_dir=args.cache_dir)
    print("train records:", D.TRAIN_RECORDS)
    Xtr, ytr, Ftr, _ = D.build_beats(D.TRAIN_RECORDS, **kw)
    print("validation records:", D.VAL_RECORDS)
    Xva, yva, Fva, _ = D.build_beats(D.VAL_RECORDS, **kw)
    print("test records (DS2):", D.TEST_RECORDS)
    Xte, yte, Fte, _ = D.build_beats(D.TEST_RECORDS, **kw)
    return (Xtr, ytr, Ftr), (Xva, yva, Fva), (Xte, yte, Fte)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="data/mitdb")
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--train-filter", default="fir127_f64", help="filter used to make the TRAINING beats")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--width", type=int, default=8)
    ap.add_argument("--weight-power", type=float, default=0.5,
                    help="class weight = (1/frequency)**p; 0 = unweighted, 0.5 = baseline, 1 = full inverse")
    ap.add_argument("--no-rr", action="store_true", help="do not use RR-interval features (M1 baseline)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="runs/rr")
    ap.add_argument("--synthetic", action="store_true", help="offline smoke test on made-up ECG")
    args = ap.parse_args()

    set_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n_rr = 0 if args.no_rr else D.N_RR

    flt = make_filter(args.train_filter)
    (Xtr, ytr, Ftr), (Xva, yva, Fva), (Xte, yte, Fte) = load_splits(args, flt)
    counts = np.bincount(ytr, minlength=len(D.CLASSES))
    print("train beats per class:", dict(zip(D.CLASSES, counts.tolist())))
    print("val   beats per class:", dict(zip(D.CLASSES, np.bincount(yva, minlength=4).tolist())))
    print("test  beats per class:", dict(zip(D.CLASSES, np.bincount(yte, minlength=4).tolist())))
    print(f"RR features: {'ON' if n_rr else 'OFF'}   class-weight power: {args.weight_power}")

    w = (counts.sum() / np.maximum(counts, 1)) ** args.weight_power
    w = torch.tensor(w / w.mean(), dtype=torch.float32)
    print("class weights:", [round(float(v), 2) for v in w])

    model = TinyECGNet(width=args.width, n_rr=n_rr)
    print("trainable parameters:", count_params(model))
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)

    best_f1, best_state, history = -1.0, None, []
    for epoch in range(1, args.epochs + 1):
        model.train()
        perm = rng.permutation(len(Xtr))
        total, n_batches = 0.0, 0
        for i in range(0, len(perm), args.batch_size):
            idx = perm[i:i + args.batch_size]
            if len(idx) < 2:                      # BatchNorm needs more than one sample
                continue
            xb = torch.from_numpy(D.prep(D.random_crop(Xtr[idx], rng))).unsqueeze(1)
            rb = torch.from_numpy(Ftr[idx]).float() if n_rr else None
            yb = torch.from_numpy(ytr[idx])
            loss = F.cross_entropy(model(xb, rb), yb, weight=w)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss.item()); n_batches += 1
        sched.step()
        cm_val = evaluate(model, Xva, yva, Fva)
        f1 = macro_f1(cm_val)
        history.append(dict(epoch=epoch, train_loss=total / max(n_batches, 1), val_macro_f1=f1))
        print(f"epoch {epoch:3d}  train loss {total / max(n_batches, 1):.4f}  val macro-F1 {f1:.4f}")
        if f1 > best_f1:
            best_f1, best_state = f1, copy.deepcopy(model.state_dict())

    model.load_state_dict(best_state)
    cm_test = evaluate(model, Xte, yte, Fte)
    print(f"\nBEST val macro-F1 {best_f1:.4f}.  TEST (DS2, filter = {args.train_filter}, RR = {bool(n_rr)}):")
    print(report(cm_test))

    torch.save(dict(state_dict=model.state_dict(), width=args.width, n_rr=n_rr, classes=D.CLASSES,
                    train_filter=args.train_filter, seed=args.seed, weight_power=args.weight_power),
               out / "model.pt")
    m = per_class(cm_test)
    nan2none = lambda a: [None if np.isnan(v) else float(v) for v in a]
    (out / "metrics.json").write_text(json.dumps(dict(
        train_filter=args.train_filter, seed=args.seed, synthetic=args.synthetic, rr=bool(n_rr),
        weight_power=args.weight_power, best_val_macro_f1=best_f1, test_confusion=cm_test.tolist(),
        test_accuracy=m["accuracy"], test_se=nan2none(m["se"]), test_ppv=nan2none(m["ppv"]),
        test_f1=nan2none(m["f1"]), history=history), indent=2))
    print(f"saved {out / 'model.pt'} and {out / 'metrics.json'}")


if __name__ == "__main__":
    main()
