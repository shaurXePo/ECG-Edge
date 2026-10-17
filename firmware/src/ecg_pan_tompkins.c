/* ecg_pan_tompkins.c - fixed-point (integer only) Pan-Tompkins style R-peak detector.
 *
 * Pipeline (all integer arithmetic, no float, no division except one /54):
 *
 *   x (Q15) -> band-pass 5-15 Hz (2 biquads, Q15 DF1) -> derivative -> squaring
 *           -> moving-window integration (150 ms) -> adaptive thresholds -> R peak
 *
 * Fixed-point bookkeeping (the part that is easy to get wrong):
 *   band-pass out : Q15 (int16)
 *   derivative    : d = (2x[n] + x[n-1] - x[n-3] - 2x[n-4]) >> 3 .  Worst case |d| <= 6*32767/8
 *                   = 24575, so it still fits an int16: no saturation needed.
 *   squaring      : d*d fits int32 (<= 6.1e8).  We do NOT shift back to Q15 here: real QRS
 *                   slopes are only a few hundred LSB, so d*d>>15 would be ~10 and the
 *                   threshold logic would run on 3-4 bits of resolution.  Instead we keep 32 bits
 *                   and drop only PT_SQ_SHIFT=6 bits so that the window sum cannot overflow:
 *                   54 * (6.1e8 >> 6) = 5.1e8 < 2^32.
 *   MWI           : sum of the last PT_MWI_LEN squared values / PT_MWI_LEN   (uint32 -> int32)
 *
 * Decision logic follows Pan & Tompkins (IEEE TBME 1985) with the usual simplifications:
 *   SPKI/NPKI running estimates of signal / noise peak level (1/8 forgetting factor),
 *   THR1 = NPKI + (SPKI-NPKI)/4, THR2 = THR1/2 (search-back), 200 ms refractory period,
 *   T-wave rejection (candidate within 360 ms whose slope < half of the previous QRS slope),
 *   search-back when no beat for 1.66 x average RR.
 * Not implemented: the 2-s learning phase (we boot SPKI from the first accepted peak) and the
 * second (band-passed signal) threshold pair of the original paper.
 *
 * Time base: the original paper is tuned for fs = 200 Hz; all windows here are expressed in
 * milliseconds and converted with ECG_FS_HZ, so they scale to 360 Hz automatically.  The
 * 5-point derivative is kept as is (its passband shifts upward at 360 Hz, which is harmless
 * because the band-pass already limits the spectrum).
 */
#include "ecg_impl.h"
#include "ecg_coeffs.h"
#include "ecg_pan_tompkins.h"

#if ECG_ENABLE_PT

#define MS(ms)          (((int32_t)(ms) * (int32_t)ECG_FS_HZ) / 1000)
#define PT_MWI_LEN      MS(150)      /* 150 ms integration window = 54 samples @ 360 Hz       */
#define PT_REFRACT      MS(200)      /* physiological refractory period: no two QRS closer     */
#define PT_TWAVE        MS(360)      /* T-wave discrimination window                           */
#define PT_SQ_SHIFT     6            /* bits dropped after squaring so MWI sum fits 32 bit     */
#define PT_MIN_THR      32           /* absolute floor of the MWI threshold (~ amplifier noise).
                                        Units: MWI counts; depends on ECG_FULLSCALE_UV!        */
#define PT_RING         128u         /* power of two >= PT_MWI_LEN + 2; ring of recent samples */
#define PT_RING_MASK    (PT_RING - 1u)

typedef struct {
    /* front end */
    q15_t    xd[5];                      /* x[n] .. x[n-4] */
    uint32_t sq_ring[MS(150) + 1];       /* squared values in the MWI window                */
    uint32_t sq_pos, sq_sum;
    q15_t    bp_ring[PT_RING];           /* band-passed samples (for R-peak localisation)   */
    uint16_t da_ring[PT_RING];           /* |derivative| (for slope / T-wave test)          */
    int32_t  m1, m2;                     /* MWI at n-1 and n-2: 3-point local-max detector  */
    int32_t  n;                          /* index of the sample being processed             */
    /* decision */
    int32_t  spki, npki, thr1;
    int32_t  last_p, last_r, last_slope; /* last accepted peak: MWI index, R index, slope   */
    int32_t  rr_avg;                     /* running average RR interval [samples]           */
    uint8_t  have_first;
    /* search-back candidate (best sub-threshold peak since last QRS) */
    int32_t  sb_peak, sb_p, sb_r, sb_slope;
    /* output */
    int32_t  peaks[ECG_PT_MAX_PEAKS];
    uint32_t n_peaks;
} pt_t;

static pt_t s_pt;
static arm_biquad_casd_df1_inst_q15 s_pt_bp;
static q15_t st_pt_bp[4u * ECG_PT_STAGES] __attribute__((aligned(4)));

uint32_t ecg_pt_peak_count(void)          { return s_pt.n_peaks; }
int32_t  ecg_pt_peak_index(uint32_t i)    { return (i < s_pt.n_peaks) ? s_pt.peaks[i] : -1; }

/* Locate the R peak and the steepest slope in the MWI-window that ends at index p. */
static void localise(const pt_t *s, int32_t p, int32_t *r_idx, int32_t *slope)
{
    int32_t lo = p - PT_MWI_LEN; if (lo < 0) lo = 0;
    int32_t best_abs = -1, best_i = p, smax = 0;
    for (int32_t i = lo; i <= p; i++) {
        int32_t a = s->bp_ring[(uint32_t)i & PT_RING_MASK];
        a = (a < 0) ? -a : a;
        if (a > best_abs) { best_abs = a; best_i = i; }
        int32_t d = s->da_ring[(uint32_t)i & PT_RING_MASK];
        if (d > smax) smax = d;
    }
    *r_idx = best_i;
    *slope = smax;
}

