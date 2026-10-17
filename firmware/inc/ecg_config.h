/* ecg_config.h - compile-time configuration shared by all hardware-independent code.
 *
 * Every tunable has a default here and can be overridden from the build system
 * (CMake: -DECG_BLOCK_SIZE=64, PlatformIO: build_flags = -DECG_BLOCK_SIZE=64).
 */
#ifndef ECG_CONFIG_H
#define ECG_CONFIG_H

#include <stdint.h>
#include <stddef.h>
#include "arm_math.h"          /* CMSIS-DSP: q15_t, q31_t, float32_t, arm_fir_q15(), ... */
#include "ecg_params.h"        /* GENERATED: sample rate, tap counts, post-shifts, X-macro lists */

/* ---- Block processing --------------------------------------------------------------
 * ECG_BLOCK_SIZE     default number of samples handed to a filter per call.
 *                    36 samples @ 360 Hz = 100 ms: small enough for low latency,
 *                    large enough that per-call overhead (function call, state load) is
 *                    amortised.  The firmware also sweeps other sizes (see ecg_app.c).
 * ECG_MAX_BLOCK_SIZE upper bound; ALL state buffers are sized for it so the block size can
 *                    change at run time without reallocating (CMSIS FIR needs
 *                    numTaps + blockSize state words).
 */
#ifndef ECG_MAX_BLOCK_SIZE
#define ECG_MAX_BLOCK_SIZE 128u
#endif
#ifndef ECG_BLOCK_SIZE
#define ECG_BLOCK_SIZE 36u
#endif
#if ECG_BLOCK_SIZE > ECG_MAX_BLOCK_SIZE
#error "ECG_BLOCK_SIZE must be <= ECG_MAX_BLOCK_SIZE"
#endif

/* ---- Implementation groups (set to 0 to drop a group from the image) ----------------
 * Used by scripts/footprint.py to measure the flash/RAM cost of each group in isolation:
 * a disabled group is not referenced, so --gc-sections removes its code, coefficients and state. */
#ifndef ECG_ENABLE_FIR_F32
#define ECG_ENABLE_FIR_F32 1     /* arm_fir_f32            (float reference)            */
#endif
#ifndef ECG_ENABLE_FIR_Q15
#define ECG_ENABLE_FIR_Q15 1     /* arm_fir_q15            (CMSIS, SIMD, 64-bit acc)    */
#endif
#ifndef ECG_ENABLE_FIR_Q15M
#define ECG_ENABLE_FIR_Q15M 1    /* hand-written Q15 FIR   (32-bit saturating acc)      */
#endif
#ifndef ECG_ENABLE_IIR_F32
#define ECG_ENABLE_IIR_F32 1     /* arm_biquad_cascade_df2T_f32                         */
#endif
#ifndef ECG_ENABLE_IIR_Q15
#define ECG_ENABLE_IIR_Q15 1     /* arm_biquad_cascade_df1_q15 (+ postShift)            */
#endif
#ifndef ECG_ENABLE_IIR_Q31
#define ECG_ENABLE_IIR_Q31 1     /* arm_biquad_cascade_df1_q31 (+ postShift)            */
#endif
#ifndef ECG_ENABLE_IIRH_F32
#define ECG_ENABLE_IIRH_F32 1    /* "hp1" structure, float DF2T                          */
#endif
#ifndef ECG_ENABLE_IIRH_Q15
#define ECG_ENABLE_IIRH_Q15 1    /* "hp1" structure, CMSIS Q15 DF1 (truncating)          */
#endif
#ifndef ECG_ENABLE_IIRH_Q15R
#define ECG_ENABLE_IIRH_Q15R 1   /* "hp1" structure, hand-written Q15 DF1 (rounding)     */
#endif
#ifndef ECG_ENABLE_IIRH_Q31
#define ECG_ENABLE_IIRH_Q31 1    /* "hp1" structure, CMSIS Q31 DF1                       */
#endif
#ifndef ECG_ENABLE_PT
#define ECG_ENABLE_PT 1          /* fixed-point Pan-Tompkins R-peak detector            */
#endif

/* Max number of R-peaks the detector can remember (4 bytes each). 10 s of ECG needs < 30. */
#ifndef ECG_PT_MAX_PEAKS
#define ECG_PT_MAX_PEAKS 128u
#endif

/* ---- Output ------------------------------------------------------------------------- */
#ifndef ECG_UART_BAUD
#define ECG_UART_BAUD 115200u
#endif

/* ---- Helpers for X-macro token pasting ---------------------------------------------- */
#define ECG_CAT2_(a, b)    a##b
#define ECG_CAT2(a, b)     ECG_CAT2_(a, b)
#define ECG_CAT3_(a, b, c) a##b##c
#define ECG_CAT3(a, b, c)  ECG_CAT3_(a, b, c)
#define ECG_XSTR_(x)       #x
#define ECG_STR(x)         ECG_XSTR_(x)

#define ECG_ARRAY_LEN(a)   (sizeof(a) / sizeof((a)[0]))

#endif /* ECG_CONFIG_H */
