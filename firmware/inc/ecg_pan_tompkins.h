/* ecg_pan_tompkins.h - fixed-point Pan-Tompkins style QRS detector (hardware independent). */
#ifndef ECG_PAN_TOMPKINS_H
#define ECG_PAN_TOMPKINS_H

#include "ecg_config.h"

#if ECG_ENABLE_PT
/* Number of R-peaks found by the most recent pass (cleared by the impl's init()). */
uint32_t        ecg_pt_peak_count(void);
/* Sample index (0-based, in the INPUT time base + band-pass delay) of the i-th detected R peak. */
int32_t         ecg_pt_peak_index(uint32_t i);
#endif

#endif /* ECG_PAN_TOMPKINS_H */
