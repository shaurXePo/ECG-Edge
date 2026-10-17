/* ecg_out.c - minimal number formatting on top of platform_putc(). */
#include "ecg_out.h"
#include "ecg_platform.h"

void ecg_out_puts(const char *s) { while (*s) platform_putc(*s++); }
void ecg_out_nl(void)            { platform_putc('\n'); }

void ecg_out_u64(uint64_t v)
{
    char b[21]; int i = 0;
    do { b[i++] = (char)('0' + (v % 10u)); v /= 10u; } while (v);
    while (i) platform_putc(b[--i]);
}

void ecg_out_i32(int32_t v)
{
    if (v < 0) { platform_putc('-'); ecg_out_u64((uint64_t)(-(int64_t)v)); }
    else       { ecg_out_u64((uint64_t)v); }
}

/* Print a value that is already expressed in thousandths ("milli" units), e.g. -1234 -> -1.234 */
static void put_milli(int64_t milli)
{
    uint64_t a;
    if (milli < 0) { platform_putc('-'); a = (uint64_t)(-milli); } else { a = (uint64_t)milli; }
    ecg_out_u64(a / 1000u);
    platform_putc('.');
    uint32_t f = (uint32_t)(a % 1000u);
    platform_putc((char)('0' + f / 100u));
    platform_putc((char)('0' + (f / 10u) % 10u));
    platform_putc((char)('0' + f % 10u));
}

/* Print num / 2^frac_bits with exactly 3 decimals, rounded to nearest (ties away from zero). */
void ecg_out_fixed3(int64_t num, unsigned frac_bits)
{
    const int neg = (num < 0);
    uint64_t a = neg ? (uint64_t)(-num) : (uint64_t)num;
    uint64_t half = frac_bits ? (1ull << (frac_bits - 1u)) : 0ull;
    int64_t milli = (int64_t)((a * 1000u + half) >> frac_bits);
    put_milli(neg ? -milli : milli);
}

void ecg_out_f32_3dp(float v)
{
    float s = v * 1000.0f;                       /* thousandths; fits int32 for |v| < 2e6 */
    int32_t m = (int32_t)(s + ((s >= 0.0f) ? 0.5f : -0.5f));
    put_milli((int64_t)m);
}
