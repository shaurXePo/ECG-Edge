#!/usr/bin/env bash
# fetch_deps.sh - download the three vendor dependencies at PINNED versions.
#
#   CMSIS-DSP        : the DSP kernels (arm_fir_q15, arm_biquad_cascade_df1_q15, ...)
#   CMSIS_5 (Core)   : core_cm4.h, cmsis_gcc.h  (DWT, SCB, intrinsics such as __QADD)
#   cmsis_device_f4  : stm32f4xx.h register definitions (USART2, RCC, GPIOA ...)
#
# Pinning matters: CMSIS-DSP changed function signatures between major versions, so
# the code in this repo is only guaranteed against the versions below.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p third_party
cd third_party

clone() {  # clone <url> <tag> <dir>
  if [ -d "$3/.git" ]; then echo "[skip] $3 already present"; return; fi
  echo "[clone] $1 @ $2"
  git clone --quiet --depth 1 --branch "$2" "$1" "$3"
}

clone https://github.com/ARM-software/CMSIS-DSP.git         v1.16.2 CMSIS-DSP
clone https://github.com/ARM-software/CMSIS_5.git           5.9.0   CMSIS_5
clone https://github.com/STMicroelectronics/cmsis_device_f4.git v2.6.10 cmsis_device_f4
echo "Done. third_party/ contains: $(ls | tr '\n' ' ')"
