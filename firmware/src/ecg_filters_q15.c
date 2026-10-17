/* ecg_filters_q15.c - fixed-point Q15 implementations using CMSIS-DSP.
 *
 *   fir<N>_q15 : arm_fir_q15                    16x16->64-bit MACs (SMLALD on Cortex-M4),
 *                                               result >> 15 then SATURATED to 16 bit.
 *   iir<K>_q15 : arm_biquad_cascade_df1_q15     5 products summed in a 64-bit accumulator,
 *                                               result >> (15 - postShift), saturated to 16 bit.
 *
 * Things that are easy to get wrong (all handled by scripts/export_headers.py):
 *   * FIR coefficient order: CMSIS wants b[N-1] ... b[0] (time reversed).
 *   * FIR tap count must be EVEN on Cortex-M4 (zero pad added by the exporter).
 *   * Biquad layout is 6 values per stage {b0, 0, b1, b2, a1, a2}; a1,a2 carry the OPPOSITE
 *     sign to the textbook convention.
 *   * postShift: real coefficient = stored * 2^postShift / 2^15.  Our a1 ~ 1.99 does not fit
 *     in Q15 (< 1.0), so postShift >= 1 (coefficients in Q14) is mandatory.
 *   * CMSIS truncates (floors) the final shift instead of rounding -> a -0.5 LSB bias that
 *     the recursion feeds back; see README "fixed-point theory".
 */
#include "ecg_impl.h"
#include "ecg_coeffs.h"

