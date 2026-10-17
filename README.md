# ECG-Edge — real-time fixed-point ECG filtering on a Cortex-M4, validated against Python

A 0.5–40 Hz band-pass + 60 Hz notch for 360 Hz ECG (MIT-BIH), implemented four ways
(float32, CMSIS Q15, hand-written Q15, Q31) as FIR and IIR, run block-by-block on an ARM Cortex-M4F,
timed with the DWT cycle counter, and checked sample-by-sample against a double-precision Python
reference. Optional: a fixed-point Pan-Tompkins R-peak detector scored against the MIT-BIH annotations.

It extends my Python project **ecg-dsp-toolkit** (same filter specification), taking it from
"works in NumPy" to "works in 16-bit integers on a microcontroller, and I can prove how wrong it is".

---

## 0. Read this first: what is verified, and what is yours to measure

| Item | Status |
|---|---|
| Python export → C headers → firmware → CSV → validation pipeline | **Built and run end-to-end** (host, QEMU Cortex-M4, Renode Cortex-M4) |
| Integer outputs: real Cortex-M4 SIMD binary (QEMU/Renode) vs host C | **Bit-identical** for every Q15/Q31 implementation and the R-peak list |
| Flash / RAM per implementation (`footprint.py`) | **Measured** (arm-none-eabi-gcc 13.2.1, `-O2`, CMSIS-DSP v1.16.2) – table in §9 |
| Stack high-water mark | Measured under QEMU (840 B for the full run); re-measure on your board |
| MIT-BIH record 100 results | **Not run by me**: my sandbox could not reach PhysioNet. All example numbers use a *synthetic* ECG and are in `results/example_synthetic/` |
| Cycles/sample, latency, CPU load | **Not measured** (no hardware; QEMU/Renode have no DWT cycle counter). §9 tells you exactly how to get them and what range to expect |
| Real Nucleo board, ST-LINK flashing, UART capture | Code written to the register level and cross-compiled, **never run on silicon by me** |
| PlatformIO build | Config provided, **untested** (the CMake build is the tested path) |

Nothing in this README is a hardware measurement unless it says so. Where I give a number I did not measure,
it is labelled *expected range* and comes with the reasoning.

### Assumptions (no questions asked, so here they are)

1. **Board**: Nucleo-F411RE (Cortex-M4F, 128 KB RAM, 512 KB flash, ST-LINK virtual COM port on USART2/PA2). Your `[board]` placeholder was unspecified; any Cortex-M4F works – see §4.4 for porting.
2. **Clock**: default HSI 16 MHz (no PLL) so the first run needs no clock debugging. `-DECG_USE_PLL=1` selects 96 MHz (F411 only, untested).
3. **Sampling**: fs = 360 Hz, **60 Hz** notch (US mains, because MIT-BIH was recorded in the US). If you later feed a live ADC in India, change `NOTCH_HZ` in `scripts/common.py` to **50**.
4. **Amplitude convention**: int16 sample = Q15 with **±5 mV full scale** (1 LSB = 0.153 µV). Record-100 MLII peaks are roughly ±1–2 mV, leaving ~2.5× headroom for filter overshoot.
5. **Test signal**: first 10 s (3600 samples) of MIT-BIH `100`, channel 0 (MLII). Configurable (`--record --start --seconds`).
6. **Reference**: double precision, run on the *already int16-quantised* input, so the measured error isolates the *filter implementation*, not the ADC.
7. **IIR "complete chain"** = band-pass **+** notch (one extra biquad). The FIR chain is band-pass only (a 63-tap or longer Hamming FIR already puts 60 Hz in its stop-band).
8. **FIR lengths** 63 / 127 / 255 (odd, type-I linear phase; zero-padded by one tap internally because `arm_fir_q15` on Cortex-M4 requires an even count).

---

## 1. System block diagram

```mermaid
flowchart LR
  subgraph PY["Python (PC)  scripts/"]
    A["MIT-BIH record 100<br/>10 s, 360 Hz (wfdb)"] --> B["quantise<br/>mV → int16 (Q15, ±5 mV FS)"]
    D["design float64 filters<br/>FIR windowed-sinc, Butterworth SOS, notch"] --> E["scale + quantise<br/>Q15 / Q31, postShift"]
    B --> H["export_headers.py"]
    E --> H
    D --> R["float64 reference<br/>(sosfilt / convolve)"]
    B --> R
  end
  H -->|"ecg_params.h<br/>ecg_coeffs.h<br/>ecg_testvec.h"| FW
  subgraph FW["Firmware  firmware/  (portable C + CMSIS-DSP)"]
    S["input source<br/>ecg_source_vector (flash)<br/>ecg_source_ring (ADC / UART ISR hook)"] --> P["block pipeline<br/>ecg_pipeline.c<br/>DWT cycle timing"]
    P --> F["filters (impl table)<br/>f32 · Q15 CMSIS · Q15 manual · Q31<br/>FIR · biquad cascade · Pan-Tompkins"]
    F --> O["CSV writer<br/>ecg_out.c (no printf)"]
  end
  subgraph BSP["Board layer  board/  (ecg_platform.h)"]
    U["UART2 / semihosting / stdout"]
    T["DWT->CYCCNT"]
    K["startup · clock · FPU · linker script · stack paint"]
  end
  P -.cycles.-> T
  O --> U
  U -->|"CSV log"| V["validate.py<br/>SNR · max error · plots · R-peak Se/PPV"]
  R --> V
  V --> X["results/ table + PNGs"]
```

Timing/latency diagram: [`docs/timing_diagram.svg`](docs/timing_diagram.svg) (symbolic: T_fill = N/fs, T_proc = cycles/f_cpu,
latency = T_fill + T_proc + group delay). Linker notes: [`docs/linker_notes.md`](docs/linker_notes.md).

**The key design rule:** `firmware/src` and `firmware/inc` (portable) know nothing about the chip. They talk to the
world only through `ecg_platform.h` (7 functions) and `ecg_source.h` (the input stream). A new board = one new
directory under `firmware/board/`.

