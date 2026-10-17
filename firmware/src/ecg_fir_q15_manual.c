/* ecg_fir_q15_manual.c - HAND-WRITTEN Q15 FIR with SATURATING 32-bit accumulation.
 *
 * Purpose: show exactly what a fixed-point FIR does, and what CMSIS-DSP buys you.
 *
 *   product  : Q15 * Q15 = Q30 in an int32  (|p| <= 2^30, never overflows by itself)
 *   accum    : Q30 in an int32 using a SATURATING add (QADD on Cortex-M4)
 *   rounding : + 2^14 (half an output LSB) before the shift  -> round-to-nearest
 *   output   : acc >> 15  (Q30 -> Q15), then clamp to [-32768, 32767]
 *
 * Differences from arm_fir_q15 (these are the interesting trade-offs):
 *   + 32-bit accumulator: cheaper registers, but it can only hold +/-2.0 in Q30.  A partial sum
 *     beyond that would WRAP with plain '+' (a huge glitch); the saturating add clips instead
 *     (a small, ugly-but-bounded error).  CMSIS uses a 64-bit accumulator and cannot overflow
 *     for any realistic tap count.
 *   + rounding instead of truncation -> no -0.5 LSB DC bias.
 *   - one MAC per loop iteration, no SIMD dual-MAC -> expect several times more cycles/sample
 *     than arm_fir_q15 (measure it!).
 *
 * Coefficients use the SAME time-reversed array as CMSIS (ecg_fir<N>_q15), so both
 * implementations are fed from identical data.
 */
#include "ecg_impl.h"
#include "ecg_coeffs.h"

#if ECG_ENABLE_FIR_Q15M

/* Saturating 32-bit add.  On M4 this is the single instruction QADD. */
static inline int32_t sat_add32(int32_t a, int32_t b)
{
#if defined(__ARM_FEATURE_DSP) && (__ARM_FEATURE_DSP == 1)
    return (int32_t)__QADD(a, b);
#else
    int64_t s = (int64_t)a + (int64_t)b;
    return (s > INT32_MAX) ? INT32_MAX : (s < INT32_MIN) ? INT32_MIN : (int32_t)s;
#endif
}

static inline q15_t sat16(int32_t v)
{
    return (q15_t)((v > 32767) ? 32767 : (v < -32768) ? -32768 : v);
}

typedef struct {
    uint16_t       taps;
    const q15_t   *coef;        /* time-reversed: coef[0] multiplies the OLDEST sample */
    q15_t         *hist;        /* [taps-1 history samples][up to ECG_MAX_BLOCK_SIZE new samples] */
} fir_q15m_t;

static void fir_q15m_reset(fir_q15m_t *s)
{
    memset(s->hist, 0, ((size_t)s->taps - 1u + ECG_MAX_BLOCK_SIZE) * sizeof(q15_t));
}

static void fir_q15m_process(fir_q15m_t *s, const q15_t *in, q15_t *out, uint32_t n)
{
    const uint32_t T = s->taps;
    q15_t *buf = s->hist;
    memcpy(buf + (T - 1u), in, n * sizeof(q15_t));      /* append new block after the history */

    for (uint32_t i = 0; i < n; i++) {
        const q15_t *x = buf + i;                       /* x[0] = oldest sample of this window */
        int32_t acc = 0;
        for (uint32_t k = 0; k < T; k++) {
            acc = sat_add32(acc, (int32_t)s->coef[k] * (int32_t)x[k]);   /* Q15*Q15 = Q30 */
        }
        acc = sat_add32(acc, 1 << 14);                  /* +0.5 LSB: round to nearest */
        out[i] = sat16(acc >> 15);                      /* Q30 -> Q15, clamp */
    }
    memmove(buf, buf + n, (T - 1u) * sizeof(q15_t));    /* keep the last T-1 samples as history */
}

#define DEF_FIR_Q15M(N)                                                                         \
    static q15_t st_fir##N##_q15m[ECG_CAT3(ECG_FIR, N, _NTAPS) - 1u + ECG_MAX_BLOCK_SIZE];      \
    static fir_q15m_t s_fir##N##_q15m = { ECG_CAT3(ECG_FIR, N, _NTAPS), ecg_fir##N##_q15,       \
                                          st_fir##N##_q15m };                                   \
    static void init_fir##N##_q15m(uint32_t blk) { (void)blk; fir_q15m_reset(&s_fir##N##_q15m); } \
    static void proc_fir##N##_q15m(const q15_t *in, void *out, uint32_t n)                      \
    {                                                                                           \
        fir_q15m_process(&s_fir##N##_q15m, in, (q15_t *)out, n);                                \
    }
ECG_FIR_LIST(DEF_FIR_Q15M)

#define ENT_FIR_Q15M(N) { "fir" #N "_q15m", ECG_FMT_Q15, init_fir##N##_q15m, proc_fir##N##_q15m },
static const ecg_impl_t k_fir_q15m[] = { ECG_FIR_LIST(ENT_FIR_Q15M) };
const ecg_group_t ecg_grp_fir_q15m = { k_fir_q15m, ECG_ARRAY_LEN(k_fir_q15m) };

#endif /* ECG_ENABLE_FIR_Q15M */
