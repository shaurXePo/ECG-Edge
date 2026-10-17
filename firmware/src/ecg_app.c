/* ecg_app.c - portable application logic (no hardware access except through ecg_platform.h).
 *
 * Output grammar (parsed by scripts/common.py:parse_log):
 *   #META,key,value                       one-off facts about this run
 *   #BEGIN,name,fmt,count                 start of a sample series ...
 *   idx,value                             ...  one line per sample, value in int16-LSB units
 *   #END,name
 *   #STAT,name,samples,blocks,block,total_cycles,max_block_cycles,min_block_cycles,rail_hits
 *   #SWEEP,<same fields>                  block-size sweep (no sample dump)
 *   #PEAK,idx                             detected R peaks (Pan-Tompkins)
 *   #STACK,used_bytes,total_bytes         stack high-water mark
 *   #DONE
 */
#include <string.h>
#include "ecg_app.h"
#include "ecg_impl.h"
#include "ecg_pipeline.h"
#include "ecg_platform.h"
#include "ecg_out.h"
#include "ecg_pan_tompkins.h"

/* Output buffer shared by all implementations: one run at a time, so a union is enough.
 * Size = N samples * 4 bytes (float / q31 worst case). */
static union {
    q15_t   q15[ECG_N_SAMPLES];
    q31_t   q31[ECG_N_SAMPLES];
    float32_t f32[ECG_N_SAMPLES];
} g_out;

/* Block sizes for the sweep (1 = pure sample-by-sample, 128 = ECG_MAX_BLOCK_SIZE). */
static const uint32_t k_sweep[] = { 1u, 4u, 16u, 36u, 64u, 128u };

void ecg_app_default_opts(ecg_app_opts_t *o)
{
    o->block = ECG_BLOCK_SIZE; o->dump = 1; o->sweep = 1; o->pt_only = 0; o->only = NULL;
}

static void meta_u(const char *k, uint32_t v)
{
    ecg_out_puts("#META,"); ecg_out_puts(k); ecg_out_puts(","); ecg_out_u64(v); ecg_out_nl();
}
static void meta_s(const char *k, const char *v)
{
    ecg_out_puts("#META,"); ecg_out_puts(k); ecg_out_puts(","); ecg_out_puts(v); ecg_out_nl();
}

static void print_stat(const char *tag, const char *name, const ecg_stats_t *s)
{
    ecg_out_puts("#"); ecg_out_puts(tag); ecg_out_puts(","); ecg_out_puts(name);
    ecg_out_puts(","); ecg_out_u64(s->samples);
    ecg_out_puts(","); ecg_out_u64(s->blocks);
    ecg_out_puts(","); ecg_out_u64(s->block);
    ecg_out_puts(","); ecg_out_u64(s->total_cycles);
    ecg_out_puts(","); ecg_out_u64(s->max_block_cycles);
    ecg_out_puts(","); ecg_out_u64(s->min_block_cycles);
    ecg_out_puts(","); ecg_out_u64(s->rail_hits);
    ecg_out_nl();
}

/* Print sample i of a buffer, in int16-LSB units regardless of the underlying format. */
static void print_sample(ecg_fmt_t fmt, const void *buf, uint32_t i)
{
    switch (fmt) {
    case ECG_FMT_Q15: ecg_out_i32(((const q15_t *)buf)[i]); break;
    case ECG_FMT_Q31: ecg_out_fixed3(((const q31_t *)buf)[i], 16); break;      /* Q31 / 2^16 = Q15 LSBs  */
    default:          ecg_out_f32_3dp(((const float32_t *)buf)[i] * 32768.0f); break;  /* 1.0 = full scale */
    }
}

static void dump_series(const char *name, ecg_fmt_t fmt, const void *buf, uint32_t n)
{
    ecg_out_puts("#BEGIN,"); ecg_out_puts(name);
    ecg_out_puts(fmt == ECG_FMT_Q15 ? ",q15," : fmt == ECG_FMT_Q31 ? ",q31," : ",f32,");
    ecg_out_u64(n); ecg_out_nl();
    for (uint32_t i = 0; i < n; i++) {
        ecg_out_u64(i); ecg_out_puts(","); print_sample(fmt, buf, i); ecg_out_nl();
    }
    ecg_out_puts("#END,"); ecg_out_puts(name); ecg_out_nl();
}