```
ecg-edge/
├── README.md  Makefile  platformio.ini  requirements.txt
├── scripts/                      # Python: everything that runs on the PC
│   ├── common.py                 #   spec, filter design, Q-format quantisation, log parser (shared by all)
│   ├── export_headers.py         #   design → quantise → ecg_params.h / ecg_coeffs.h / ecg_testvec.h + reference.npz
│   ├── validate.py               #   MCU log vs float64: SNR, max error, plots, R-peak Se/PPV, results table
│   ├── footprint.py              #   per-implementation flash/RAM (isolated builds)
│   ├── map_report.py             #   flash/RAM/top symbols from the linker map
│   ├── plot_responses.py         #   |H(f)| float64 vs quantised coefficients
│   ├── diagnose_q15_iir.py       #   bit-exact Q15 biquad model: why the 0.5 Hz IIR fails
│   ├── capture_uart.py           #   record the ST-LINK COM port to a file
│   └── fetch_deps.sh  pio_extra.py
├── firmware/
│   ├── CMakeLists.txt  cmake/arm-none-eabi.cmake
│   ├── inc/  src/                # PORTABLE: pipeline, filters, detector, CSV writer, input sources
│   │   └── generated/            #   (created by export_headers.py – not committed)
│   ├── board/host/               # PC implementation of ecg_platform.h
│   ├── board/stm32f4/            # Cortex-M4: startup, clock/FPU, UART, DWT, stack painting, linker scripts (ld/)
│   ├── renode/                   # ecg_edge.resc + run_renode.sh
│   ├── sim/run_qemu.sh           # QEMU alternative
│   └── tests/test_ring.c         # unit test of the ADC/UART ring-buffer hook
├── results/                      # your run outputs go here;  example_synthetic/ = sandbox run (see its README)
├── docs/                         # block_diagram.mmd, timing_diagram.svg, linker_notes.md
└── third_party/                  # fetched: CMSIS-DSP v1.16.2, CMSIS_5 5.9.0 (Core), cmsis_device_f4 v2.6.10
```

### Implementation names (they are the keys in the CSV log and in the results table)

| Name | Arithmetic | Structure |
|---|---|---|
| `fir{63,127,255}_f32` | float32, FPU | `arm_fir_f32` |
| `fir{N}_q15` | Q15, 64-bit accumulate, **truncate** | `arm_fir_q15` (SIMD dual-MAC) |
| `fir{N}_q15m` | Q15, 32-bit **saturating** accumulate, **round** | hand-written (`ecg_fir_q15_manual.c`) |
| `iir{2,4}_f32` | float32 | `arm_biquad_cascade_df2T_f32`, Butterworth band-pass order 2/4 + notch |
| `iir{2,4}_q15` | Q15, truncate | `arm_biquad_cascade_df1_q15` (+postShift) – **fails, on purpose kept, see §5.6** |
| `iir{2,4}_q31` | Q31 | `arm_biquad_cascade_df1_q31` |
| `iirh_{f32,q15,q15r,q31}` | as named; `q15r` = hand-written, **rounding** | "hp1" structure: 2× first-order HP + LP + notch (Q15-friendly) |
| `pt_q15` | integer | band-pass 5–15 Hz → derivative → square → MWI → adaptive threshold |

---

## 2. Quick start

### 2.1 Prerequisites

```bash
# Ubuntu/Debian/WSL
sudo apt install git cmake python3-pip gcc-arm-none-eabi libnewlib-arm-none-eabi
# optional simulators
sudo apt install qemu-system-arm                  # QEMU
#   Renode: https://github.com/renode/renode/releases  (v1.15.3 portable tarball was used)
# optional flashing: sudo apt install stlink-tools   (st-flash)   or openocd
pip install -r requirements.txt
./scripts/fetch_deps.sh                           # CMSIS-DSP / CMSIS-Core / STM32F4 device header, pinned versions
```
macOS: `brew install cmake arm-none-eabi-gcc qemu stlink`. Windows: use WSL2 (USB passthrough for ST-LINK via `usbipd`) or the Arm GNU toolchain + CMake + Ninja.

### 2.2 Export the data and coefficients (once)

```bash
python scripts/export_headers.py                  # real MIT-BIH record 100, first 10 s (downloads ~2 MB into data/)
# offline smoke test only (NOT a valid portfolio result):
python scripts/export_headers.py --source synthetic
# options: --record 100 --start 0 --seconds 10 --fir-taps 63 127 255 --iir-orders 2 4 --iir-scale linf|none
```
It prints the quantisation report (max |h|, L1 norm, postShift …) and writes
`firmware/inc/generated/*.h`, `results/reference.npz`, `results/meta.json`.

### 2.3 Path A — no hardware (host + QEMU/Renode)

```bash
# A1. host build: portable code on your PC (numerics only; timing is in ns, not cycles)
make host-run                                    # = cmake build + ./ecg_edge.elf + validate.py + unit test
# equivalent explicit commands:
cmake -S firmware -B build/host -DECG_TARGET=host -DCMAKE_BUILD_TYPE=Release
cmake --build build/host -j
./build/host/ecg_edge.elf > results/host_run.log
python scripts/validate.py --log results/host_run.log --label host

# A2. the REAL Cortex-M4 machine code, simulated – QEMU
make qemu-run
#   = cmake -S firmware -B build/qemu -DECG_TARGET=qemu -DCMAKE_TOOLCHAIN_FILE=$PWD/firmware/cmake/arm-none-eabi.cmake -DCMAKE_BUILD_TYPE=Release
#     cmake --build build/qemu -j  &&  ./firmware/sim/run_qemu.sh

# A3. same binary family in Renode (STM32F407 model, USART2 captured to a file)
export RENODE=/path/to/renode                    # omit if `renode` is on PATH
make renode-run
```
What simulators can and cannot tell you:

* ✅ **Functional correctness**: they execute the real Thumb-2 + DSP-extension instructions, so Q15/Q31 integer results are bit-exact with silicon (I verified host == QEMU == Renode).
* ❌ **Cycle counts**: neither models `DWT->CYCCNT`. The firmware detects this (`#META,has_cycle_counter,0`) and `validate.py` prints `n/a` rather than fake numbers.
* ❌ Flash wait states / ART accelerator / bus contention – these change real cycle counts.

