/* platform_cycles.h (host) - there is no cycle counter on a PC; return nanoseconds instead.
 * The numbers are NOT Cortex-M cycles.  The host build exists to validate NUMERICS and logic. */
#ifndef PLATFORM_CYCLES_H
#define PLATFORM_CYCLES_H
#include <stdint.h>
#include <time.h>

static inline uint32_t platform_cycles(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)((uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec);   /* wraps every 4.29 s: fine for deltas */
}
#endif
