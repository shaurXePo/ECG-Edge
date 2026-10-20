#!/usr/bin/env python3
"""Convert a trained PyTorch checkpoint to the NumPy file the web app uses, and PROVE they agree.

    python scripts/export_numpy.py --ckpt runs/rr_v3/model.pt --out models/rr_v3.npz

Folds BatchNorm into the convolutions, saves float32 arrays, then runs 256 random inputs through both
the PyTorch model and the NumPy model and exits with an error if logits differ by more than 1e-3.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ecg_edge_ml.model import TinyECGNet  # noqa: E402
from ecg_edge_ml.numpy_infer import NumpyNet, from_torch_state_dict  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="runs/rr_v3/model.pt")
    ap.add_argument("--out", default="models/rr_v3.npz")
    args = ap.parse_args()

    ck = torch.load(args.ckpt, map_location="cpu", weights_only=True)
    n_rr = int(ck["n_rr"])
    model = TinyECGNet(width=ck["width"], n_rr=n_rr)
    model.load_state_dict(ck["state_dict"])
    model.eval()
    net = NumpyNet(from_torch_state_dict({k: v.numpy() for k, v in model.state_dict().items()}, n_rr))

    g = torch.Generator().manual_seed(0)
    x = torch.randn(256, 1, 256, generator=g) * 0.5
    rr = torch.rand(256, n_rr, generator=g) * 2.0 if n_rr else None
    with torch.no_grad():
        ref = model(x, rr).numpy()
    got = net.forward(x[:, 0, :].numpy(), None if rr is None else rr.numpy())
    diff = float(np.abs(ref - got).max())
    print(f"max |torch - numpy| logit difference over 256 random inputs: {diff:.2e}")
    if diff > 1e-3:
        sys.exit("MISMATCH: do not use this file")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    net.save(args.out)
    print(f"wrote {args.out} ({Path(args.out).stat().st_size / 1024:.0f} KB), n_rr={n_rr}, "
          f"trained on filter {ck.get('train_filter')}")


if __name__ == "__main__":
    main()
