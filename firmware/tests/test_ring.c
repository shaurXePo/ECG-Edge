/* test_ring.c - host unit test for the ISR-fed ring-buffer source (the ADC/UART hook).
 * Build + run:  cmake --build build/host --target test_ring && ./build/host/test_ring */
#include <stdio.h>
#include "ecg_source.h"

#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); return 1; } } while (0)

int main(void)
{
    q15_t blk[36];
    /* 1. 100 samples pushed "from the ISR", then end-of-stream: read() must return 36, 36, 28, 0 in order */
    for (int i = 0; i < 100; i++) ecg_source_ring_push((q15_t)(i * 7 - 300));
    ecg_source_ring_close();
    uint32_t n1 = ecg_source_ring.read(blk, 36); CHECK(n1 == 36); CHECK(blk[0] == -300 && blk[35] == 35 * 7 - 300);
    uint32_t n2 = ecg_source_ring.read(blk, 36); CHECK(n2 == 36); CHECK(blk[0] == 36 * 7 - 300);
    uint32_t n3 = ecg_source_ring.read(blk, 36); CHECK(n3 == 28); CHECK(blk[27] == 99 * 7 - 300);
    uint32_t n4 = ecg_source_ring.read(blk, 36); CHECK(n4 == 0);
    CHECK(ecg_source_ring_overruns() == 0);
    /* 2. consumer too slow: push more than the ring holds -> samples are DROPPED and counted, never block */
    for (int i = 0; i < 600; i++) ecg_source_ring_push(1);
    CHECK(ecg_source_ring_overruns() > 0);
    printf("test_ring: OK (overruns counted = %u)\n", (unsigned)ecg_source_ring_overruns());
    return 0;
}
