/* main_stm32f4.c - entry point for the Cortex-M4 targets: run the portable app once, then idle. */
#include "ecg_app.h"
#include "ecg_platform.h"

int main(void)
{
    ecg_app_opts_t o;
    ecg_app_default_opts(&o);       /* block = ECG_BLOCK_SIZE, dump everything, sweep block sizes */
    int rc = ecg_app_run(&o);
    platform_exit(rc);
}
