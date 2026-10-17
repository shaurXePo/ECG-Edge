/* ecg_registry.c - collects every ENABLED implementation group into one table. */
#include "ecg_impl.h"

#if ECG_ENABLE_FIR_F32
extern const ecg_group_t ecg_grp_fir_f32;
#endif
#if ECG_ENABLE_FIR_Q15
extern const ecg_group_t ecg_grp_fir_q15;
#endif
#if ECG_ENABLE_FIR_Q15M
extern const ecg_group_t ecg_grp_fir_q15m;
#endif
#if ECG_ENABLE_IIR_F32
extern const ecg_group_t ecg_grp_iir_f32;
#endif
#if ECG_ENABLE_IIR_Q15
extern const ecg_group_t ecg_grp_iir_q15;
#endif
#if ECG_ENABLE_IIR_Q31
extern const ecg_group_t ecg_grp_iir_q31;
#endif
#if ECG_ENABLE_IIRH_F32
extern const ecg_group_t ecg_grp_iirh_f32;
#endif
#if ECG_ENABLE_IIRH_Q15
extern const ecg_group_t ecg_grp_iirh_q15;
#endif
#if ECG_ENABLE_IIRH_Q15R
extern const ecg_group_t ecg_grp_iirh_q15r;
#endif
#if ECG_ENABLE_IIRH_Q31
extern const ecg_group_t ecg_grp_iirh_q31;
#endif
#if ECG_ENABLE_PT
extern const ecg_group_t ecg_grp_pt;
#endif

/* Order here = order of sections in the CSV log. */
const ecg_group_t *const ecg_groups[] = {
#if ECG_ENABLE_FIR_F32
    &ecg_grp_fir_f32,
#endif
#if ECG_ENABLE_FIR_Q15
    &ecg_grp_fir_q15,
#endif
#if ECG_ENABLE_FIR_Q15M
    &ecg_grp_fir_q15m,
#endif
#if ECG_ENABLE_IIR_F32
    &ecg_grp_iir_f32,
#endif
#if ECG_ENABLE_IIR_Q15
    &ecg_grp_iir_q15,
#endif
#if ECG_ENABLE_IIR_Q31
    &ecg_grp_iir_q31,
#endif
#if ECG_ENABLE_IIRH_F32
    &ecg_grp_iirh_f32,
#endif
#if ECG_ENABLE_IIRH_Q15
    &ecg_grp_iirh_q15,
#endif
#if ECG_ENABLE_IIRH_Q15R
    &ecg_grp_iirh_q15r,
#endif
#if ECG_ENABLE_IIRH_Q31
    &ecg_grp_iirh_q31,
#endif
#if ECG_ENABLE_PT
    &ecg_grp_pt,
#endif
    NULL   /* keeps the array non-empty when every group is disabled (footprint baseline) */
};

const uint32_t ecg_group_count = (uint32_t)(ECG_ARRAY_LEN(ecg_groups) - 1u);