#if ECG_ENABLE_FIR_Q15
#define DEF_FIR_Q15(N)                                                                          \
    static arm_fir_instance_q15 s_fir##N##_q15;                                                 \
    static q15_t st_fir##N##_q15[ECG_CAT3(ECG_FIR, N, _NTAPS) + ECG_MAX_BLOCK_SIZE]             \
        __attribute__((aligned(4)));                                                            \
    static void init_fir##N##_q15(uint32_t blk)                                                 \
    {                                                                                           \
        (void)arm_fir_init_q15(&s_fir##N##_q15, ECG_CAT3(ECG_FIR, N, _NTAPS), ecg_fir##N##_q15, \
                               st_fir##N##_q15, blk);                                           \
    }                                                                                           \
    static void proc_fir##N##_q15(const q15_t *in, void *out, uint32_t n)                       \
    {                                                                                           \
        arm_fir_q15(&s_fir##N##_q15, in, (q15_t *)out, n);                                      \
    }
ECG_FIR_LIST(DEF_FIR_Q15)

#define ENT_FIR_Q15(N) { "fir" #N "_q15", ECG_FMT_Q15, init_fir##N##_q15, proc_fir##N##_q15 },
static const ecg_impl_t k_fir_q15[] = { ECG_FIR_LIST(ENT_FIR_Q15) };
const ecg_group_t ecg_grp_fir_q15 = { k_fir_q15, ECG_ARRAY_LEN(k_fir_q15) };
#endif /* ECG_ENABLE_FIR_Q15 */

#if ECG_ENABLE_IIR_Q15
#define DEF_IIR_Q15(K)                                                                          \
    static arm_biquad_casd_df1_inst_q15 s_iir##K##_q15;                                         \
    static q15_t st_iir##K##_q15[4u * ECG_CAT3(ECG_IIR, K, _STAGES)] __attribute__((aligned(4))); \
    /* 4 state words per stage: x[n-1], x[n-2], y[n-1], y[n-2] */                               \
    static void init_iir##K##_q15(uint32_t blk)                                                 \
    {                                                                                           \
        (void)blk;                                                                              \
        arm_biquad_cascade_df1_init_q15(&s_iir##K##_q15, ECG_CAT3(ECG_IIR, K, _STAGES),         \
                                        ecg_iir##K##_q15, st_iir##K##_q15,                      \
                                        ECG_CAT3(ECG_IIR, K, _POSTSHIFT));                      \
    }                                                                                           \
    static void proc_iir##K##_q15(const q15_t *in, void *out, uint32_t n)                       \
    {                                                                                           \
        arm_biquad_cascade_df1_q15(&s_iir##K##_q15, in, (q15_t *)out, n);                       \
    }
ECG_IIR_LIST(DEF_IIR_Q15)

#define ENT_IIR_Q15(K) { "iir" #K "_q15", ECG_FMT_Q15, init_iir##K##_q15, proc_iir##K##_q15 },
static const ecg_impl_t k_iir_q15[] = { ECG_IIR_LIST(ENT_IIR_Q15) };
const ecg_group_t ecg_grp_iir_q15 = { k_iir_q15, ECG_ARRAY_LEN(k_iir_q15) };
#endif /* ECG_ENABLE_IIR_Q15 */

#if ECG_ENABLE_IIRH_Q15
static arm_biquad_casd_df1_inst_q15 s_iirh_q15;
static q15_t st_iirh_q15[4u * ECG_IIRH_STAGES] __attribute__((aligned(4)));
static void init_iirh_q15(uint32_t blk)
{
    (void)blk;
    arm_biquad_cascade_df1_init_q15(&s_iirh_q15, ECG_IIRH_STAGES, ecg_iirh_q15, st_iirh_q15, ECG_IIRH_POSTSHIFT);
}
static void proc_iirh_q15(const q15_t *in, void *out, uint32_t n)
{
    arm_biquad_cascade_df1_q15(&s_iirh_q15, in, (q15_t *)out, n);
}
static const ecg_impl_t k_iirh_q15[] = { { "iirh_q15", ECG_FMT_Q15, init_iirh_q15, proc_iirh_q15 } };
const ecg_group_t ecg_grp_iirh_q15 = { k_iirh_q15, 1u };
#endif

/* ---- hand-written Q15 biquad cascade with ROUND-TO-NEAREST -------------------------------
 * Same coefficient array, same layout {b0,0,b1,b2,a1,a2}, same postShift and same 4-word state
 * as arm_biquad_cascade_df1_q15 - the ONLY difference is that half an output LSB is added before
 * the shift.  CMSIS floors instead (mean error -0.5 LSB).  In a recursive filter that constant
 * is multiplied by the DC gain of 1/A(z) (115x for a 0.5 Hz first-order high-pass), which is
 * the dominant error of iirh_q15.  Rounding removes the bias at the cost of one add per sample. */
#if ECG_ENABLE_IIRH_Q15R
static q15_t st_iirh_q15r[4u * ECG_IIRH_STAGES];

static void init_iirh_q15r(uint32_t blk) { (void)blk; memset(st_iirh_q15r, 0, sizeof(st_iirh_q15r)); }

static void proc_iirh_q15r(const q15_t *in, void *out, uint32_t n)
{
    q15_t *o = (q15_t *)out;
    const int sh = 15 - ECG_IIRH_POSTSHIFT;              /* output = acc >> sh;  sh >= 1 */
    const q15_t *src = in;
    for (uint32_t st = 0; st < ECG_IIRH_STAGES; st++) {
        const q15_t *c = &ecg_iirh_q15[6u * st];
        const int32_t b0 = c[0], b1 = c[2], b2 = c[3], a1 = c[4], a2 = c[5];   /* c[1] is the SIMD pad */
        q15_t *s = &st_iirh_q15r[4u * st];                /* x[n-1], x[n-2], y[n-1], y[n-2] */
        int32_t x1 = s[0], x2 = s[1], y1 = s[2], y2 = s[3];
        for (uint32_t i = 0; i < n; i++) {
            const int32_t x0 = src[i];
            /* 5 products of (Q15 * Q(15-ps)) summed in 64 bit: cannot overflow */
            int64_t acc = (int64_t)b0 * x0 + (int64_t)b1 * x1 + (int64_t)b2 * x2
                        + (int64_t)a1 * y1 + (int64_t)a2 * y2;
            acc += (int64_t)1 << (sh - 1);                /* +0.5 LSB -> round to nearest */
            acc >>= sh;
            const int32_t y0 = (acc > 32767) ? 32767 : (acc < -32768) ? -32768 : (int32_t)acc;   /* saturate */
            x2 = x1; x1 = x0; y2 = y1; y1 = y0;
            o[i] = (q15_t)y0;                             /* stage output (in place for the next stage) */
        }
        s[0] = (q15_t)x1; s[1] = (q15_t)x2; s[2] = (q15_t)y1; s[3] = (q15_t)y2;
        src = o;                                          /* next stage reads this stage's output */
    }
}
static const ecg_impl_t k_iirh_q15r[] = { { "iirh_q15r", ECG_FMT_Q15, init_iirh_q15r, proc_iirh_q15r } };
const ecg_group_t ecg_grp_iirh_q15r = { k_iirh_q15r, 1u };
#endif
