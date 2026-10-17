/* ecg_impl.h - uniform descriptor for every filter implementation.
 *
 * The pipeline does not care whether a filter is float, Q15 or Q31, FIR or IIR: it only sees
 * { name, output format, init(), process() }.  That is what lets one benchmark loop time all
 * of them identically.
 */
#ifndef ECG_IMPL_H
#define ECG_IMPL_H

#include "ecg_config.h"

typedef enum { ECG_FMT_Q15 = 0, ECG_FMT_Q31 = 1, ECG_FMT_F32 = 2 } ecg_fmt_t;

typedef struct {
    const char *name;                       /* e.g. "fir127_q15"  - must match scripts/validate.py */
    ecg_fmt_t   fmt;                        /* element type written to `out`                        */
    void (*init)(uint32_t block);           /* reset filter state (zeros) for the given block size  */
    void (*process)(const q15_t *in, void *out, uint32_t n);   /* filter n <= block samples        */
} ecg_impl_t;

typedef struct {
    const ecg_impl_t *impls;
    uint32_t          count;
} ecg_group_t;

/* Registry: array of pointers to every ENABLED group (defined in ecg_registry.c). */
extern const ecg_group_t *const ecg_groups[];
extern const uint32_t           ecg_group_count;

static inline uint32_t ecg_fmt_size(ecg_fmt_t f) { return (f == ECG_FMT_Q15) ? 2u : 4u; }

#endif /* ECG_IMPL_H */