### 2.4 Path B — Nucleo-F411RE hardware

```bash
make nucleo                                      # 115200 baud, HSI 16 MHz  (≈ 75 s to stream the log)
#  or faster:   make nucleo-pll                  # 96 MHz core, 460800 baud (≈ 19 s) – see §10 if no output
# explicit form:
cmake -S firmware -B build/nucleo -DECG_TARGET=stm32f4 -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_TOOLCHAIN_FILE=$PWD/firmware/cmake/arm-none-eabi.cmake -DECG_UART_BAUD=115200
cmake --build build/nucleo -j                    # prints FLASH/RAM usage; produces ecg_edge.elf/.bin/.map

# flash (any one of):
st-flash --reset write build/nucleo/ecg_edge.bin 0x08000000
openocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c "program build/nucleo/ecg_edge.elf verify reset exit"
cp build/nucleo/ecg_edge.bin /media/$USER/NODE_F411RE/       # drag-and-drop via ST-LINK mass storage

# capture the CSV (start BEFORE pressing the black RESET button; stops at #DONE)
python scripts/capture_uart.py --list
python scripts/capture_uart.py --port /dev/ttyACM0 --baud 115200 --out results/mcu_run.log    # Windows: COM5
python scripts/validate.py --log results/mcu_run.log --label mcu --cross results/host_run.log
python scripts/footprint.py                                              # per-implementation flash/RAM  (~1 min)
python scripts/map_report.py --map build/nucleo/ecg_edge.map --elf build/nucleo/ecg_edge.elf --log results/mcu_run.log
```
(If you use `nucleo-pll`, capture at `--baud 460800`.) The firmware runs **once** after every reset, prints
the log, then sleeps – press RESET to repeat.

### 2.5 PlatformIO option

```bash
pip install platformio
./scripts/fetch_deps.sh && python scripts/export_headers.py
pio run -e nucleo_f411re -t upload
pio device monitor -b 115200 --filter log2file          # or use scripts/capture_uart.py
```
**Untested by me.** PlatformIO's CMSIS framework brings its own startup/linker script/`system_stm32f4xx.c`, so those
files in `board/stm32f4/` are excluded (see `platformio.ini`). If the link fails with a missing `_ebss`/`_estack`,
add them to PlatformIO's linker script (`.ld`) – they are standard in ST's scripts, but check your framework version.

---

## 3. What each stage does (step-by-step explanation)

**Step 1 — Python design (`common.py`, `export_headers.py`).**
Golden filters are designed in float64: `firwin` (Hamming windowed-sinc, 0.5–40 Hz), `butter(...,'bandpass',output='sos')`, `iirnotch(60, Q=30)`.
Then each is converted to the exact byte pattern the CMSIS function expects (§5): time-reversed + even-length FIR taps,
sign-flipped feedback coefficients, 6-per-stage layout for the Q15 biquad, `postShift`. The 10 s ECG segment is quantised to int16 and written
as a `static const int16_t[]`. Every spec number lives once in `common.py` and is copied into `ecg_params.h`, so firmware and reference cannot disagree.

**Step 2 — Firmware filters (`src/ecg_filters_*.c`).** One macro per family expands, for every tap count/order in the exported list, into
`{state buffer, init(), process()}`. Changing `--fir-taps` in Python changes the firmware with no C edits (X-macros).

**Step 3 — Pipeline (`ecg_pipeline.c`).** `source → process(block) → output buffer`. Block size is a run-time argument (≤ `ECG_MAX_BLOCK_SIZE`).
The stream is processed **twice**: pass 1 warms the flash prefetch/cache and is discarded, pass 2 is timed. Each `process()` call is bracketed by
two reads of `DWT->CYCCNT`; the cost of the measurement itself (`#META,timing_overhead_cycles`) is subtracted. We keep total cycles
(→ cycles/sample), **maximum** block cycles (→ worst-case latency) and minimum.

**Step 4 — Input hook (`ecg_source.h`).** `ecg_source_vector` replays flash data (deterministic validation). `ecg_source_ring` is an SPSC ring buffer
that an ISR fills with `ecg_source_ring_push()`; wiring comments for TIM2→ADC1→ISR are in `ecg_source.h`. Switch by changing one line in `ecg_app.c`.

**Step 5 — Output (`ecg_out.c`).** CSV over UART (or semihosting under QEMU) with a hand-written number formatter (no `printf`, which would cost 10–20 KB flash and distort the footprint numbers).
Every implementation's output is printed in **int16-LSB units** (float ×32768, Q31 ÷2¹⁶, 3 decimals), so Python compares like with like.

**Step 6 — Validation (`validate.py`).** Checks the echoed input equals the exported vector bit-for-bit (catches stale headers),
then per implementation: `SNR = 10·log10(Σref² / Σ(y−ref)²)`, max |error|, bias, and the *ceiling* (SNR of simply rounding the exact answer to integers – no int16 implementation can beat it).

---

## 4. Software details worth knowing

### 4.1 Log format (parsed by `common.parse_log`)
```
#META,key,value               #BEGIN,name,fmt,count  /  idx,value ... /  #END,name
#STAT,name,samples,blocks,block,total_cycles,max_block_cycles,min_block_cycles,rail_hits
#SWEEP,<same>                 (block-size sweep 1/4/16/36/64/128, timing only)
#PEAK,idx                     #STACK,used_bytes,total_bytes        #DONE
```
Samples are stored **by index**: a byte lost on the UART leaves a NaN hole that `validate.py` reports, instead of silently shifting the data.

### 4.2 Stack usage
`platform_stack_paint()` fills the free RAM (`_ebss` … SP−64) with `0xA5A5A5A5` at start; at the end `platform_stack_used()` scans upward for the first overwritten word.
No heap exists, so this is the complete dynamic-memory story. Result is printed as `#STACK,used,total`.

### 4.3 Flash and RAM
* Whole image: linker prints `FLASH:/RAM:` at every link; `map_report.py` parses the map and `arm-none-eabi-nm` for the biggest symbols.
* Per implementation: `footprint.py` builds a baseline with everything disabled, then one image per implementation, and subtracts (the `ECG_ENABLE_*` flags + `--gc-sections` make unused code vanish).

