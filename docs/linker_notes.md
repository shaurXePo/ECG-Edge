# Linker-script notes (firmware/board/stm32f4/ld/)

Two small files per chip + one shared file:

| File | Role |
|---|---|
| `stm32f411re.ld` | `MEMORY` for the Nucleo-F411RE: FLASH 512 KiB @ 0x0800_0000, RAM 128 KiB @ 0x2000_0000 |
| `stm32f407vg.ld` | `MEMORY` for Renode's F407 model / QEMU F405: FLASH 1 MiB, RAM 128 KiB (CCM RAM unused on purpose) |
| `stm32f4_sections.ld` | placement of `.isr_vector`, `.text`, `.rodata`, `.data`, `.bss`, stack reserve |

**To port to another Cortex-M4 part** (F446, L4, G4 ...): copy `stm32f411re.ld`, change the two
`ORIGIN/LENGTH` pairs, keep `INCLUDE stm32f4_sections.ld`. Then replace `board/stm32f4/` register
code (UART pins, clock tree) - everything under `firmware/src` stays untouched.

## What each symbol is for
* `_estack` - top of RAM, the initial stack pointer (vector[0]). The stack grows **down** from here.
* `_sidata` - flash address (LMA) of the initial values of `.data`; `Reset_Handler` copies `_sidata.._sidata+size` -> `_sdata.._edata`.
* `_sbss/_ebss` - zeroed by `Reset_Handler`.  **`_ebss` is also the lowest address the stack may reach**
  (no heap): `platform_stack_paint()` fills `_ebss .. SP-64` with `0xA5A5A5A5` and
  `platform_stack_used()` finds the deepest word that was overwritten.
* `_Min_Stack_Size` (4 KiB) - the linker reserves this much *after* `.bss`; if static data grows so that
  less remains, the link **fails** instead of the stack silently corrupting `.bss` at run time.

## Flash / RAM numbers come from here
`-Wl,-Map=build/<dir>/ecg_edge.map` + `-Wl,--print-memory-usage` (printed at every link) +
`scripts/map_report.py` (parses the map) + `scripts/footprint.py` (per-implementation deltas).
`--gc-sections` + `-ffunction-sections -fdata-sections` are what make a disabled implementation cost zero bytes.

## Why no heap / newlib printf
`--specs=nano.specs --specs=nosys.specs` only supplies `memcpy/memset/strcmp`. Nothing calls `malloc`
or `printf`, so (a) the image is small, (b) all RAM is accounted for statically, (c) the stack
high-water mark is the whole story for dynamic memory.
