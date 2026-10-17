/* ecg_out.h - tiny printf-free text output (CSV).
 *
 * printf from newlib-nano costs 10-20 KB of flash and a lot of stack; both would distort the
 * very footprint numbers this project reports, so we format numbers by hand.
 */
#ifndef ECG_OUT_H
#define ECG_OUT_H

#include "ecg_config.h"

void ecg_out_puts(const char *s);
void ecg_out_u64(uint64_t v);
void ecg_out_i32(int32_t v);
void ecg_out_fixed3(int64_t num, unsigned frac_bits);   /* prints num / 2^frac_bits, 3 decimals */
void ecg_out_f32_3dp(float v);                          /* prints v with 3 decimals             */
void ecg_out_nl(void);

#endif /* ECG_OUT_H */