### 4.4 Porting to another Cortex-M4
Create `firmware/board/<yours>/` with `platform_cycles.h` (`return DWT->CYCCNT;`), a file implementing the functions in `ecg_platform.h`
(UART pins and clock tree are the only chip-specific parts), startup code and a linker script, and add the directory to `CMakeLists.txt`. Nothing in `src/` changes. For a Cortex-M7 add `-mcpu=cortex-m7 -mfpu=fpv5-d16`; for M0/M3 there is no DSP extension and no DWT cycle counter on M0 (use SysTick).

---

## 5. Fixed-point theory (the part interviewers ask about)

### 5.1 Q formats
Qm.n = signed integer interpreted as `value = int / 2ⁿ`. ARM/CMSIS write **Q1.15** (1 sign bit + 15 fraction bits = 16 bits, abbreviated **Q15**):
range [−1, 1−2⁻¹⁵], step 2⁻¹⁵ = 3.05×10⁻⁵. Q31 = 1.31. A Q15 value is not "a small integer": the integer −32768 *means* −1.0.
Our int16 ECG sample means `mV = int/32768 × 5`.

### 5.2 Multiplication, accumulation, scaling
* Q1.15 × Q1.15 = **Q2.30** in 32 bits (two sign bits). To return to Q15 shift right 15.
* Summing N products grows the value by up to log₂(N) bits (**guard bits**). `arm_fir_q15` accumulates in 64 bits (34.30) so this never overflows; our hand-written FIR uses a 32-bit Q30 accumulator that holds ±2.0, which is safe only if **Σ|h| < 2** (the L1 norm: worst-case input of full-scale, sign-matched samples).
  Our L1 norms are 1.64 (63 taps), 1.94 (127), **2.26 (255)** → the 255-tap manual FIR has *no guarantee* (real ECG never gets near it: `rail_hits` stays 0), which is exactly why it uses a **saturating** add.
* The one illegal product: (−1)×(−1) = +1 is not representable in Q15 → must saturate to 32767 (CMSIS does via `__SSAT`).

### 5.3 Saturation vs wrap-around
Two's-complement overflow **wraps**: 32767 + 1 → −32768, turning a slightly-too-large peak into a huge opposite-sign spike.
Saturation clamps instead (`SSAT`, `QADD`, `QSUB` are single-cycle instructions on Cortex-M4). Rule: **saturate at every point where a signal is narrowed or accumulated
in the same width**; widen the accumulator wherever it is free. `rail_hits` in the log counts output samples sitting on ±full-scale, a cheap overflow detector.

### 5.4 Quantisation noise and the 6 dB/bit rule
Rounding to a grid of step Δ adds error uniformly distributed in ±Δ/2: power Δ²/12. For a full-scale sine and B bits
`SQNR = 6.02·B + 1.76 dB` (98 dB for B=16): **each extra bit buys 6.02 dB** because it halves Δ (20·log₁₀2).
A real ECG uses only part of the range: with rms ≈ 0.05–0.1 of full scale you lose 20–26 dB, so the *ceiling* for an int16 output is ≈ 72–78 dB. That is the "ideal" column in `validate.py`.
Other noise sources: coefficient quantisation (moves poles/zeros: changes the *response*, not the noise), and **recursive feedback** (IIR) which amplifies rounding noise by the gain of 1/A(z).

### 5.5 FIR in Q15
Windowed-sinc taps are all |h| < 1 (max ≈ 0.2), so they fit Q15 directly with no scaling; coefficient error ≤ 2⁻¹⁶. The final `>>15` in CMSIS **truncates** (floor) → mean error −0.5 LSB
(visible as bias ≈ −0.45…−0.6 LSB in the results), and cost ≈ 4–6 dB of SNR versus rounding in my sandbox run. My manual FIR adds half an LSB before shifting.

### 5.6 IIR (biquad) in Q15 — coefficient scaling and `postShift`
**CMSIS conventions (all handled in `common.py`):** equation `y[n] = b0x[n] + b1x[n-1] + b2x[n-2] + a1'y[n-1] + a2'y[n-2]` with **a1' = −a1, a2' = −a2** (opposite of scipy);
Q15 layout is **6 values/stage `{b0, 0, b1, b2, a1', a2'}`** (the 0 pads b0 into a SIMD word); state is 4 words/stage (`x[n-1], x[n-2], y[n-1], y[n-2]`).

**Why scaling is needed.** A Q15 coefficient must satisfy |c| < 1, but a low-frequency pole pair has a1' = 2r·cos θ ≈ **1.98**.
CMSIS therefore takes a `postShift` p: stored integer `q = round(c · 2^(15−p))`, and the kernel computes `y = (Σ q·s) >> (15−p)`, so the real coefficient is `q·2^p / 2^15`.
`p = 1` ⇒ Q14 (range ±2), `p = 2` ⇒ Q13 (±4). `choose_post_shift()` picks the smallest p with max|c| < 2^p. The price: each +1 in p costs **one coefficient bit** (precision halves).

**Section scaling.** `--iir-scale linf` divides each section's numerator by that section's peak gain and puts the product back into the last section – the overall transfer function is unchanged, but no inner node can exceed the input level (no clipping inside the cascade) and inner signals stay as large as safely possible. For Butterworth order 4 this pushed the last section above 2.0 and forced p=2; `--iir-scale none` is provided to compare. Both fail the same way (below).

**What actually happens at 0.5 Hz / fs = 360 Hz (measured, bit-exact model in `scripts/diagnose_q15_iir.py`):**

| Structure | Arithmetic | SNR vs float64 | Why |
|---|---|---|---|
| Butterworth band-pass+notch, order 2 | CMSIS Q15 (truncate) | **−16.6 dB** (bias ≈ −8000 LSB) | see below |
| same, order 4 | CMSIS Q15 | −28.5 dB, output pinned to the rail | same |
| same | Q31 (`iir2_q31`) | 82.4 dB | 2¹⁶× finer coefficients and state |
| same | float32 | 80.8 dB | even float32 loses ~30 dB vs the better structure |
| **hp1**: 2×1st-order HP + LP + notch | CMSIS Q15 | 23.1 dB (42.3 dB with DC removed) | truncation bias × 115 |
| same | **hand-written Q15, rounding** (`iirh_q15r`) | **50.1 dB** | bias ≈ −1.3 LSB |
| same | Q31 / float32 | 119 dB / 114 dB | |

