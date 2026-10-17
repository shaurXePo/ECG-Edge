# Example results - SYNTHETIC ECG, SIMULATED Cortex-M4

These files were produced while developing the project, in a sandbox that could not reach PhysioNet:

* input   : `scripts/common.py:synth_ecg` (10 s synthetic ECG), **not** MIT-BIH record 100
* firmware: the real Cortex-M4F binary (`-DECG_TARGET=qemu`) executed by QEMU 8.2 (`netduinoplus2`)
            and by Renode 1.15.3; integer outputs were bit-identical to the host build
* timing  : none (neither simulator models the DWT cycle counter) - cycles columns are intentionally empty
* flash/RAM (`footprint.csv`, `map_report_nucleo.md`): real numbers for arm-none-eabi-gcc 13.2.1, -O2,
  CMSIS-DSP v1.16.2, all 20 implementations; they do not depend on the ECG data

Use them only to check that YOUR run looks sane (same file layout, integer rows identical to the host
build, SNR rows in the same ballpark).  Do not quote them as MIT-BIH results.
