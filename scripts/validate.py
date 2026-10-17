#!/usr/bin/env python3
"""validate.py - compare the firmware output against the double-precision Python reference.

    python scripts/validate.py --log results/mcu_run.log            # real board / Renode / QEMU
    python scripts/validate.py --log results/host_run.log --label host
    python scripts/validate.py --log results/mcu_run.log --cross results/host_run.log

What it does
  1. integrity : the input echoed by the MCU must equal the exported int16 vector bit for bit
  2. accuracy  : for every implementation  SNR = 10 log10( sum(ref^2) / sum((y-ref)^2) ),
                 max |error| (int16 LSB and uV), bias, and the ideal-int16 SNR ceiling
  3. timing    : cycles/sample, worst-block latency, CPU load @ fs  (only if the log has a real
                 DWT cycle counter; host/QEMU logs print 'n/a' instead of fake numbers)
  4. R peaks   : sensitivity / PPV of the fixed-point Pan-Tompkins vs MIT-BIH annotations
  5. outputs   : results/results_table.md|csv, results/summary.json, results/*.png
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def family(name: str) -> str:
    return name.split("_")[0]                       # fir127_q15m -> fir127 ; iirh_q15r -> iirh


def fmt_of(name: str) -> str:
    return name.split("_")[1]


# ------------------------------------------------------------------------------ peaks
def score_peaks(det, ann, tol):
    """Greedy nearest-neighbour matching, each annotation matched at most once."""
    det = sorted(det)
    used, tp, offs = set(), 0, []
    for a in sorted(ann):
        best, bd = None, tol + 1
        for k, d in enumerate(det):
            if k in used:
                continue
            if abs(d - a) < bd:
                best, bd = k, abs(d - a)
        if best is not None and bd <= tol:
            used.add(best); tp += 1; offs.append(det[best] - a)
    fn, fp = len(ann) - tp, len(det) - tp
    se = tp / (tp + fn) if tp + fn else float("nan")
    ppv = tp / (tp + fp) if tp + fp else float("nan")
    return dict(tp=tp, fn=fn, fp=fp, sensitivity=se, ppv=ppv,
                mean_offset_samples=float(np.mean(offs)) if offs else float("nan"),
                std_offset_samples=float(np.std(offs)) if offs else float("nan"))


# ------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", required=True, help="CSV log from the firmware (UART capture / semihosting / host stdout)")
    ap.add_argument("--reference", default=str(C.RESULTS / "reference.npz"))
    ap.add_argument("--meta", default=str(C.RESULTS / "meta.json"))
    ap.add_argument("--footprint", default=str(C.RESULTS / "footprint.csv"))
    ap.add_argument("--out-dir", default=str(C.RESULTS))
    ap.add_argument("--label", default="mcu", help="prefix for output files (mcu / host / renode ...)")
    ap.add_argument("--skip-s", type=float, default=1.0, help="ignore first N s for the 'steady-state' SNR")
    ap.add_argument("--tol-ms", type=float, default=150.0, help="R-peak match tolerance (AAMI EC57 uses 150 ms)")
    ap.add_argument("--cross", help="second log (e.g. host) to compare integer outputs bit-exactly")
    ap.add_argument("--zoom", type=float, nargs=2, default=[2.0, 5.0], help="overlay plot window [s]")
    a = ap.parse_args()

    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    log = C.parse_log(a.log)
    ref = np.load(a.reference, allow_pickle=False)
    meta = json.loads(Path(a.meta).read_text())
    fs = meta["fs_hz"]; x = ref["x"]; n = len(x)
    skip = int(a.skip_s * fs)
    problems = []

    # ---- 1. integrity ------------------------------------------------------------
    if not log["done"]:
        problems.append("log has no #DONE marker: run was truncated (UART overflow / reset / timeout)")
    if "input" in log["series"]:
        same = np.array_equal(log["series"]["input"], x)
        print(f"[integrity] input echo identical to exported vector: {same}")
        if not same:
            problems.append("input echo differs from the exported vector - stale headers? rebuild after export")
    cpu_hz = int(log["meta"].get("cpu_hz", 0)); has_cyc = log["meta"].get("has_cycle_counter", "0") == "1"
    block = int(log["meta"].get("block_size", 0))
    print(f"[meta] platform = {log['meta'].get('platform')}, cpu = {cpu_hz/1e6:.1f} MHz, block = {block}, "
          f"cycle counter = {'yes' if has_cyc else 'NO (timing columns suppressed)'}")

    # ---- footprint (optional) ----------------------------------------------------
    foot = {}
    if Path(a.footprint).exists():
        for r in csv.DictReader(open(a.footprint)):
            foot[r["impl"]] = r

    # ---- 2/3. per-implementation rows ---------------------------------------------
    rows = []
    for name, st in log["stats"].items():
        if name.startswith("pt"):
            continue
        y = log["series"].get(name)
        if y is None:
            problems.append(f"{name}: no sample series in log"); continue
        holes = int(np.isnan(y).sum())
        if holes:
            problems.append(f"{name}: {holes} samples missing (UART corruption) - results for this row are invalid")
            y = np.where(np.isnan(y), 0.0, y)
        r = ref["ref_" + family(name)]
        m = C.error_metrics(y, r); ms = C.error_metrics(y, r, skip)
        row = dict(impl=name, fmt=fmt_of(name), snr_db=m["snr_db"], snr_ac_db=m["snr_ac_db"], snr_steady_db=ms["snr_db"],
                   max_err_lsb=m["max_abs_err"], max_err_uv=m["max_abs_err"] * C.LSB_UV, bias_lsb=m["mean_err"],
                   ideal_q15_snr_db=C.ideal_q15_snr(r), rail_hits=st["rail_hits"],
                   enob=(m["snr_db"] - 1.76) / 6.02 if np.isfinite(m["snr_db"]) else float("nan"))
        fam = family(name)
        if fam.startswith("fir"):
            gd_ms = meta["fir"][fam[3:]]["gd_ms"]
        elif fam == "iirh":
            gd_ms = meta["iirh"]["gd10_ms"]
        else:
            gd_ms = meta["iir"][fam[3:]]["gd10_ms"]
        row["group_delay_ms"] = gd_ms
        if has_cyc and cpu_hz and st["samples"]:
            cps = st["total_cycles"] / st["samples"]
            fill_ms = st["block"] / fs * 1000.0
            proc_ms = st["max_block_cycles"] / cpu_hz * 1000.0
            row.update(cycles_per_sample=cps, proc_ms_worst_block=proc_ms, io_latency_ms=fill_ms + proc_ms,
                       cpu_load_pct=cps * fs / cpu_hz * 100.0,
                       worst_load_pct=st["max_block_cycles"] / (st["block"] / fs * cpu_hz) * 100.0)
        f = foot.get(name)
        if f:
            row.update(flash_bytes=int(f["flash_bytes"]), ram_bytes=int(f["ram_bytes"]))
        rows.append(row)

    # ---- 4. R peaks -----------------------------------------------------------------
    peak_res = None
    if "pt_q15" in log["stats"]:
        beats = np.array([s in C.BEAT_SYMBOLS for s in ref["ann_symbols"]])
        ann = ref["ann_samples"][beats]
        tol = int(round(a.tol_ms / 1000 * fs))
        peak_res = score_peaks(log["peaks"], ann, tol)
        peak_res.update(n_ann=int(len(ann)), n_det=len(log["peaks"]), tol_ms=a.tol_ms)
        if has_cyc and cpu_hz:
            st = log["stats"]["pt_q15"]
            peak_res.update(cycles_per_sample=st["total_cycles"] / st["samples"],
                            cpu_load_pct=st["total_cycles"] / st["samples"] * fs / cpu_hz * 100)
        print(f"[R peaks] {peak_res['n_det']} detected, {peak_res['n_ann']} annotated beats, "
              f"Se = {peak_res['sensitivity']*100:.1f} %, PPV = {peak_res['ppv']*100:.1f} %, "
              f"mean offset = {peak_res['mean_offset_samples']:.1f} samples  (tol +/-{a.tol_ms:g} ms)")
        if n < 60 * fs:
            print("          NOTE: <1 min of data -> Se/PPV rest on only a handful of beats; evaluate a longer "
                  "record on the host build (README, 'R-peak evaluation').")

    # ---- cross-check against another log --------------------------------------------
    cross = None
    if a.cross:
        other = C.parse_log(a.cross)
        cross = {}
        for k, v in log["series"].items():
            if k in other["series"] and k != "input":
                d = np.abs(np.nan_to_num(v) - np.nan_to_num(other["series"][k]))
                cross[k] = dict(identical=bool(np.all(d == 0)), max_diff=float(d.max()))
        ident = [k for k, v in cross.items() if v["identical"]]
        print(f"[cross] bit-identical to {Path(a.cross).name}: {len(ident)}/{len(cross)} series "
              f"(float rows may differ by <~1 LSB: FMA / summation order)")

    # ---- console table --------------------------------------------------------------
    hdr = f"{'impl':12s} {'SNR dB':>8s} {'SNR(ac)':>8s} {'steady':>8s} {'max|e|LSB':>10s} {'bias':>9s} {'ceiling':>8s}"
    print("\n" + hdr + ("  cyc/smp  load%" if has_cyc else ""))
    for r in rows:
        line = (f"{r['impl']:12s} {r['snr_db']:8.2f} {r['snr_ac_db']:8.2f} {r['snr_steady_db']:8.2f} "
                f"{r['max_err_lsb']:10.2f} {r['bias_lsb']:9.3f} {r['ideal_q15_snr_db']:8.1f}")
        if "cycles_per_sample" in r:
            line += f"  {r['cycles_per_sample']:7.1f}  {r['cpu_load_pct']:5.2f}"
        print(line)

    # ---- write table ----------------------------------------------------------------
    keys = ["impl", "cycles_per_sample", "cpu_load_pct", "worst_load_pct", "proc_ms_worst_block", "io_latency_ms",
            "group_delay_ms", "flash_bytes", "ram_bytes", "snr_db", "snr_ac_db", "max_err_lsb", "bias_lsb", "rail_hits"]
    with open(out / f"{a.label}_results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore"); w.writeheader(); w.writerows(rows)

    def cell(r, k, f="{:.1f}"):
        return f.format(r[k]) if k in r and r[k] == r[k] else "n/a"
    md = ["| Implementation | cycles/sample | CPU load @360 Hz | worst block (ms) | I/O latency (ms) | group delay (ms) "
          "| flash (B) | RAM (B) | SNR (dB) | SNR, DC removed (dB) | max err (LSB) | bias (LSB) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['impl']} | {cell(r,'cycles_per_sample')} | {cell(r,'cpu_load_pct','{:.2f} %')} | "
                  f"{cell(r,'proc_ms_worst_block','{:.3f}')} | {cell(r,'io_latency_ms','{:.1f}')} | "
                  f"{r['group_delay_ms']:.1f} | {cell(r,'flash_bytes','{:d}')} | {cell(r,'ram_bytes','{:d}')} | "
                  f"{r['snr_db']:.1f} | {r['snr_ac_db']:.1f} | {r['max_err_lsb']:.2f} | {r['bias_lsb']:+.2f} |")
    (out / f"{a.label}_results_table.md").write_text("\n".join(md) + "\n")
    summary = dict(label=a.label, platform=log["meta"].get("platform"), cpu_hz=cpu_hz, block=block,
                   cycle_counter=has_cyc, stack=log["stack"], peaks=peak_res, cross=cross, problems=problems,
                   segment=meta["segment"], rows=rows)
    C.save_json(out / f"{a.label}_summary.json", summary)

    # ---- plots ----------------------------------------------------------------------
    t = np.arange(n) / fs
    z0, z1 = (int(v * fs) for v in a.zoom)
    z1 = min(z1, n)
    def fam_key(s):                                  # fir63 < fir127 < fir255 < iir2 < iir4 < iirh
        digits = "".join(ch for ch in s if ch.isdigit())
        return (0 if s.startswith("fir") else 1, int(digits) if digits else 99)
    fams = sorted({family(r["impl"]) for r in rows}, key=fam_key)
    if not rows:
        print("[plots] no filter series in this log (pt-only run): skipping overlay/SNR plots")
    fig, axes = plt.subplots(max(len(fams), 1), 2, figsize=(14, 2.6 * max(len(fams), 1)), squeeze=False)
    for i, fam in enumerate(fams):
        ax, ae = axes[i]
        ax.plot(t[z0:z1], ref["ref_" + fam][z0:z1], "k", lw=2.2, label="float64 reference")
        for r in rows:
            if family(r["impl"]) != fam:
                continue
            y = log["series"][r["impl"]]
            ax.plot(t[z0:z1], y[z0:z1], lw=1, ls="--", label=f"{r['impl']} ({r['snr_db']:.0f} dB)")
            ae.plot(t[z0:z1], (y - ref["ref_" + fam])[z0:z1], lw=0.8, label=r["impl"])
        ax.set_title(f"{fam}: output overlay"); ax.set_ylabel("LSB"); ax.legend(fontsize=7, loc="upper right")
        ae.set_title(f"{fam}: error vs float64 (LSB)"); ae.legend(fontsize=7, loc="upper right")
        ax.grid(alpha=.3); ae.grid(alpha=.3)
    axes[-1][0].set_xlabel("time [s]"); axes[-1][1].set_xlabel("time [s]")
    fig.tight_layout()
    if rows:
        fig.savefig(out / f"{a.label}_overlay.png", dpi=110)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 4.2))
    names = [r["impl"] for r in rows]; xs = np.arange(len(rows))
    snr_plot = [max(r["snr_db"], -10) for r in rows]
    cols = ["tab:blue" if r["fmt"] == "f32" else "tab:green" if r["fmt"] in ("q15", "q15m", "q15r") else "tab:orange" for r in rows]
    ax.bar(xs, snr_plot, color=cols)
    ax.plot(xs, [r["ideal_q15_snr_db"] for r in rows], "k_", ms=14, label="ideal int16 output ceiling")
    ax.set_xticks(xs); ax.set_xticklabels(names, rotation=60, ha="right", fontsize=8)
    ax.set_ylabel("SNR vs float64 [dB]  (clipped at -10)"); ax.grid(axis="y", alpha=.3); ax.legend()
    ax.set_title("Quantisation-noise SNR per implementation (blue=f32, green=Q15, orange=Q31)")
    fig.tight_layout()
    if rows:
        fig.savefig(out / f"{a.label}_snr.png", dpi=110)
    plt.close(fig)

    if has_cyc and log["sweep"]:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        names_sw = sorted({s["name"] for s in log["sweep"]})
        for nm in names_sw:
            pts = sorted((s["block"], s["total_cycles"] / s["samples"]) for s in log["sweep"] if s["name"] == nm)
            ax.plot(*zip(*pts), marker="o", ms=3, lw=1, label=nm)
        ax.set_xscale("log", base=2); ax.set_yscale("log"); ax.set_xlabel("block size [samples]")
        ax.set_ylabel("cycles / sample"); ax.grid(alpha=.3, which="both"); ax.legend(fontsize=6, ncol=2)
        ax.set_title("Per-call overhead: cycles/sample vs block size")
        fig.tight_layout(); fig.savefig(out / f"{a.label}_block_sweep.png", dpi=110); plt.close(fig)

    if "pt_q15" in log["series"]:
        fig, ax = plt.subplots(2, 1, figsize=(12, 5), sharex=True)
        ax[0].plot(t, x, lw=.7, label="input")
        ann_b = ref["ann_samples"][[s in C.BEAT_SYMBOLS for s in ref["ann_symbols"]]]
        ax[0].plot(ann_b / fs, x[ann_b], "g^", label="MIT-BIH annotation")
        d = np.array(log["peaks"], dtype=int); d = d[d < n]
        ax[0].plot(d / fs, x[d], "rv", label="fixed-point Pan-Tompkins")
        ax[0].legend(fontsize=8); ax[0].grid(alpha=.3); ax[0].set_ylabel("LSB")
        ax[1].plot(t, log["series"]["pt_q15"], lw=.8, color="tab:purple"); ax[1].set_ylabel("MWI (counts)")
        ax[1].set_xlabel("time [s]"); ax[1].grid(alpha=.3)
        fig.tight_layout(); fig.savefig(out / f"{a.label}_peaks.png", dpi=110); plt.close(fig)

    print(f"\n[done] wrote {a.label}_results_table.md/.csv, {a.label}_summary.json and PNGs to {out}")
    if problems:
        print("\nPROBLEMS:\n  - " + "\n  - ".join(problems))
        sys.exit(1)


if __name__ == "__main__":
    main()
