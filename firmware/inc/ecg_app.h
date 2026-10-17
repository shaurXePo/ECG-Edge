/* ecg_app.h - the portable application: benchmark every implementation, dump CSV. */
#ifndef ECG_APP_H
#define ECG_APP_H

#include "ecg_config.h"

typedef struct {
    uint32_t    block;      /* block size for the main (dumped) pass                          */
    int         dump;       /* 1: print every output sample as CSV (needed for validation)    */
    int         sweep;      /* 1: also sweep block sizes and print #SWEEP lines (timing only) */
    int         pt_only;    /* 1: run only the Pan-Tompkins detector (long records on host)   */
    const char *only;       /* if non-NULL, run only the implementation with this exact name  */
} ecg_app_opts_t;

void ecg_app_default_opts(ecg_app_opts_t *o);
int  ecg_app_run(const ecg_app_opts_t *o);      /* returns 0 on success */

#endif /* ECG_APP_H */
