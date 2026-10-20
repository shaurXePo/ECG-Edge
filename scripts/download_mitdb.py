#!/usr/bin/env python3
"""Download the 44 MIT-BIH records used here (DS1 + DS2) into data/mitdb.

    python scripts/download_mitdb.py [--out data/mitdb]

Needs internet and the `wfdb` package. ~2 MB per record. Records already present are skipped.
Data licence: PhysioNet Open Data (cite Moody & Mark 2001; Goldberger et al. 2000).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ecg_edge_ml.data import DS1, DS2  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/mitdb")
    args = ap.parse_args()
    import wfdb

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for rec in DS1 + DS2:
        need = [f"{rec}.dat", f"{rec}.hea", f"{rec}.atr"]
        if all((out / f).exists() for f in need):
            print(f"{rec}: already present")
            continue
        print(f"{rec}: downloading")
        wfdb.dl_files("mitdb", str(out), need)
    print("done ->", out.resolve())


if __name__ == "__main__":
    main()