static void accept(pt_t *s, int32_t p, int32_t r, int32_t slope, int32_t peak, int shift)
{
    if (!s->have_first) {
        s->spki = peak;                                   /* boot the signal level from first peak */
    } else {
        s->spki += (peak - s->spki) >> shift;             /* SPKI = 0.875 SPKI + 0.125 peak (or 0.75/0.25) */
        int32_t rr = p - s->last_p;
        s->rr_avg += (rr - s->rr_avg) >> 3;               /* RR average, 1/8 forgetting factor */
    }
    s->have_first = 1;
    s->last_p = p; s->last_r = r; s->last_slope = slope;
    s->sb_peak = 0;                                        /* new beat: search-back starts over */
    if (s->n_peaks < ECG_PT_MAX_PEAKS) s->peaks[s->n_peaks++] = r;
}

static void candidate(pt_t *s, int32_t p, int32_t peak)
{
    if (s->have_first && (p - s->last_p) < PT_REFRACT) return;   /* inside refractory period */

    int32_t r, slope;
    localise(s, p, &r, &slope);

    if (peak > s->thr1) {
        if (s->have_first && (p - s->last_p) < PT_TWAVE && slope < (s->last_slope >> 1)) {
            s->npki += (peak - s->npki) >> 3;              /* gentle slope shortly after QRS: T wave */
        } else {
            accept(s, p, r, slope, peak, 3);
        }
    } else {
        s->npki += (peak - s->npki) >> 3;                  /* below threshold: update noise level */
        if (peak > (s->thr1 >> 1) && peak > s->sb_peak) {  /* remember best sub-threshold peak */
            s->sb_peak = peak; s->sb_p = p; s->sb_r = r; s->sb_slope = slope;
        }
    }
    s->thr1 = s->npki + ((s->spki - s->npki) >> 2);        /* THR1 = NPKI + 0.25 (SPKI - NPKI) */
    if (s->thr1 < PT_MIN_THR) s->thr1 = PT_MIN_THR;
}

/* Process one band-passed sample; returns the MWI value (for debug output). */
static int32_t pt_push(pt_t *s, q15_t xbp)
{
    const int32_t n = s->n++;
    s->bp_ring[(uint32_t)n & PT_RING_MASK] = xbp;

    /* 5-point derivative */
    s->xd[4] = s->xd[3]; s->xd[3] = s->xd[2]; s->xd[2] = s->xd[1]; s->xd[1] = s->xd[0]; s->xd[0] = xbp;
    int32_t d = (2 * s->xd[0] + s->xd[1] - s->xd[3] - 2 * s->xd[4]) >> 3;
    s->da_ring[(uint32_t)n & PT_RING_MASK] = (uint16_t)((d < 0) ? -d : d);

    /* squaring (32 bit), then moving-window integration */
    uint32_t sq = ((uint32_t)(d * d)) >> PT_SQ_SHIFT;
    s->sq_sum += sq - s->sq_ring[s->sq_pos];
    s->sq_ring[s->sq_pos] = sq;
    if (++s->sq_pos >= (uint32_t)PT_MWI_LEN) s->sq_pos = 0;
    int32_t m = (int32_t)(s->sq_sum / (uint32_t)PT_MWI_LEN);

    /* local maximum of the MWI at n-1 */
    if (n >= 2 && s->m1 > s->m2 && s->m1 >= m && s->m1 > PT_MIN_THR) candidate(s, n - 1, s->m1);
    s->m2 = s->m1; s->m1 = m;

    /* search-back: no beat for 1.66 RR -> accept the best sub-threshold candidate */
    if (s->have_first && s->sb_peak > 0 && (n - s->last_p) > (s->rr_avg * 166) / 100) {
        accept(s, s->sb_p, s->sb_r, s->sb_slope, s->sb_peak, 2);
        s->thr1 = s->npki + ((s->spki - s->npki) >> 2);
        if (s->thr1 < PT_MIN_THR) s->thr1 = PT_MIN_THR;
    }
    return m;
}

/* ---- impl glue ----------------------------------------------------------------------- */
static void init_pt(uint32_t blk)
{
    (void)blk;
    memset(&s_pt, 0, sizeof(s_pt));
    s_pt.thr1   = PT_MIN_THR;
    s_pt.rr_avg = MS(800);                                /* start assuming 75 bpm */
    arm_biquad_cascade_df1_init_q15(&s_pt_bp, ECG_PT_STAGES, ecg_pt_bp_q15, st_pt_bp, ECG_PT_POSTSHIFT);
}

/* Output = MWI waveform (clipped to Q15) so the detector's internal signal can be plotted. */
static void proc_pt(const q15_t *in, void *out, uint32_t n)
{
    q15_t bp[ECG_MAX_BLOCK_SIZE];
    q15_t *o = (q15_t *)out;
    arm_biquad_cascade_df1_q15(&s_pt_bp, in, bp, n);
    for (uint32_t i = 0; i < n; i++) {
        int32_t m = pt_push(&s_pt, bp[i]);
        o[i] = (q15_t)((m > 32767) ? 32767 : m);
    }
}

static const ecg_impl_t k_pt[] = { { "pt_q15", ECG_FMT_Q15, init_pt, proc_pt } };
const ecg_group_t ecg_grp_pt = { k_pt, 1u };

#endif /* ECG_ENABLE_PT */
