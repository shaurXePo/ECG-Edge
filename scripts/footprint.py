#!/usr/bin/env python3
"""footprint.py - measure the flash / RAM cost of EACH implementation in isolation.

Method (no estimation, no guessing):
  * build a BASELINE image with every implementation group disabled (framework + vector + UART);
  * for each implementation build an image with ONLY that group enabled (and a header set that
    contains only that one tap count / order), using the same compiler flags;
  * flash_bytes = (text + data) - baseline,   ram_bytes = (data + bss) - baseline
    where text/data/bss come from `arm-none-eabi-size` (Berkeley format) on the ELF.
  --gc-sections removes everything the disabled groups would have contributed, so the delta is
  exactly the code + coefficients + filter state of that implementation (plus the CMSIS-DSP
  kernels it alone pulls in - shared kernels are counted in full for each, i.e. 'stand-alone cost').

Stack is not included (it is measured at run time by stack painting: see the #STACK line).

    python scripts/footprint.py                      # Cortex-M4 (needs arm-none-eabi-gcc), writes results/footprint.csv
    python scripts/footprint.py --opt -Os            # footprint at a different optimisation level
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

ALL_GROUPS = ["FIR_F32", "FIR_Q15", "FIR_Q15M", "IIR_F32", "IIR_Q15", "IIR_Q31",
              "IIRH_F32", "IIRH_Q15", "IIRH_Q15R", "IIRH_Q31", "PT"]


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"command failed: {' '.join(map(str, cmd))}\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return r.stdout


def build_and_size(tmp: Path, tag: str, enabled: set, taps: int, order: int, target: str, pll: int, opt: str):
    gen = tmp / f"gen_{tag}"
    run([sys.executable, str(C.REPO / "scripts" / "export_headers.py"), "--headers-only", "--no-reference",
         "--fir-taps", str(taps), "--iir-orders", str(order), "--out-dir", str(gen)])
    bld = tmp / f"build_{tag}"
    flags = [f"-DECG_ENABLE_{g}={1 if g in enabled else 0}" for g in ALL_GROUPS]
    run(["cmake", "-S", str(C.REPO / "firmware"), "-B", str(bld), f"-DECG_TARGET={target}", f"-DECG_USE_PLL={pll}",
         f"-DECG_GEN_DIR={gen}", f"-DECG_OPT={opt}", "-DCMAKE_BUILD_TYPE=Release",
         f"-DCMAKE_TOOLCHAIN_FILE={C.REPO / 'firmware' / 'cmake' / 'arm-none-eabi.cmake'}", *flags])
    run(["cmake", "--build", str(bld), "-j8"])
    line = run(["arm-none-eabi-size", "--format=berkeley", str(bld / "ecg_edge.elf")]).strip().splitlines()[-1].split()
    text, data, bss = int(line[0]), int(line[1]), int(line[2])
    return text + data, data + bss


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", default="stm32f4", choices=["stm32f4", "renode", "qemu"])
    ap.add_argument("--pll", type=int, default=0)
    ap.add_argument("--opt", default="-O2")
    ap.add_argument("--out", default=str(C.RESULTS / "footprint.csv"))
    ap.add_argument("--keep", action="store_true", help="keep temporary build dirs")
    a = ap.parse_args()

    meta = json.loads((C.RESULTS / "meta.json").read_text())
    taps, orders = [int(k) for k in meta["fir"]], [int(k) for k in meta["iir"]]
    tmp = Path(tempfile.mkdtemp(prefix="ecg_footprint_"))
    try:
        # (impl name, group, taps used for header, order used for header)
        jobs = []
        for n in taps:
            jobs += [(f"fir{n}_f32", "FIR_F32", n, orders[0]), (f"fir{n}_q15", "FIR_Q15", n, orders[0]),
                     (f"fir{n}_q15m", "FIR_Q15M", n, orders[0])]
        for k in orders:
            jobs += [(f"iir{k}_f32", "IIR_F32", taps[0], k), (f"iir{k}_q15", "IIR_Q15", taps[0], k),
                     (f"iir{k}_q31", "IIR_Q31", taps[0], k)]
        jobs += [(f"iirh_{s.lower()}", f"IIRH_{s}", taps[0], orders[0]) for s in ("F32", "Q15", "Q15R", "Q31")]
        jobs += [("pt_q15", "PT", taps[0], orders[0])]

        print("[footprint] baseline (all groups off) ...")
        base_flash, base_ram = build_and_size(tmp, "base", set(), taps[0], orders[0], a.target, a.pll, a.opt)
        print(f"            baseline: flash {base_flash} B, RAM {base_ram} B")
        rows = [dict(impl="__baseline__", flash_bytes=base_flash, ram_bytes=base_ram)]
        for name, grp, n, k in jobs:
            fl, rm = build_and_size(tmp, name, {grp}, n, k, a.target, a.pll, a.opt)
            rows.append(dict(impl=name, flash_bytes=fl - base_flash, ram_bytes=rm - base_ram))
            print(f"  {name:12s} +{fl - base_flash:6d} B flash   +{rm - base_ram:6d} B RAM")
        with open(a.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["impl", "flash_bytes", "ram_bytes"]); w.writeheader(); w.writerows(rows)
        print(f"[footprint] wrote {a.out}  (opt {a.opt}, target {a.target})")
    finally:
        if not a.keep:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