(All on the synthetic segment; rerun on record 100 for your numbers.)

The failure of the Butterworth Q15 IIR is **structural**, not a bug (Q31 with identical coefficient conventions works):

1. The 0.5 Hz poles sit at radius ≈ 0.991. For that section `A(1) = 1 + a1 + a2 = 7.7×10⁻⁵` and the DC gain of the feedback path is `1/A(1) ≈ 12 900`.
2. One Q14 coefficient step is 6.1×10⁻⁵ ≈ A(1): **a single LSB of rounding in a1 or a2 changes the DC gain by ~80 %** – the pole position is essentially random (`plot_responses.py` shows the corner moving).
3. CMSIS truncates; the −0.5 LSB bias is injected *inside* the recursion and multiplied by 12 900 → thousands of LSB of DC offset (the plots show it as a huge constant shift).

Remedies, in the order I would try them: (a) **Q31** biquads (`iirK_q31`: more flash/cycles but ≈ float quality); (b) **change the structure** so no direct-form section has poles that close to z=1: two first-order high-passes (`iirh`), whose single real pole at R ≈ 0.994 is only 0.3 % off in Q15 – with **rounding** instead of truncation this reaches 50 dB; (c) a high-pass implemented as *subtract a slow running mean* (not implemented); (d) error-feedback ("noise shaping") or 32-bit state with 16-bit coefficients (`arm_biquad_cas_df1_32x64_q31`, not implemented).
The hp1 filter is *not* the Butterworth you designed (its high-pass is double real pole instead of Butterworth pair): it is a deliberate engineering trade-off, and the reference for `iirh` is its own float64 design.

### 5.7 DF1 vs DF2T
Direct form I (used for fixed point): feed-forward and feedback parts are separate, so one 64-bit accumulator sums all 5 products with no intermediate overflow, and state holds real signal values.
Transposed DF2 (used for float): only 2 state words/section and good float behaviour, but its internal states are not signal-sized and can overflow in fixed point.

---

## 6. FIR design note: why 0.5 Hz is awkward for a FIR
A Hamming window has a main-lobe width ≈ 3.3·fs/N. For a 0.5 Hz edge you would need N ≈ 2400 taps; with N = 255 the transition is ≈ 4.7 Hz wide, so
the high-pass edge is soft: baseline wander below ≈ 2 Hz is only partly removed and the response at 0.5 Hz is far from −3 dB. That is a *design* limitation, not a *quantisation* one;
`validate.py` measures only the latter (vs the same filter in float64), and `plot_responses.py` shows the former. Group delay is (N−1)/2 samples: 86 / 175 / 353 ms for 63 / 127 / 255 taps
– too long for beat-by-beat feedback, fine for display/storage. Long FIRs are cheap in cycles but expensive in latency; IIR is the opposite.

---

## 7. Optional stretch: Pan-Tompkins R-peak detector (`ecg_pan_tompkins.c`)
Integer-only chain: 5–15 Hz Butterworth (2 biquads, Q15) → 5-point derivative → squaring (kept in 32 bit, `>>6`, **not** shifted back to Q15 – QRS slopes are only hundreds of LSB, a Q15 square would have 3–4 bits of resolution) →
150 ms moving-window integral (54 samples @ 360 Hz) → adaptive thresholds (SPKI/NPKI, THR1 = NPKI + ¼(SPKI−NPKI)), 200 ms refractory, T-wave rejection (slope < ½ of the previous QRS), search-back at 1.66×RR. R location is refined by an arg-max on the band-passed signal.
Not implemented: the 2 s learning phase and the second threshold pair of the original paper.

**Evaluating it properly.** 10 s contains only ~10–15 beats, so Se/PPV there is anecdotal. Use the host build on a long record (the host can hold the whole 30-min record; the MCU cannot):
```bash
python scripts/export_headers.py --seconds 1800 --out-dir build/gen_long --results-dir results/long     # ~650 k samples
cmake -S firmware -B build/host_long -DECG_TARGET=host -DECG_GEN_DIR=$PWD/build/gen_long -DCMAKE_BUILD_TYPE=Release && cmake --build build/host_long -j
./build/host_long/ecg_edge.elf --pt-only > results/long/pt.log
python scripts/validate.py --log results/long/pt.log --reference results/long/reference.npz --meta results/long/meta.json \
                           --out-dir results/long --label pt --tol-ms 150
```
`validate.py` counts only *beat* annotation symbols (`N L R B A a J S V r F e j n E / f Q ?`), matches each to the nearest detection within ±150 ms (AAMI EC57) and reports TP/FP/FN, sensitivity Se = TP/(TP+FN), PPV = TP/(TP+FP) and the mean detection offset
(≈ the band-pass group delay; subtract it if you need sample-accurate R positions). Typical literature values for PT-style detectors on MIT-BIH are Se/PPV ≈ 98–99.5 % overall, but **record 100 is one of the easy ones; report what *you* measure**.

---

## 8. Validation method
* **SNR** = 10·log₁₀(Σ ref² / Σ (y − ref)²), all in int16-LSB units; also reported with the error's DC removed (`SNR, DC removed`) because a constant offset is harmless for AC-coupled ECG but dominates the plain SNR when bias is large.
* **Ceiling** = same formula for `round(ref)`: the best any int16 output can do on this signal.
* **ENOB** = (SNR − 1.76)/6.02 is in the CSV.
* **Max abs error** in LSB and µV (1 LSB = 0.1526 µV). For reference, an ECG diagnostic tolerance of a few µV is ≈ 10–30 LSB.
* `--cross host_run.log` verifies the MCU's integer outputs are *bit-identical* to the host build (float rows may differ by < 1 LSB because of FMA/summation order).
* Overlays (`*_overlay.png`), SNR bars (`*_snr.png`), block-size sweep (`*_block_sweep.png`, hardware only), R-peak plot (`*_peaks.png`) and frequency responses (`freq_responses.png`).

