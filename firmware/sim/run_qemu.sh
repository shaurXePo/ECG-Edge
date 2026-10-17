#!/usr/bin/env bash
# Run the firmware on QEMU's STM32F405 board model ("netduinoplus2", Cortex-M4) with semihosting.
#   ./firmware/sim/run_qemu.sh [build-dir]       (build with -DECG_TARGET=qemu first)
#
# * QEMU executes the REAL Cortex-M4 machine code (including the SIMD kernels), so integer
#   results are bit-exact with the hardware.
# * QEMU does NOT model the DWT cycle counter -> no timing; use it for functional validation.
# * Semihosting console output is written to QEMU's STDERR (that is how QEMU does it), hence 2>.
set -euo pipefail
cd "$(dirname "$0")/../.."
BUILD=${1:-build/qemu}
LOG=results/qemu_run.log
[ -f "$BUILD/ecg_edge.elf" ] || { echo "missing $BUILD/ecg_edge.elf - build with -DECG_TARGET=qemu"; exit 1; }
qemu-system-arm -M netduinoplus2 -nographic \
    -semihosting-config enable=on,target=native \
    -kernel "$BUILD/ecg_edge.elf" 2> "$LOG" >/dev/null
echo "log: $LOG ($(wc -l < "$LOG") lines); last line: $(tail -n1 "$LOG")"
python3 scripts/validate.py --log "$LOG" --label qemu --cross results/host_run.log 2>/dev/null || python3 scripts/validate.py --log "$LOG" --label qemu
