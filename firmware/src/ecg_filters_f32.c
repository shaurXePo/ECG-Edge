/* ecg_filters_f32.c - single-precision REFERENCE implementations (CMSIS-DSP).
 *
 *   fir<N>_f32 : arm_fir_f32                       (direct form, FPU MAC)
 *   iir<K>_f32 : arm_biquad_cascade_df2T_f32       (transposed direct form II)
 *
 * Input arrives as Q15 integers (what an ADC delivers).  arm_q15_to_float() converts to
 * floats in [-1, 1); the conversion is INSIDE the timed region because a real float
 * pipeline would pay for it too.  Output stays float, normalised so that 1.0 == full scale
 * (the CSV writer multiplies by 32768 so every implementation is reported in int16 LSBs).
 *
 * Note on DF2T vs DF1: transposed DF2 is the preferred float structure (good numerical
 * behaviour, only 2 state words per section).  DF1 is the preferred FIXED-point structure
 * (the 64-bit accumulator can absorb all five products without intermediate overflow).
 */
#include "ecg_impl.h"
#include "ecg_coeffs.h"

#if ECG_ENABLE_FIR_F32
#define DEF_FIR_F32(N)                                                                          \
    static arm_fir_instance_f32 s_fir##N##_f32;                                                 \
    /* CMSIS FIR state = numTaps + blockSize - 1 words; sized for the MAX block size */         \
    static float32_t st_fir##N##_f32[ECG_CAT3(ECG_FIR, N, _NTAPS) + ECG_MAX_BLOCK_SIZE];        \
    static void init_fir##N##_f32(uint32_t blk)                                                 \
    {                                                                                           \
        arm_fir_init_f32(&s_fir##N##_f32, ECG_CAT3(ECG_FIR, N, _NTAPS), ecg_fir##N##_f32,       \
                         st_fir##N##_f32, blk);                                                 \
    }                                                                                           \
    static void proc_fir##N##_f32(const q15_t *in, void *out, uint32_t n)                       \
    {                                                                                           \
        float32_t tmp[ECG_MAX_BLOCK_SIZE];                                                      \
        arm_q15_to_float(in, tmp, n);                                                           \
        arm_fir_f32(&s_fir##N##_f32, tmp, (float32_t *)out, n);                                 \
    }
ECG_FIR_LIST(DEF_FIR_F32)

#define ENT_FIR_F32(N) { "fir" #N "_f32", ECG_FMT_F32, init_fir##N##_f32, proc_fir##N##_f32 },
static const ecg_impl_t k_fir_f32[] = { ECG_FIR_LIST(ENT_FIR_F32) };
const ecg_group_t ecg_grp_fir_f32 = { k_fir_f32, ECG_ARRAY_LEN(k_fir_f32) };
#endif /* ECG_ENABLE_FIR_F32 */

#if ECG_ENABLE_IIR_F32
#define DEF_IIR_F32(K)                                                                          \
    static arm_biquad_cascade_df2T_instance_f32 s_iir##K##_f32;                                 \
    static float32_t st_iir##K##_f32[2u * ECG_CAT3(ECG_IIR, K, _STAGES)]; /* 2 words / stage */  \
    static void init_iir##K##_f32(uint32_t blk)                                                 \
    {                                                                                           \
        (void)blk;                                                                              \
        arm_biquad_cascade_df2T_init_f32(&s_iir##K##_f32, ECG_CAT3(ECG_IIR, K, _STAGES),        \
                                         ecg_iir##K##_f32, st_iir##K##_f32);                    \
        memset(st_iir##K##_f32, 0, sizeof(st_iir##K##_f32));                                    \
    }                                                                                           \
    static void proc_iir##K##_f32(const q15_t *in, void *out, uint32_t n)                       \
    {                                                                                           \
        float32_t tmp[ECG_MAX_BLOCK_SIZE];                                                      \
        arm_q15_to_float(in, tmp, n);                                                           \
        arm_biquad_cascade_df2T_f32(&s_iir##K##_f32, tmp, (float32_t *)out, n);                 \
    }
ECG_IIR_LIST(DEF_IIR_F32)

#define ENT_IIR_F32(K) { "iir" #K "_f32", ECG_FMT_F32, init_iir##K##_f32, proc_iir##K##_f32 },
static const ecg_impl_t k_iir_f32[] = { ECG_IIR_LIST(ENT_IIR_F32) };
const ecg_group_t ecg_grp_iir_f32 = { k_iir_f32, ECG_ARRAY_LEN(k_iir_f32) };
#endif /* ECG_ENABLE_IIR_F32 */

/* "hp1" structure: 2 first-order high-passes + Butterworth low-pass + notch (see scripts/common.py) */
#if ECG_ENABLE_IIRH_F32
static arm_biquad_cascade_df2T_instance_f32 s_iirh_f32;
static float32_t st_iirh_f32[2u * ECG_IIRH_STAGES];
static void init_iirh_f32(uint32_t blk)
{
    (void)blk;
    arm_biquad_cascade_df2T_init_f32(&s_iirh_f32, ECG_IIRH_STAGES, ecg_iirh_f32, st_iirh_f32);
    memset(st_iirh_f32, 0, sizeof(st_iirh_f32));
}
static void proc_iirh_f32(const q15_t *in, void *out, uint32_t n)
{
    float32_t tmp[ECG_MAX_BLOCK_SIZE];
    arm_q15_to_float(in, tmp, n);
    arm_biquad_cascade_df2T_f32(&s_iirh_f32, tmp, (float32_t *)out, n);
}
static const ecg_impl_t k_iirh_f32[] = { { "iirh_f32", ECG_FMT_F32, init_iirh_f32, proc_iirh_f32 } };
const ecg_group_t ecg_grp_iirh_f32 = { k_iirh_f32, 1u };
#endif
