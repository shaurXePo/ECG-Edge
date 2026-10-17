/* ecg_source_vector.c - replays the int16 test vector that lives in flash. */
#include "ecg_source.h"
#include "ecg_testvec.h"          /* GENERATED: static const int16_t ecg_testvec[ECG_N_SAMPLES] */

static uint32_t s_pos;

static void vec_rewind(void) { s_pos = 0u; }

static uint32_t vec_read(q15_t *dst, uint32_t max)
{
    uint32_t left = ECG_N_SAMPLES - s_pos;
    uint32_t n = (max < left) ? max : left;
    memcpy(dst, &ecg_testvec[s_pos], n * sizeof(q15_t));   /* int16_t and q15_t are the same type */
    s_pos += n;
    return n;
}

const ecg_source_t ecg_source_vector = { "vector", vec_rewind, vec_read };
