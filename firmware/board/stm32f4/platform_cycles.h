/* platform_cycles.h (Cortex-M4) - the DWT cycle counter, read in ONE instruction (LDR). */
#ifndef PLATFORM_CYCLES_H
#define PLATFORM_CYCLES_H
#include "stm32f4xx.h"           /* pulls in core_cm4.h: DWT, CoreDebug */

static inline uint32_t platform_cycles(void) { return DWT->CYCCNT; }
#endif
