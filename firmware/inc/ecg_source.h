/* ecg_source.h - the INPUT SOURCE abstraction (hardware-independent).
 *
 * The pipeline pulls blocks of Q15 samples from a source.  Two implementations are provided:
 *
 *   ecg_source_vector : replays the int16 test vector stored in flash (used for validation,
 *                       because it is deterministic and comparable with the Python reference).
 *   ecg_source_ring   : THE HOOK FOR A REAL STREAM.  An ISR calls ecg_source_ring_push()
 *                       once per sample (ADC end-of-conversion interrupt, or UART RX
 *                       interrupt) and the pipeline's read() drains whole blocks.
 *
 * Wiring a real ADC on an STM32F4 (sketch - board specific, so NOT in this layer):
 *     TIM2 update event @ 360 Hz  --(TRGO)-->  ADC1 regular conversion (12 bit)
 *     ADC_IRQHandler():  ecg_source_ring_push((q15_t)(((int32_t)ADC1->DR - 2048) << 4));
 *                         ^ 12-bit unsigned (0..4095) -> remove mid-scale -> left-align to Q15
 *     main loop: ecg_pipeline_run(impl, &ecg_source_ring, ...)
 * A hardware timer (not a software delay!) must pace the sampling, otherwise the sampling
 * period jitters and the filter's frequency response is no longer what you designed.
 */
#ifndef ECG_SOURCE_H
#define ECG_SOURCE_H

#include "ecg_config.h"

typedef struct {
    const char *name;
    void     (*rewind)(void);                    /* restart the stream; NULL if not rewindable */
    uint32_t (*read)(q15_t *dst, uint32_t max);  /* copy up to `max` samples, return count; 0 = end of stream */
} ecg_source_t;

extern const ecg_source_t ecg_source_vector;     /* stored test vector                    */
extern const ecg_source_t ecg_source_ring;       /* ISR-fed ring buffer (ADC / UART hook) */

/* ring-source API (called from interrupt context, single producer) */
void     ecg_source_ring_push(q15_t sample);     /* returns silently (and counts) if the ring is full */
void     ecg_source_ring_close(void);            /* signal end-of-stream so read() can return 0       */
uint32_t ecg_source_ring_overruns(void);         /* how many samples were dropped (consumer too slow) */

#endif /* ECG_SOURCE_H */
