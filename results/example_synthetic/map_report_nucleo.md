# Image size (from the linker map)

| Section | Bytes |
|---|---|
| .isr_vector | 392 |
| .text | 9524 |
| .rodata | 12476 |
| .data | 40 |
| .bss | 23560 |

* **Flash used** = 22432 B of 524288 B (4.3 %)
* **Static RAM** (.data+.bss) = 23600 B of 131072 B (18.0 %)
* **Stack high-water mark** (stack painting) = 840 B (of 107472 B left between .bss and the top of RAM)
* **Total RAM footprint** = 24440 B

## Top 8 symbols by size

| Size (B) | Type | Symbol |
|---|---|---|
| 14400 | b | `g_out` |
| 7200 | r | `ecg_testvec` |
| 1536 | b | `st_fir255_f32` |
| 1328 | b | `s_pt` |
| 1328 | T | `ecg_app_run` |
| 1024 | b | `st_fir127_f32` |
| 1024 | r | `ecg_fir255_f32` |
| 824 | t | `proc_pt` |
