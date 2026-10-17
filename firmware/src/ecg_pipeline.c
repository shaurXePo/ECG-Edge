/* ecg_pipeline.c - block loop: source -> filter -> output buffer, timed with the cycle counter. */
#include "ecg_pipeline.h"
#include "ecg_platform.h"

static uint32_t s_overhead;                    /* cycles consumed by one start/stop timestamp pair */
static q15_t    s_in[ECG_MAX_BLOCK_SIZE];      /* input block (shared by every implementation)    */

void ecg_pipeline_calibrate(void)
{
    /* Back-to-back reads: the difference is the cost of the measurement itself. Keep the minimum
     * of 32 tries so an unlucky interrupt/prefetch stall does not inflate it. */
    uint32_t best = 0xFFFFFFFFu;
    for (int i = 0; i < 32; i++) {
        uint32_t t0 = platform_cycles();
        uint32_t t1 = platform_cycles();
        if ((t1 - t0) < best) best = t1 - t0;
    }
    s_overhead = best;
}

uint32_t ecg_pipeline_overhead(void) { return s_overhead; }

int ecg_pipeline_run(const ecg_impl_t *impl, const ecg_source_t *src, uint32_t block,
                     void *out, uint32_t out_capacity, ecg_stats_t *st)
{
    if (block == 0u || block > ECG_MAX_BLOCK_SIZE) return -1;
    const uint32_t esz    = ecg_fmt_size(impl->fmt);
    const int      passes = (src->rewind != NULL) ? 2 : 1;      /* pass 0 = warm-up (untimed)  */

    for (int pass = 0; pass < passes; pass++) {
        const int measure = (pass == passes - 1);
        memset(st, 0, sizeof(*st));
        st->block = block;
        st->min_block_cycles = 0xFFFFFFFFu;
        if (src->rewind) src->rewind();
        impl->init(block);                                       /* zero filter state */

        uint32_t idx = 0, n;
        while ((n = src->read(s_in, block)) != 0u) {
            if (idx + n > out_capacity) n = out_capacity - idx;  /* output buffer full: stop */
            if (n == 0u) break;

            uint32_t t0 = platform_cycles();
            impl->process(s_in, (uint8_t *)out + (size_t)idx * esz, n);
            uint32_t dt = platform_cycles() - t0;                /* unsigned wrap-safe subtraction */
            dt = (dt > s_overhead) ? dt - s_overhead : 0u;

            if (measure) {
                st->total_cycles += dt;
                if (dt > st->max_block_cycles) st->max_block_cycles = dt;
                if (dt < st->min_block_cycles) st->min_block_cycles = dt;
                st->blocks++;
            }
            idx += n;
        }
        st->samples = idx;
    }

    /* Count outputs that sit on a full-scale rail (saturation / clipping indicator). */
    if (impl->fmt == ECG_FMT_Q15) {
        const q15_t *p = (const q15_t *)out;
        for (uint32_t i = 0; i < st->samples; i++) if (p[i] == 32767 || p[i] == -32768) st->rail_hits++;
    } else if (impl->fmt == ECG_FMT_Q31) {
        const q31_t *p = (const q31_t *)out;
        for (uint32_t i = 0; i < st->samples; i++) if (p[i] == INT32_MAX || p[i] == INT32_MIN) st->rail_hits++;
    }
    if (st->min_block_cycles == 0xFFFFFFFFu) st->min_block_cycles = 0;
    return 0;
}
