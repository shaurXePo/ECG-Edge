/* platform_host.c - run the portable firmware on a PC (Linux/macOS/WSL).
 *
 * Why: (1) CMSIS-DSP's C reference kernels give the same integer results as the Cortex-M4
 * SIMD kernels, so numerical validation needs no hardware; (2) debugging with gdb/valgrind/
 * sanitizers is far easier on a PC.  Timing from this target is meaningless for the MCU.
 */
#include <stdio.h>
#include <stdlib.h>
#include "ecg_platform.h"

void        platform_init(void)               { static char buf[1 << 16]; setvbuf(stdout, buf, _IOFBF, sizeof buf); }
void        platform_putc(char c)             { fputc(c, stdout); }
void        platform_flush(void)              { fflush(stdout); }
uint32_t    platform_cpu_hz(void)             { return 1000000000u; }        /* "cycles" are nanoseconds */
const char *platform_name(void)               { return "host (timing in ns, NOT cycles)"; }
int         platform_has_cycle_counter(void)  { return 0; }
void        platform_stack_paint(void)        { }
uint32_t    platform_stack_used(void)         { return 0; }
uint32_t    platform_stack_total(void)        { return 0; }
void        platform_exit(int code)           { fflush(stdout); exit(code); }