static int is_pt(const ecg_impl_t *im) { return im->name[0] == 'p' && im->name[1] == 't'; }

int ecg_app_run(const ecg_app_opts_t *o)
{
    platform_init();
    platform_stack_paint();                     /* must happen BEFORE the deep call chains below */
    ecg_pipeline_calibrate();

    ecg_out_puts("#ECG_EDGE,1"); ecg_out_nl();
    meta_s("platform", platform_name());
    meta_s("compiler", __VERSION__);
    meta_s("record", ECG_RECORD_NAME);
    meta_u("fs_hz", ECG_FS_HZ);
    meta_u("n_samples", ECG_N_SAMPLES);
    meta_u("cpu_hz", platform_cpu_hz());
    meta_u("has_cycle_counter", (uint32_t)platform_has_cycle_counter());
    meta_u("timing_overhead_cycles", ecg_pipeline_overhead());
    meta_u("block_size", o->block);
    meta_u("max_block_size", ECG_MAX_BLOCK_SIZE);

    const ecg_source_t *src = &ecg_source_vector;       /* <-- swap for &ecg_source_ring to use a live stream */

    if (o->dump) {                                      /* echo the input: proves the data path is intact */
        static q15_t blk[ECG_MAX_BLOCK_SIZE];
        uint32_t idx = 0, n;
        src->rewind();
        ecg_out_puts("#BEGIN,input,q15,"); ecg_out_u64(ECG_N_SAMPLES); ecg_out_nl();
        while ((n = src->read(blk, ECG_MAX_BLOCK_SIZE)) != 0u) {
            for (uint32_t i = 0; i < n; i++) { ecg_out_u64(idx++); ecg_out_puts(","); ecg_out_i32(blk[i]); ecg_out_nl(); }
        }
        ecg_out_puts("#END,input"); ecg_out_nl();
    }

    /* ---- main pass: one run per implementation, full dump ---- */
    for (uint32_t g = 0; g < ecg_group_count; g++) {
        for (uint32_t k = 0; k < ecg_groups[g]->count; k++) {
            const ecg_impl_t *im = &ecg_groups[g]->impls[k];
            if (o->only && strcmp(o->only, im->name) != 0) continue;
            if (o->pt_only && !is_pt(im)) continue;

            ecg_stats_t st;
            if (ecg_pipeline_run(im, src, o->block, &g_out, ECG_N_SAMPLES, &st) != 0) continue;
            print_stat("STAT", im->name, &st);
#if ECG_ENABLE_PT
            if (is_pt(im)) {
                for (uint32_t p = 0; p < ecg_pt_peak_count(); p++) {
                    ecg_out_puts("#PEAK,"); ecg_out_i32(ecg_pt_peak_index(p)); ecg_out_nl();
                }
            }
#endif
            if (o->dump && !o->pt_only) dump_series(im->name, im->fmt, &g_out, st.samples);
        }
    }

    /* ---- block-size sweep: timing only (pure overhead vs block size) ---- */
    if (o->sweep) {
        for (uint32_t g = 0; g < ecg_group_count; g++) {
            for (uint32_t k = 0; k < ecg_groups[g]->count; k++) {
                const ecg_impl_t *im = &ecg_groups[g]->impls[k];
                if (o->only && strcmp(o->only, im->name) != 0) continue;
                if (o->pt_only && !is_pt(im)) continue;
                for (uint32_t b = 0; b < ECG_ARRAY_LEN(k_sweep); b++) {
                    ecg_stats_t st;
                    if (k_sweep[b] > ECG_MAX_BLOCK_SIZE) continue;
                    if (ecg_pipeline_run(im, src, k_sweep[b], &g_out, ECG_N_SAMPLES, &st) == 0)
                        print_stat("SWEEP", im->name, &st);
                }
            }
        }
    }

    ecg_out_puts("#STACK,"); ecg_out_u64(platform_stack_used());
    ecg_out_puts(","); ecg_out_u64(platform_stack_total()); ecg_out_nl();
    ecg_out_puts("#DONE"); ecg_out_nl();
    platform_flush();
    return 0;
}
