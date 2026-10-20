#!/usr/bin/env python3
"""Cut short demo windows out of MIT-BIH records for the web app -> app/sample_ecg.npz (a few hundred KB).

    python scripts/make_app_sample.py                       # records 100 200 213 232 (all from the TEST split)
    python scripts/make_app_sample.py --records 100 119 --span 60

For each record it picks the `span`-second window with the most S/V/F beats, and stores LEAD seconds
before it so the IIR filters have settled by the time the window starts.
Data: MIT-BIH Arrhythmia Database, PhysioNet Open Data licence (Moody & Mark 2001; Goldberger et al. 2000).
Redistribution of a few short excerpts with attribution is permitted; keep the attribution in the app.
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ecg_edge_ml import data as D  # noqa: E402
from ecg_edge_ml.appcore import LEAD_S, save_samples  # noqa: E402
from ecg_edge_ml.dsp import FS_HZ  # noqa: E402


def best_window(rec, span_s, lead_s):
    n_s = len(rec["x_mv"]) / FS_HZ
    abnormal = np.array([D.AAMI_MAP.get(c, 0) > 0 for c in rec["ann_symbols"]])
    t = rec["ann_samples"] / FS_HZ
    best, best_t0 = -1, lead_s
    for t0 in np.arange(lead_s, n_s - span_s, 5.0):
        score = int(np.sum(abnormal & (t >= t0) & (t < t0 + span_s)))
        if score > best:
            best, best_t0 = score, float(t0)
    return best_t0, best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/mitdb")
    ap.add_argument("--records", nargs="+", default=["100", "200", "213", "232"])
    ap.add_argument("--span", type=float, default=60.0)
    ap.add_argument("--out", default="app/sample_ecg.npz")
    args = ap.parse_args()

    out = {}
    for name in args.records:
        rec = D.load_record(name, args.data_dir)
        t0, n_ab = best_window(rec, args.span, LEAD_S)
        a, b = int((t0 - LEAD_S) * FS_HZ), int((t0 + args.span) * FS_HZ)
        keep = (rec["ann_samples"] >= a) & (rec["ann_samples"] < b)
        out[name] = dict(x_mv=rec["x_mv"][a:b], ann_samples=rec["ann_samples"][keep] - a,
                         ann_symbols=rec["ann_symbols"][keep])
        print(f"{name}: window {t0:.0f}-{t0 + args.span:.0f} s, {n_ab} S/V/F beats  [{D.split_of(name)}]")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    save_samples(args.out, out)
    print("wrote", args.out, f"({Path(args.out).stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
