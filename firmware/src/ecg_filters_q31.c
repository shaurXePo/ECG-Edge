/* ecg_filters_q31.c - OPTIONAL Q31 biquad cascade (arm_biquad_cascade_df1_q31).
 *
 * Why it exists: a 0.5 Hz high-pass corner at fs = 360 Hz puts poles at radius ~0.991, i.e.
 * within 0.9 % of the unit circle.  In Q15 the output rounding noise is amplified by the
 * 1/A(z) gain of those poles and the 15-bit coefficients move the poles measurably.  Q31 has
 * 2^16 times finer steps for the price of 2x state memory and 32x32->64 MACs; it shows how
 * much of the Q15 error is *structural* rather than a bug.
 *
 * Input Q15 -> Q31 is a left shift by 16 (arm_q15_to_q31, exact).  The output stays Q31 and is
 * printed in Q15-LSB units with 3 decimals, so it is directly comparable with the other rows.
 */
#include "ecg_impl.h"
#include "ecg_coeffs.h"

#if ECG_ENABLE_IIR_Q31
#define DEF_IIR_Q31(K)                                                                          \
    static arm_biquad_casd_df1_inst_q31 s_iir##K##_q31;                                         \
    static q31_t st_iir##K##_q31[4u * ECG_CAT3(ECG_IIR, K, _STAGES)];                           \
    static void init_iir##K##_q31(uint32_t blk)                                                 \
    {                                                                                           \
        (void)blk;                                                                              \
        arm_biquad_cascade_df1_init_q31(&s_iir##K##_q31, ECG_CAT3(ECG_IIR, K, _STAGES),         \
                                        ecg_iir##K##_q31, st_iir##K##_q31,                      \
                                        ECG_CAT3(ECG_IIR, K, _POSTSHIFT));                      \
    }                                                                                           \
    static void proc_iir##K##_q31(const q15_t *in, void *out, uint32_t n)                       \
    {                                                                                           \
        q31_t tmp[ECG_MAX_BLOCK_SIZE];                                                          \
        arm_q15_to_q31(in, tmp, n);                                                             \
        arm_biquad_cascade_df1_q31(&s_iir##K##_q31, tmp, (q31_t *)out, n);                      \
    }
ECG_IIR_LIST(DEF_IIR_Q31)

#define ENT_IIR_Q31(K) { "iir" #K "_q31", ECG_FMT_Q31, init_iir##K##_q31, proc_iir##K##_q31 },
static const ecg_impl_t k_iir_q31[] = { ECG_IIR_LIST(ENT_IIR_Q31) };
const ecg_group_t ecg_grp_iir_q31 = { k_iir_q31, ECG_ARRAY_LEN(k_iir_q31) };
#endif /* ECG_ENABLE_IIR_Q31 */

#if ECG_ENABLE_IIRH_Q31
static arm_biquad_casd_df1_inst_q31 s_iirh_q31;
static q31_t st_iirh_q31[4u * ECG_IIRH_STAGES];
static void init_iirh_q31(uint32_t blk)
{
    (void)blk;
    arm_biquad_cascade_df1_init_q31(&s_iirh_q31, ECG_IIRH_STAGES, ecg_iirh_q31, st_iirh_q31, ECG_IIRH_POSTSHIFT);
}
static void proc_iirh_q31(const q15_t *in, void *out, uint32_t n)
{
    q31_t tmp[ECG_MAX_BLOCK_SIZE];
    arm_q15_to_q31(in, tmp, n);
    arm_biquad_cascade_df1_q31(&s_iirh_q31, tmp, (q31_t *)out, n);
}
static const ecg_impl_t k_iirh_q31[] = { { "iirh_q31", ECG_FMT_Q31, init_iirh_q31, proc_iirh_q31 } };
const ecg_group_t ecg_grp_iirh_q31 = { k_iirh_q31, 1u };
#endif
