#!/usr/bin/env python3
"""map_report.py - flash / RAM usage of the FULL image, read from the linker map and the ELF.

    python scripts/map_report.py --map build/nucleo/ecg_edge.map --elf build/nucleo/ecg_edge.elf \
                                 [--log results/mcu_run.log] [--flash-kib 512 --ram-kib 128]

Flash used = .isr_vector + .text + .rodata + (initial values of) .data
RAM  used  = .data + .bss                (static)   + stack high-water mark from the run (#STACK)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

SEC = re.compile(r"^(\.[A-Za-z_][\w.]*)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)")


def parse_map_sections(path: Path) -> dict:
    """Top-level output sections: the lines of the map that start in column 0 with '.name addr size'."""
    out = {}
    for line in path.read_text(errors="ignore").splitlines():
        m = SEC.match(line)
        if m and int(m.group(3), 16) > 0:
            out[m.group(1)] = int(m.group(3), 16)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", required=True); ap.add_argument("--elf", required=True)
    ap.add_argument("--log"); ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--flash-kib", type=int, default=512); ap.add_argument("--ram-kib", type=int, default=128)
    ap.add_argument("--out", default=str(C.RESULTS / "map_report.md"))
    a = ap.parse_args()

    sec = parse_map_sections(Path(a.map))
    flash = sum(sec.get(k, 0) for k in (".isr_vector", ".text", ".rodata", ".data"))
    ram_static = sec.get(".data", 0) + sec.get(".bss", 0)
    stack_used = stack_total = None
    if a.log:
        st = C.parse_log(a.log)["stack"]
        if st:
            stack_used, stack_total = st
    lines = ["# Image size (from the linker map)", "",
             "| Section | Bytes |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sec.items()
                                                    if k in (".isr_vector", ".text", ".rodata", ".data", ".bss")]
    lines += ["", f"* **Flash used** = {flash} B of {a.flash_kib * 1024} B ({flash / (a.flash_kib * 1024) * 100:.1f} %)",
              f"* **Static RAM** (.data+.bss) = {ram_static} B of {a.ram_kib * 1024} B ({ram_static / (a.ram_kib * 1024) * 100:.1f} %)"]
    if stack_used is not None:
        lines.append(f"* **Stack high-water mark** (stack painting) = {stack_used} B "
                     f"(of {stack_total} B left between .bss and the top of RAM)")
        lines.append(f"* **Total RAM footprint** = {ram_static + stack_used} B")
    nm = subprocess.run(["arm-none-eabi-nm", "-S", "--size-sort", "-t", "d", "-C", a.elf], capture_output=True, text=True).stdout
    big = [l.split(None, 3) for l in nm.strip().splitlines()][-a.top:][::-1]
    lines += ["", f"## Top {a.top} symbols by size", "", "| Size (B) | Type | Symbol |", "|---|---|---|"]
    lines += [f"| {int(s[1])} | {s[2]} | `{s[3]}` |" for s in big if len(s) == 4]
    Path(a.out).write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
