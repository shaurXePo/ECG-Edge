/* ecg_platform.h - THE boundary between portable code and the board.
 *
 * Everything in firmware/src depends only on this header.  A new board needs exactly one
 * file implementing these functions plus a platform_cycles.h next to it (see board/host and
 * board/stm32f4 for two complete examples).
 */
#ifndef ECG_PLATFORM_H
#define ECG_PLATFORM_H

#include <stdint.h>
#include "platform_cycles.h"     /* provided by the selected board dir: static inline uint32_t platform_cycles(void) */

void        platform_init(void);               /* clocks, UART, cycle counter                       */
void        platform_putc(char c);             /* blocking character output (UART / semihosting)    */
void        platform_flush(void);              /* wait until everything has physically left         */
uint32_t    platform_cpu_hz(void);              /* core clock in Hz  (cycles -> seconds)             */
const char *platform_name(void);
int         platform_has_cycle_counter(void);  /* 0 if DWT is absent/unimplemented (some simulators) */

/* Stack high-water-mark measurement ("stack painting").  Host builds report 0. */
void        platform_stack_paint(void);
uint32_t    platform_stack_used(void);          /* bytes ever used since paint */
uint32_t    platform_stack_total(void);         /* bytes available for stack   */

void        platform_exit(int code) __attribute__((noreturn));

#endif /* ECG_PLATFORM_H */