---

## 9. Results

### 9.1 What I measured (sandbox: synthetic ECG, QEMU Cortex-M4, flash/RAM via `footprint.py`)
*Data-dependent columns (SNR) are for the synthetic signal – do not quote. Flash/RAM Δ are measured and are independent of the data; they are the **stand-alone** cost of
each implementation over a framework-only baseline of **13 344 B flash / 19 024 B RAM** (7 200 B of that flash is the test vector; 14 400 B of the RAM is the shared output buffer).*

| Implementation | flash Δ (B) | RAM Δ (B) | SNR (dB) | SNR, DC removed (dB) | max abs err (LSB) | bias (LSB) | cycles/sample | CPU load @360 Hz |
|---|---|---|---|---|---|---|---|---|
| `fir63_f32` | 560 | 776 | 133.2 | 133.2 | 0.00 | +0.00 | *measure* | *measure* |
| `fir127_f32` | 816 | 1032 | 131.6 | 131.6 | 0.00 | +0.00 | *measure* | *measure* |
| `fir255_f32` | 1328 | 1544 | 129.1 | 129.1 | 0.01 | +0.00 | *measure* | *measure* |
| `fir63_q15` | 464 | 392 | 70.4 | 74.8 | 1.33 | -0.45 | *measure* | *measure* |
| `fir127_q15` | 592 | 520 | 68.7 | 74.3 | 1.39 | -0.55 | *measure* | *measure* |
| `fir255_q15` | 848 | 776 | 66.5 | 70.8 | 1.92 | -0.59 | *measure* | *measure* |
| `fir63_q15m` | 588 | 384 | 74.5 | 74.6 | 1.13 | +0.05 | *measure* | *measure* |
| `fir127_q15m` | 716 | 512 | 74.3 | 74.4 | 0.95 | -0.05 | *measure* | *measure* |
| `fir255_q15m` | 976 | 768 | 70.6 | 70.8 | 1.39 | -0.09 | *measure* | *measure* |
| `iir2_f32` | 368 | 32 | 80.8 | 80.8 | 0.36 | +0.00 | *measure* | *measure* |
| `iir4_f32` | 408 | 48 | 76.5 | 76.6 | 0.45 | -0.01 | *measure* | *measure* |
| `iir2_q15` | 456 | 40 | -16.6 | -4.4 | 11633.22 | -8262.94 | *measure* | *measure* |
| `iir4_q15` | 480 | 56 | -28.5 | -14.7 | 39612.84 | -31034.58 | *measure* | *measure* |
| `iir2_q31` | 452 | 64 | 82.4 | 97.5 | 0.10 | -0.09 | *measure* | *measure* |
| `iir4_q31` | 492 | 96 | 75.3 | 90.6 | 0.26 | -0.20 | *measure* | *measure* |
| `iirh_f32` | 388 | 40 | 114.0 | 114.0 | 0.01 | -0.00 | *measure* | *measure* |
| `iirh_q15` | 468 | 48 | 23.1 | 42.3 | 108.95 | -92.10 | *measure* | *measure* |
| `iirh_q15r` | 412 | 32 | 50.1 | 50.5 | 14.72 | -1.30 | *measure* | *measure* |
| `iirh_q31` | 472 | 80 | 119.1 | 131.7 | 0.00 | -0.00 | *measure* | *measure* |
| `pt_q15` (detector) | 1396 | 1356 | - | - | - | - | *measure* | *measure* |

Whole image with everything enabled (Nucleo-F411RE build): **22 464 B flash (4.3 % of 512 KB), 23 600 B static RAM (18 %), stack high-water 840 B** (QEMU) → ≈ 24.4 KB RAM.
Full detail: `results/example_synthetic/map_report_nucleo.md`.

Reading the table:
* **FIR f32 ≈ 130 dB** vs the float64 reference: float32's own error (not a bug – 24-bit mantissa).
* **CMSIS Q15 FIR sits ≈ 4–6 dB below the manual FIR** (truncation bias −0.5 LSB vs rounding); both are within ~2–6 dB of the 74–76 dB int16 ceiling. SNR drifts down slightly with FIR length (more terms, longer coefficient set).
* **`iirK_q15` is unusable at this corner (§5.6)**; `iirh_q15r` (50 dB) and `iirK_q31` (75–82 dB) are the working fixed-point IIRs.
* **FIR Q15 RAM** is dominated by CMSIS state (`numTaps+block` words) – Q15 halves it vs float.

### 9.2 What YOU must fill in: cycles, latency, CPU load (hardware)
Run §2.4. `validate.py` then writes `results/mcu_results_table.md` with every column below filled in from the DWT counter. How each number is obtained:

| Column | Source | Formula |
|---|---|---|
| cycles/sample | `#STAT … total_cycles / samples` (2nd, warm pass; measurement overhead removed) | – |
| CPU load @ 360 Hz | derived | `cycles_per_sample × 360 / f_cpu × 100 %` |
| worst block (ms) | `max_block_cycles` | `/ f_cpu × 1000` |
| I/O latency (ms) | derived | `N/fs·1000 + worst block ms`  (N = 36 → 100 ms fill) |
| group delay (ms) | exported by Python | FIR (N−1)/2/fs; IIR at 10 Hz |
| flash / RAM | `footprint.py` | as §4.3 |
| error (dB) | `validate.py` | §8 |

`f_cpu` = `#META,cpu_hz` (16 MHz default; 96 MHz with `ECG_USE_PLL=1`).

**Expected ranges** (plausibility bands from instruction counts of the inner loops on a Cortex-M4F with zero/low wait states; *not* measurements. If you land more than ~3× outside, suspect a wrong clock, `-O0`, a Debug build, caches/ART disabled or the wrong `cpu_hz`):

