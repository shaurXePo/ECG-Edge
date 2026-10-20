"""model.py - a tiny 1D CNN for 256-sample beat windows, optionally with RR-interval inputs (PyTorch).

Why this shape (every choice is made with the Cortex-M4 and int8 in mind):
  * Three stride-2 convolutions (kernel 7, 5, 5) do the down-sampling: 256 -> 128 -> 64 -> 32.
    No max-pool layers: strided convs are cheaper and quantise cleanly.
  * bias=False in the convs because BatchNorm follows; BN is FOLDED into the conv weights and
    bias before int8 quantisation, so it costs nothing on the device.
  * AdaptiveAvgPool1d(8) squeezes 32 -> 8 positions (pool of 4) instead of a global average:
    it keeps a coarse "where in the beat" layout (P-QRS-T order) at 8 x 32 = 256 features.
  * n_rr = 0 : one Linear 256 -> 4 (the M1 baseline).               4396 parameters at width 8.
    n_rr = 4 : the 4 RR features are concatenated with the 256 CNN features, then
               Linear(260 -> 16) - ReLU - Linear(16 -> 4).  The hidden layer lets the network combine
               "arrived early" (RR) with "narrow QRS, no P wave" (shape).          7612 parameters.
Input  : x  (batch, 1, 256) float32, per-beat mean removed, mV;  rr (batch, n_rr) float32 or None.
Output : (batch, 4) logits for [N, S, V, F].
"""
from __future__ import annotations

import torch
from torch import nn

from .data import CLASSES, WIN


class TinyECGNet(nn.Module):
    def __init__(self, n_classes: int = len(CLASSES), width: int = 8, n_rr: int = 0, hidden: int = 16):
        super().__init__()
        w = width
        self.features = nn.Sequential(
            nn.Conv1d(1, w, kernel_size=7, stride=2, padding=3, bias=False),
            nn.BatchNorm1d(w), nn.ReLU(),
            nn.Conv1d(w, 2 * w, kernel_size=5, stride=2, padding=2, bias=False),
            nn.BatchNorm1d(2 * w), nn.ReLU(),
            nn.Conv1d(2 * w, 4 * w, kernel_size=5, stride=2, padding=2, bias=False),
            nn.BatchNorm1d(4 * w), nn.ReLU(),
            nn.AdaptiveAvgPool1d(8),
        )
        feat = 4 * w * 8
        if n_rr == 0:
            self.classifier = nn.Linear(feat, n_classes)
        else:
            self.classifier = nn.Sequential(nn.Linear(feat + n_rr, hidden), nn.ReLU(),
                                            nn.Linear(hidden, n_classes))
        self.width, self.n_classes, self.n_rr, self.hidden = width, n_classes, n_rr, hidden

    def forward(self, x: torch.Tensor, rr: torch.Tensor | None = None) -> torch.Tensor:
        f = self.features(x).flatten(1)                       # (B, 256)
        if self.n_rr:
            if rr is None:
                raise ValueError("this model was built with n_rr > 0: pass the RR features")
            f = torch.cat([f, rr], dim=1)                     # (B, 256 + n_rr)
        return self.classifier(f)


def count_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


if __name__ == "__main__":
    for n_rr in (0, 4):
        m = TinyECGNet(n_rr=n_rr)
        out = m(torch.zeros(2, 1, WIN), torch.zeros(2, n_rr) if n_rr else None)
        print(f"n_rr={n_rr}: trainable parameters {count_params(m)}, output {tuple(out.shape)}")
