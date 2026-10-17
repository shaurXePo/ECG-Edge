/* ecg_source_ring.c - interrupt-fed single-producer / single-consumer ring buffer.
 *
 * This is where a real ADC or UART byte stream plugs in (see ecg_source.h for the wiring).
 * Lock-free SPSC: only the ISR writes `head`, only the main loop writes `tail`; indices are
 * volatile and the buffer size is a power of two so wrap-around is a mask.  On a Cortex-M a
 * 32-bit aligned store is atomic, which is all this scheme needs.
 */
#include "ecg_source.h"

#define RING_SIZE 512u                     /* power of two; 512 samples = 1.4 s of ECG at 360 Hz */
#define RING_MASK (RING_SIZE - 1u)

static q15_t             s_ring[RING_SIZE];
static volatile uint32_t s_head;           /* next write position (ISR)  */
static volatile uint32_t s_tail;           /* next read position  (main) */
static volatile uint32_t s_closed;
static volatile uint32_t s_overruns;

void ecg_source_ring_push(q15_t sample)    /* call from the ADC/UART ISR */
{
    uint32_t h = s_head;
    if (((h + 1u) & RING_MASK) == s_tail) { s_overruns++; return; }   /* full: drop, never block an ISR */
    s_ring[h] = sample;
    s_head = (h + 1u) & RING_MASK;
}

void     ecg_source_ring_close(void)    { s_closed = 1u; }
uint32_t ecg_source_ring_overruns(void) { return s_overruns; }

static uint32_t ring_avail(void) { return (s_head - s_tail) & RING_MASK; }

static uint32_t ring_read(q15_t *dst, uint32_t max)
{
    /* Block until a FULL block is available (keeps the filter's block size constant),
     * or until the producer says the stream is over and drain whatever is left. */
    while (ring_avail() < max && !s_closed) {
#if defined(__ARM_ARCH)
        __asm volatile("wfi");             /* sleep until the next sample interrupt */
#endif
    }
    uint32_t n = ring_avail();
    if (n > max) n = max;
    for (uint32_t i = 0; i < n; i++) {
        dst[i] = s_ring[s_tail];
        s_tail = (s_tail + 1u) & RING_MASK;
    }
    return n;                              /* 0 only after close() and an empty ring */
}

const ecg_source_t ecg_source_ring = { "ring", NULL, ring_read };