| Implementation | Expected cycles/sample |
|---|---|
| `fir{N}_q15` (SMLALD dual-MAC) | ≈ (0.5 … 1.5) × N  |
| `fir{N}_f32` (VMLA) | ≈ (1 … 3) × N  |
| `fir{N}_q15m` (manual, QADD per tap) | ≈ (4 … 8) × N  → several × slower than `_q15` |
| `iirK_*` per section | Q15 ≈ 12–25, f32 DF2T ≈ 8–20, Q31 ≈ 20–40 cycles; multiply by the number of sections (3 or 5; `iirh` 4) |
| `pt_q15` | ≈ 100 … 300 |
| timing overhead (`#META`) | ≈ 1 … 4 cycles |

**Worked CPU-load arithmetic (hypothetical numbers, to show the formula):** if `fir255_q15` needed 300 cycles/sample at 16 MHz, load = 300 × 360 / 16 000 000 = 0.68 %. At fs = 360 Hz even the slowest implementation here should leave > 90 % idle; the interesting comparison is **energy** (idle % ⇒ sleep time) and **latency**, not feasibility.
Block-size sweep: expect cycles/sample to fall steeply from block = 1 to ≈ 16 (call + state load/store overhead amortised) and flatten after; the curve is in `*_block_sweep.png`.

---

## 10. Trade-offs: accuracy vs speed vs memory

| Choice | Accuracy | Speed | Memory | Latency |
|---|---|---|---|---|
| float32 FIR/IIR | best (≥ 110 dB) | FPU: fast; **needs an FPU** (M4F/M7) | 2× Q15 | – |
| Q15 CMSIS FIR | ≈ 66–71 dB (≈ int16 ceiling − 5 dB) | fastest (SIMD) | smallest | FIR delay (N−1)/2 |
| Q15 manual FIR (round + saturate) | ≈ ceiling − 1…4 dB | several × slower | small | same |
| Q31 | ≥ float | ≈ 1.5–2× Q15 | 2× | – |
| IIR vs FIR | IIR: 5–6 coefficients/section, tiny state, **but** ill-conditioned at 0.5 Hz | IIR ≈ 3–15× fewer cycles than a 255-tap FIR (expected: ≈3× vs Q15, ≈15× vs f32 – measure) | IIR ≪ FIR | IIR ≈ 7–13 ms vs FIR 86–353 ms; IIR is non-linear-phase (distorts ST segment morphology) |
| Block size | – | larger = lower overhead/sample | state ∝ block | latency ∝ block (N/fs) |

Rule of thumb from this project: **fixed-point is "free" for FIRs, treacherous for narrow, low-frequency IIRs**; choose the arithmetic *after* looking at the pole radius.

---

## 11. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| CMake: `Missing third_party/...` or `Missing .../ecg_params.h` | run `./scripts/fetch_deps.sh` and `python scripts/export_headers.py` |
| `export_headers.py` cannot download | PhysioNet blocked/offline: copy `100.dat 100.hea 100.atr` into `data/mitdb/`, or use `--source synthetic` for a smoke test only |
| No UART output | wrong port (`capture_uart.py --list`); started capture *after* reset (the program runs once – press RESET again); baud mismatch (`-DECG_UART_BAUD` must equal `--baud`); with `nucleo-pll` capture at 460800; jumpers/ST-LINK VCP driver on Windows |
| Garbage characters / `validate.py` reports missing samples | baud error: HSI is ±1 %; try 115200 (not 460800) without the PLL; use a short USB cable |
| Immediately HardFaults / works in debug only | FPU not enabled (CPACR) – done in `SystemInit`; if you replaced startup, copy that line. Also never run the QEMU/semihosting build on hardware (BKPT without debugger faults) |
| `validate.py`: "input echo differs" | stale headers: re-run export **and rebuild** |
| `has_cycle_counter,0` on real hardware | some debug configs gate DWT; the firmware sets `TRCENA` itself – if still 0, a debugger session may have disabled trace (reset the board with the debugger detached) |
| Cycle counts 3–10× above expectation | `-O0` / Debug build (`-DCMAKE_BUILD_TYPE=Release`), flash wait states with ART disabled, wrong `cpu_hz`, or `ARM_MATH_DSP` not defined (check `-mcpu=cortex-m4`) |
| `iirK_q15` SNR is terrible | expected – §5.6 explains it; look at `iirh_q15r` / `iirK_q31` |
| `arm_fir_init_q15` returns error / FIR output is zero | tap count must be even (the exporter pads) – only matters if you hand-edit headers |
| Linker: `region RAM overflowed` | lower `--seconds` (output buffer = N×4 B) or disable groups with `-DECG_ENABLE_*=0` |
| Renode: floods of `0xE0001004` warnings | DWT not modelled; the script sets `logLevel 3` to hide them. Cycle counts from Renode are meaningless |
| Renode prints `Failed to download ... .svd.gz` | it tries to fetch a peripheral-description file; harmless offline – the run proceeds |
| Renode: log empty | `CreateFileBackend` needs an absolute path: use `run_renode.sh`; check `$RENODE` |
| QEMU prints nothing on stdout | semihosting console goes to **stderr** (`2> results/qemu_run.log`) |

---

## 12. Interview Q&A

**Q1. Why Q15 and not float on a Cortex-M4F?** The M4F has an FPU, so float is fine here. Q15 matters on FPU-less cores (M0/M3/M0+), for energy (integer SIMD does two MACs per cycle), and for memory (half the state). This project measures the cost of that choice.

**Q2. What does Q1.15 mean and what is the product format?** 1 sign bit, 15 fraction bits, value = int/2¹⁵. Q15×Q15 = Q2.30; shift right 15 and saturate to return to Q15.

**Q3. Overflow vs saturation?** Wrap-around turns +full-scale into −full-scale (a spike); saturation clamps. Use saturating ops (SSAT/QADD) where narrowing; use a wide accumulator where it is free (SMLALD 64-bit).

**Q4. Why ~6 dB per bit?** Quantisation step halves per bit; noise power Δ²/12 drops 4× = 6.02 dB. SQNR = 6.02B + 1.76 dB for a full-scale sine; an ECG that uses only a fraction of full scale gets less.

