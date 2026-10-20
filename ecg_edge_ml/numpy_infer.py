"""numpy_infer.py - run TinyECGNet with NumPy only (no PyTorch), for the web app and for int8 prep.

Why: Streamlit Community Cloud installs requirements on every deploy; PyTorch is ~200 MB+ and slow.
This ~4-8 k-parameter network is tiny, so a NumPy forward pass is instant.

BatchNorm folding (inference):   BN(conv(x)) = gamma * (conv(x) - mean) / sqrt(var + eps) + beta
    = conv'(x) + b'   with   w' = w * s,   b' = beta - mean * s,   s = gamma / sqrt(var + eps).
So each conv+BN pair becomes ONE conv with a bias; this is exactly what the firmware will do too.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .data import prep

BN_EPS = 1e-5                      # PyTorch BatchNorm1d default


def conv1d(x: np.ndarray, w: np.ndarray, b: np.ndarray, stride: int, pad: int) -> np.ndarray:
    """PyTorch-style Conv1d (cross-correlation, zero padding). x (B,Cin,L), w (Cout,Cin,K), b (Cout,)."""
    xp = np.pad(x, ((0, 0), (0, 0), (pad, pad)))
    win = np.lib.stride_tricks.sliding_window_view(xp, w.shape[2], axis=2)[:, :, ::stride, :]   # (B,Cin,Lout,K)
    return np.einsum("bclk,ock->bol", win, w, optimize=True) + b[None, :, None]


def adaptive_avg_pool1d(x: np.ndarray, out: int) -> np.ndarray:
    """Same bin edges as torch.nn.AdaptiveAvgPool1d: [floor(i*L/out), ceil((i+1)*L/out))."""
    L = x.shape[2]
    cols = [x[:, :, (i * L) // out: -((-(i + 1) * L) // out)].mean(axis=2) for i in range(out)]
    return np.stack(cols, axis=2)


def fold_bn(w, gamma, beta, mean, var, eps: float = BN_EPS):
    s = gamma / np.sqrt(var + eps)
    return w * s[:, None, None], beta - mean * s


def from_torch_state_dict(sd: dict, n_rr: int) -> dict:
    """sd: {name: numpy array} from TinyECGNet.state_dict(). Returns the folded NumPy parameter dict."""
    p = {"n_rr": np.array(n_rr)}
    for i, (ci, bi) in enumerate([(0, 1), (3, 4), (6, 7)], start=1):
        w, b = fold_bn(sd[f"features.{ci}.weight"], sd[f"features.{bi}.weight"], sd[f"features.{bi}.bias"],
                       sd[f"features.{bi}.running_mean"], sd[f"features.{bi}.running_var"])
        p[f"conv{i}_w"], p[f"conv{i}_b"] = w.astype(np.float32), b.astype(np.float32)
    if n_rr == 0:
        p["fc1_w"], p["fc1_b"] = sd["classifier.weight"], sd["classifier.bias"]
    else:
        p["fc1_w"], p["fc1_b"] = sd["classifier.0.weight"], sd["classifier.0.bias"]
        p["fc2_w"], p["fc2_b"] = sd["classifier.2.weight"], sd["classifier.2.bias"]
    return {k: (v if k == "n_rr" else np.asarray(v, dtype=np.float32)) for k, v in p.items()}


class NumpyNet:
    def __init__(self, params: dict):
        self.p = {k: np.asarray(v) for k, v in params.items()}
        self.n_rr = int(self.p["n_rr"])

    @classmethod
    def load(cls, path) -> "NumpyNet":
        with np.load(Path(path), allow_pickle=False) as d:
            return cls({k: d[k] for k in d.files})

    def save(self, path) -> None:
        np.savez_compressed(Path(path), **self.p)

    def forward(self, x: np.ndarray, rr: np.ndarray | None = None) -> np.ndarray:
        """x: (B, 256) mean-removed mV windows; rr: (B, n_rr) or None. Returns (B, 4) logits."""
        h = np.asarray(x, dtype=np.float32)[:, None, :]
        for i, (stride, pad) in enumerate([(2, 3), (2, 2), (2, 2)], start=1):
            h = np.maximum(conv1d(h, self.p[f"conv{i}_w"], self.p[f"conv{i}_b"], stride, pad), 0.0)
        h = adaptive_avg_pool1d(h, 8).reshape(len(h), -1)               # channel-major, like torch .flatten(1)
        if self.n_rr:
            if rr is None:
                raise ValueError("model needs RR features")
            h = np.concatenate([h, np.asarray(rr, dtype=np.float32)], axis=1)
            h = np.maximum(h @ self.p["fc1_w"].T + self.p["fc1_b"], 0.0)
            return h @ self.p["fc2_w"].T + self.p["fc2_b"]
        return h @ self.p["fc1_w"].T + self.p["fc1_b"]

    def predict(self, X_crop: np.ndarray, rr: np.ndarray | None, batch: int = 2048) -> np.ndarray:
        """Same contract as train.predict_logits: raw cropped mV windows in, logits out (mean removal inside)."""
        out = [self.forward(prep(X_crop[i:i + batch]), None if rr is None else rr[i:i + batch])
               for i in range(0, len(X_crop), batch)]
        return np.concatenate(out) if out else np.zeros((0, 4), np.float32)
