/* ecg_pipeline.h - block-based processing loop with cycle-accurate timing. */
#ifndef ECG_PIPELINE_H
#define ECG_PIPELINE_H

#include "ecg_impl.h"
#include "ecg_source.h"

typedef struct {
    uint32_t samples;            /* samples processed                                         */
    uint32_t blocks;             /* process() calls                                           */
    uint32_t block;              /* configured block size                                     */
    uint64_t total_cycles;       /* sum of CPU cycles spent inside process()                  */
    uint32_t max_block_cycles;   /* WORST block  -> worst-case compute latency                */
    uint32_t min_block_cycles;   /* best block                                                */
    uint32_t rail_hits;          /* output samples sitting exactly on a +/- full-scale rail   */
} ecg_stats_t;

/* Measure the cost of reading the cycle counter itself (subtracted from every block). */
void ecg_pipeline_calibrate(void);
uint32_t ecg_pipeline_overhead(void);

/* Run `impl` over the whole stream.
 *   block        : samples per process() call (1 .. ECG_MAX_BLOCK_SIZE)
 *   out          : buffer for `out_capacity` elements of impl->fmt
 * For rewindable sources the stream is processed TWICE: pass 1 warms caches / flash prefetch
 * and is discarded; pass 2 is measured.  Returns 0 on success. */
int ecg_pipeline_run(const ecg_impl_t *impl, const ecg_source_t *src, uint32_t block,
                     void *out, uint32_t out_capacity, ecg_stats_t *st);

#endif /* ECG_PIPELINE_H */