**Q5. What is `postShift` in the CMSIS Q15 biquad?** The coefficients are stored as `c·2^(15−p)` and the 64-bit accumulator is shifted right by `15−p`. It lets coefficients up to ±2^p be represented (a1 ≈ 1.98 needs p=1) at the cost of p bits of coefficient precision.

**Q6. CMSIS biquad quirks?** a1/a2 sign-flipped vs scipy; Q15 layout is 6 per stage with a padding zero; state 4 words per stage; DF1 for fixed-point, DF2T for float.

**Q7. Your Q15 IIR gave −16 dB. How did you debug it?** Wrote a bit-exact Python model of the kernel (verified equal to the C output), then computed A(1)=1+a1+a2 ≈ 7.7e-5 for the 0.5 Hz section: equal to one coefficient LSB, so the DC gain is quantisation noise, and the −0.5 LSB truncation bias × 1/A(1)≈12 900 gives thousands of LSB of offset. Fixed by Q31, or by restructuring into first-order sections plus round-to-nearest (50 dB).

**Q8. Why does truncation matter?** Floor-shifting biases every output by −½ LSB. In an FIR that is a small DC error; in an IIR it is injected inside the feedback loop and amplified by the loop's DC gain.

**Q9. FIR vs IIR for ECG?** FIR: linear phase (no morphology distortion), always stable, trivially fixed-point, but long (0.5 Hz edge needs thousands of taps) and delayed 86–353 ms. IIR: few coefficients and ms of delay, but non-linear phase and ill-conditioned for narrow low-frequency features. Clinical standards (e.g. AHA) care about phase for ST analysis; monitors often use forward-backward or linear-phase high-pass.

**Q10. How did you measure cycles?** DWT->CYCCNT around `process()`, overhead of the read pair subtracted, two passes (warm-up discarded), max block for worst case; converted with the real core clock. QEMU/Renode lack DWT, so I used them only for functional checks.

**Q11. How did you verify the embedded code without hardware?** Host build of the same portable C, plus the real Thumb-2 binary in QEMU and Renode; integer outputs were bit-identical across the three, and a Python bit-exact model matched too. Hardware then only adds timing.

**Q12. Why block processing?** Amortises call/state overhead, lets SIMD kernels run on long vectors, and allows sleeping between blocks – at the cost of N/fs latency. The block-size sweep quantifies it.

**Q13. What limits your latency?** T_fill (N/fs) + compute (max block cycles/f_cpu) + the filter's group delay; the last dominates for long FIRs.

**Q14. How is stack usage measured?** Stack painting: fill free RAM with a pattern, run, scan from the bottom for the first overwritten word. There is no heap, so static RAM + stack high-water is the full memory story.

**Q15. What would you change for a live ADC?** Timer-triggered ADC so the sample period is exact, ISR pushes into the SPSC ring (`ecg_source_ring`), main loop sleeps (WFI) and processes full blocks; change the notch to the local mains frequency; use DMA double-buffering for higher rates.

**Q16. Pan-Tompkins in fixed point – what's tricky?** Dynamic range: squaring needs 32 bits, the window sum needs a pre-shift to avoid overflow, thresholds are absolute counts (so they depend on gain/full-scale), and windows must be rescaled from the 200 Hz of the paper to 360 Hz.

---

## 13. Day-by-day checklist (≈ 7 working days)

- [ ] **Day 1 – environment.** Install toolchain, `pip install -r requirements.txt`, `./scripts/fetch_deps.sh`. `python scripts/export_headers.py` (real record 100). Read the quantisation report; open `results/meta.json`. *Commit.*
- [ ] **Day 2 – host build.** `make host-run`. Confirm "input echo identical". Read `results/host_results_table.md`; look at `host_overlay.png`. Run `python scripts/plot_responses.py`. Explain to yourself why FIR f32 ≈ 130 dB and Q15 ≈ 70 dB.
- [ ] **Day 3 – simulators.** `make qemu-run`, then Renode (`make renode-run`). Check `--cross` says integer rows are bit-identical. Run `python scripts/diagnose_q15_iir.py`; write 5 lines on why Butterworth Q15 fails.
- [ ] **Day 4 – hardware bring-up.** `make nucleo`, flash, `capture_uart.py`, press RESET. Get a clean log (`#DONE`). Run `validate.py --label mcu --cross results/host_run.log`.
- [ ] **Day 5 – measurements.** Fill §9.2: cycles/sample, CPU load, latency from `mcu_results_table.md`; run `footprint.py` and `map_report.py`; compare to the expected-range table; try `make nucleo-pll` and `-DECG_BLOCK_SIZE`. Save `*_block_sweep.png`.
- [ ] **Day 6 – experiments.** Sweep `--fir-taps`, `--iir-scale none|linf`, `-Os`/`-O3` (footprint with `--opt`). Long-record R-peak evaluation (§7). Try a different segment (`--start 600`) or a record with arrhythmias.
- [ ] **Day 7 – portfolio polish.** Replace `results/example_synthetic` references with *your* `results/` outputs; add your table to the README (§9.2); add a photo of the board + terminal screenshot; rehearse the interview Q&A; tag `v1.0`.
- [ ] **Stretch.** ADC+TIM2 live input through `ecg_source_ring`; `arm_biquad_cas_df1_32x64_q31`; int8 classifier from ecg-ml with CMSIS-NN.

---

## 14. Known limitations
* Not run on real silicon or on real MIT-BIH data by the author of this scaffold; the synthetic-data numbers are for pipeline checking only.
* QEMU/Renode give functional results, not timing.
* `ECG_USE_PLL=1` (96 MHz) and the PlatformIO config are untested.
* The FIR high-pass edge at 0.5 Hz is soft by construction (§6).
* Pan-Tompkins thresholds (`PT_MIN_THR`) are in absolute counts for the ±5 mV full-scale convention; change them if you change the scaling.
* CMSIS-DSP's generic C kernels (host) and SIMD kernels (M4) produced identical integers *here*; other CMSIS-DSP versions may differ in rounding details – keep the pinned versions.

Licence: MIT for this repository's code; CMSIS-DSP/CMSIS-Core are Apache-2.0; STM32 device headers are under ST's licence; MIT-BIH data are under the PhysioNet Open Data licence.
