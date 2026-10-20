"""metrics.py - confusion matrix and per-class sensitivity / precision (NumPy only).

Accuracy is deliberately NOT the headline number: ~90 % of MIT-BIH beats are 'N', so a model that
always says 'N' scores ~90 %.  We report, per class,
    sensitivity (recall) Se  = TP / (TP + FN)     "of the real V beats, how many did we find?"
    precision (PPV)          = TP / (TP + FP)     "of the beats we called V, how many were?"
    F1                       = harmonic mean of the two
A class with no true beats in the test set gives NaN (not 0), so it cannot silently drag a mean down.
"""
from __future__ import annotations

import numpy as np

from .data import CLASSES


def confusion(y_true, y_pred, n_classes: int = len(CLASSES)) -> np.ndarray:
    """cm[i, j] = number of beats of true class i predicted as class j."""
    cm = np.zeros((n_classes, n_classes), dtype=np.int64)
    np.add.at(cm, (np.asarray(y_true, dtype=int), np.asarray(y_pred, dtype=int)), 1)
    return cm


def _div(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return np.divide(a, b, out=np.full(a.shape, np.nan), where=b > 0)


def per_class(cm: np.ndarray) -> dict:
    tp = np.diag(cm).astype(float)
    se = _div(tp, cm.sum(axis=1))          # row sums = true counts
    ppv = _div(tp, cm.sum(axis=0))         # column sums = predicted counts
    f1 = _div(2 * se * ppv, se + ppv)
    return dict(se=se, ppv=ppv, f1=f1, accuracy=float(tp.sum() / max(cm.sum(), 1)))


def macro_f1(cm: np.ndarray) -> float:
    """Mean F1 over the classes that actually occur (NaN-safe)."""
    f1 = per_class(cm)["f1"]
    return float(np.nanmean(f1)) if np.any(~np.isnan(f1)) else 0.0


def report(cm: np.ndarray, classes=CLASSES) -> str:
    m = per_class(cm)
    lines = ["true\\pred " + " ".join(f"{c:>6s}" for c in classes) + "  |   Se    PPV     F1"]
    for i, c in enumerate(classes):
        lines.append(f"{c:>9s} " + " ".join(f"{v:6d}" for v in cm[i]) +
                     f"  | {m['se'][i]:5.3f}  {m['ppv'][i]:5.3f}  {m['f1'][i]:5.3f}")
    lines.append(f"accuracy {m['accuracy']:.4f}   macro-F1 {macro_f1(cm):.4f}   (n = {int(cm.sum())})")
    return "\n".join(lines)


# ---------------------------------------------------------------- threshold-free metrics
def softmax(logits: np.ndarray) -> np.ndarray:
    z = np.asarray(logits, dtype=np.float64)
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def roc_auc(is_pos, score) -> float:
    """One-vs-rest ROC-AUC via the Mann-Whitney U statistic (ties get average ranks).
    = P(random positive scores higher than random negative). 0.5 = chance, 1 = perfect.
    Unlike sensitivity/precision it does not depend on class weights or on where the
    decision threshold sits, so it is a steadier yardstick when comparing filters."""
    from scipy.stats import rankdata
    is_pos = np.asarray(is_pos, dtype=bool)
    n_pos, n_neg = int(is_pos.sum()), int((~is_pos).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = rankdata(np.asarray(score, dtype=np.float64))
    return float((ranks[is_pos].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def average_precision(is_pos, score) -> float:
    """Area under the precision-recall curve (step form): mean of precision at each true positive."""
    is_pos = np.asarray(is_pos, dtype=bool)
    if not is_pos.any():
        return float("nan")
    order = np.argsort(-np.asarray(score, dtype=np.float64), kind="stable")
    hit = is_pos[order]
    tp = np.cumsum(hit)
    precision_at_k = tp / np.arange(1, len(hit) + 1)
    return float(precision_at_k[hit].mean())
